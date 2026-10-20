"""Staged opponent lookup pipeline.

All network I/O runs on a ``ThreadPoolExecutor``. Each finished stage emits
``update(LookupUpdate)`` from the worker thread; the pipeline object lives on the main
thread, so receivers there get a queued call. Updates carry ``game_id`` so consumers
can drop stale results from a previous game.

Stage graph per opponent::

    GAME (sync, in start())
     └─ IDENTITY  search_characters + matching.pick_candidate
         ├─ RATING      character-teams + seasons + tier-thresholds
         ├─ SMURF       team-histories + team-history-summaries -> analyze.smurf
         ├─ H2H         local player log (no network)
         ├─ TENDENCIES  character-matches
         └─ INTEL       only if analyze.intel.should_query_pro_sources (or ensure())
    TEAM (2v2+, after every IDENTITY)
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject, Signal

from smurfsniper.analyze import h2h as h2h_mod
from smurfsniper.analyze import history, intel, matches
from smurfsniper.analyze.smurf import SmurfInputs, assess
from smurfsniper.analyze.team import team_summary, windowed_records
from smurfsniper.api.errors import ApiError
from smurfsniper.api.sc2pulse.ids import LinkType, Queue, TeamType, solo_legacy_uid
from smurfsniper.api.sc2pulse.models import LadderTeam, ProPlayerEntry, SocialLink
from smurfsniper.core import matching
from smurfsniper.core.profile import (
    GameSeed,
    Identity,
    IntelInfo,
    LookupUpdate,
    OpponentProfile,
    RatingInfo,
    SmurfInfo,
    Stage,
    TendenciesInfo,
)
from smurfsniper.logger import logger

if TYPE_CHECKING:
    from smurfsniper.api.registry import Clients
    from smurfsniper.core.game_state import GameContext
    from smurfsniper.storage.player_log import PlayerLogStore

TEAM_SLOT = -1
SPARK_DAYS = 30


def _seed(player) -> GameSeed:
    return GameSeed(name=player.name, race=player.race_code)


def _pick_team(teams: list[LadderTeam], race: str | None) -> LadderTeam | None:
    """Team for the race played, else the most recently played one."""
    if not teams:
        return None
    if race:
        raced = [t for t in teams if any(race in m.race_games for m in t.members)]
        if raced:
            teams = raced
    epoch = datetime.min.replace(tzinfo=UTC)
    return max(teams, key=lambda t: (t.last_played or epoch, t.rating or 0))


class LookupPipeline(QObject):
    update = Signal(object)  # LookupUpdate

    def __init__(
        self,
        clients: Clients,
        db: PlayerLogStore | None,
        *,
        my_mmr: Callable[[], int | None],
        my_region: Callable[[], str | None],
        mmr_window: Callable[[], int],
        max_workers: int = 4,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        super().__init__()
        self.clients = clients
        self.db = db
        self._my_mmr = my_mmr
        self._my_region = my_region
        self._mmr_window = mmr_window
        self._now = now
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="lookup")
        self._lock = threading.RLock()
        self._ctx: GameContext | None = None
        self._game_id: int | None = None
        self._futures: list[Future] = []
        self._stages: dict[tuple[int, int, Stage], str] = {}  # running / done
        self._wanted: set[tuple[int, int, Stage]] = set()
        self._results: dict[int, dict[int, OpponentProfile]] = {}
        self._team: dict[int, Any] = {}

    # ---------------------------------------------------------------- public
    @property
    def game_id(self) -> int | None:
        return self._game_id

    def start(self, ctx: GameContext) -> None:
        """Begin lookups for a new game. Emits GAME updates synchronously."""
        self.cancel()
        with self._lock:
            self._ctx = ctx
            self._game_id = ctx.game_id
            self._results = {
                ctx.game_id: {
                    i: OpponentProfile(seed=_seed(p)) for i, p in enumerate(ctx.opponents)
                }
            }
            self._team = {}
        for slot, p in enumerate(ctx.opponents):
            self._emit(LookupUpdate(ctx.game_id, slot, Stage.GAME, _seed(p)))
        if ctx.vs_ai:
            logger.info("vs AI game: skipping opponent lookups")
            return
        for slot in range(len(ctx.opponents)):
            self._submit(ctx.game_id, slot, Stage.IDENTITY, self._identity, slot)

    def cancel(self) -> None:
        """Drop the current game's pending work (best effort)."""
        with self._lock:
            for f in self._futures:
                f.cancel()
            self._futures = []
            self._stages = {}
            self._wanted = set()
            self._ctx = None
            self._game_id = None

    def ensure(self, game_id: int, slot: int, stage: Stage) -> None:
        """Run ``stage`` for ``slot`` if it has not run; waits for IDENTITY if needed."""
        with self._lock:
            if game_id != self._game_id or self._ctx is None:
                return
            key = (game_id, slot, stage)
            if key in self._stages:
                return
            prof = self._results.get(game_id, {}).get(slot)
            identity = prof.identity if prof else None
            if identity is None:
                if (game_id, slot, Stage.IDENTITY) in self._stages and self._stages[
                    (game_id, slot, Stage.IDENTITY)
                ] == "running":
                    self._wanted.add(key)
                return
        self._submit_stage(game_id, slot, stage, identity)

    def results(self, game_id: int) -> dict[int, OpponentProfile]:
        """Thread-safe snapshot of every profile for ``game_id``."""
        with self._lock:
            return {s: p.copy() for s, p in self._results.get(game_id, {}).items()}

    def team_result(self, game_id: int) -> Any:
        with self._lock:
            return self._team.get(game_id)

    def context(self) -> GameContext | None:
        return self._ctx

    def shutdown(self) -> None:
        self.cancel()
        self._executor.shutdown(wait=False, cancel_futures=True)

    # -------------------------------------------------------------- plumbing
    def _is_current(self, game_id: int) -> bool:
        return game_id == self._game_id

    def _emit(self, u: LookupUpdate) -> None:
        with self._lock:
            if u.slot == TEAM_SLOT:
                if u.data is not None:
                    self._team[u.game_id] = u.data
            else:
                prof = self._results.get(u.game_id, {}).get(u.slot)
                if prof is not None:
                    prof.apply(u)
        self.update.emit(u)

    def _submit(self, game_id: int, slot: int, stage: Stage, fn: Callable, *args: Any) -> None:
        key = (game_id, slot, stage)
        with self._lock:
            if not self._is_current(game_id) or key in self._stages:
                return
            self._stages[key] = "running"
            try:
                fut = self._executor.submit(self._run, game_id, slot, stage, fn, args)
            except RuntimeError:  # executor shut down
                return
            self._futures.append(fut)

    def _run(self, game_id: int, slot: int, stage: Stage, fn: Callable, args: tuple) -> None:
        if not self._is_current(game_id):
            return
        data, err = None, None
        try:
            data = fn(*args)
        except ApiError as e:
            err = str(e)
            logger.warning(f"lookup {stage} slot {slot} failed: {e}")
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            logger.opt(exception=True).warning(f"lookup {stage} slot {slot} crashed: {err}")
        with self._lock:
            if (game_id, slot, stage) in self._stages:
                self._stages[(game_id, slot, stage)] = "done"
        self._emit(LookupUpdate(game_id, slot, stage, data, err))
        if self._is_current(game_id):
            self._after(game_id, slot, stage, data, err)

    def _after(self, game_id: int, slot: int, stage: Stage, data: Any, err: str | None) -> None:
        if stage is not Stage.IDENTITY:
            return
        if isinstance(data, Identity) and err is None:
            for nxt in (Stage.RATING, Stage.SMURF, Stage.H2H, Stage.TENDENCIES):
                self._submit_stage(game_id, slot, nxt, data)
            with self._lock:
                wanted = {k for k in self._wanted if k[0] == game_id and k[1] == slot}
                self._wanted -= wanted
            if intel.should_query_pro_sources(data) or (game_id, slot, Stage.INTEL) in wanted:
                self._submit_stage(game_id, slot, Stage.INTEL, data)
        self._maybe_team(game_id)

    def _submit_stage(self, game_id: int, slot: int, stage: Stage, identity: Identity) -> None:
        fns = {
            Stage.RATING: self._rating,
            Stage.SMURF: self._smurf,
            Stage.H2H: self._h2h,
            Stage.TENDENCIES: self._tendencies,
            Stage.INTEL: self._intel,
        }
        fn = fns.get(stage)
        if fn is not None:
            self._submit(game_id, slot, stage, fn, slot, identity)

    def _maybe_team(self, game_id: int) -> None:
        ctx = self._ctx
        if ctx is None or ctx.mode in ("1v1", "other") or len(ctx.opponents) < 2:
            return
        with self._lock:
            done = all(
                self._stages.get((game_id, s, Stage.IDENTITY)) == "done"
                for s in range(len(ctx.opponents))
            )
        if done:
            self._submit(game_id, TEAM_SLOT, Stage.TEAM, self._team_stage)

    def _region(self, identity: Identity | None = None) -> str:
        if identity is not None:
            return identity.character.region
        return self._my_region() or "EU"

    def _season(self, region: str) -> int:
        return self.clients.sc2pulse.current_season(region).battlenet_id

    def _profile(self, slot: int) -> OpponentProfile | None:
        with self._lock:
            return self._results.get(self._game_id or -1, {}).get(slot)

    # ---------------------------------------------------------------- stages
    def _identity(self, slot: int) -> Identity | None:
        ctx = self._ctx
        if ctx is None:
            return None
        seed = _seed(ctx.opponents[slot])
        cands = self.clients.sc2pulse.search_characters(seed.name)
        picked = matching.pick_candidate(
            cands,
            seed,
            region=self._my_region(),
            my_mmr=self._my_mmr(),
            window=self._mmr_window(),
        )
        if picked is None:
            logger.info(f"No SC2Pulse match for {seed.name}")
            return None
        cand, confidence = picked
        m = cand.members
        logger.info(
            f"Chose {m.character.name} ({m.character.region}, MMR {cand.rating}) for "
            f"{seed.name}, confidence {confidence:.2f}"
        )
        return Identity(
            character=m.character,
            clan=m.clan,
            pro=m.pro_player,
            candidate=cand,
            confidence=confidence,
            exact_matches=len(matching.exact_name_matches(cands, seed.name)),
        )

    def _rating(self, slot: int, identity: Identity) -> RatingInfo:
        ctx = self._ctx
        mode = ctx.mode if ctx else "1v1"
        queue = matching.queue_for(mode)
        region = identity.character.region
        season = self._season(region)
        seed = ctx.opponents[slot] if ctx else None
        teams = self.clients.sc2pulse.character_teams(
            [identity.character.id], queues=[queue], seasons=[season]
        )
        team = _pick_team(teams, seed.race_code if seed else None)
        cand = identity.candidate
        mmr = team.rating if team and team.rating else cand.rating
        league = team.league_id if team else None
        tier = team.tier_type if team else None
        to_next = None
        if mmr is not None:
            try:
                tt = self.clients.sc2pulse.tier_thresholds(
                    queue, TeamType.ARRANGED, season, regions=[region]
                )
                band = tt.band(region, mmr)
            except ApiError as e:
                logger.debug(f"tier thresholds unavailable: {e}")
                band = None
            if band is not None:
                b_league, b_tier, _lo, hi = band
                if league is None:
                    league = b_league
                if tier is None:
                    tier = b_tier
                to_next = max(hi - mmr, 0)
        return RatingInfo(
            mmr=mmr,
            league=league,
            tier=tier,
            region_percentile=team.region_percentile if team else None,
            season_wins=team.wins if team else None,
            season_losses=team.losses if team else None,
            peak_mmr=cand.rating_max,
            peak_league=cand.league_max,
            mmr_to_next_tier=to_next,
            team=team,
        )

    def _smurf(self, slot: int, identity: Identity) -> SmurfInfo:
        ch = identity.character
        ctx = self._ctx
        race_now = ctx.opponents[slot].race_code if ctx else None
        races = [r for r, n in identity.candidate.members.race_games.items() if n > 0]
        if race_now and race_now not in races and race_now != "RANDOM":
            races.append(race_now)
        if not races:
            races = [race_now] if race_now else []
        uids = [
            solo_legacy_uid(Queue.LOTV_1V1, ch.region, ch.realm, ch.battlenet_id, r) for r in races
        ]
        if not uids:
            uids = [solo_legacy_uid(Queue.LOTV_1V1, ch.region, ch.realm, ch.battlenet_id, None)]
        pulse = self.clients.sc2pulse
        series = pulse.team_histories(uids)
        summaries = pulse.team_history_summaries(uids)
        now = self._now()
        points = history.rating_points(series)
        outs = history.outcomes(points)
        peak = max((s.rating_max for s in summaries if s.rating_max), default=None)
        peak_league = max(
            (s.league_type_max for s in summaries if s.league_type_max is not None), default=None
        )
        cand = identity.candidate
        current = cand.rating or (points[-1].rating if points else None)
        assessment = assess(
            SmurfInputs(
                outcomes=outs,
                points=points,
                now=now,
                current_mmr=current,
                peak_mmr=max(filter(None, (peak, cand.rating_max)), default=None),
                peak_league=peak_league if peak_league is not None else cand.league_max,
                race_games=dict(cand.members.race_games),
                current_race=race_now,
            )
        )
        season = None
        try:
            season = self._season(ch.region)
        except ApiError:
            season = None
        recent = [p.rating for p in points if (now - p.ts).days <= SPARK_DAYS]
        if len(recent) < 3:
            recent = [p.rating for p in points[-20:]]
        return SmurfInfo(
            assessment=assessment,
            trend=history.trend(points),
            sparkline=history.sparkline(recent),
            records=windowed_records(outs, points, now=now, season=season),
        )

    def _h2h(self, slot: int, identity: Identity) -> Any:
        if self.db is None:
            return None
        rows = self.db.rows_for(identity.character.region, identity.character.battlenet_id)
        return h2h_mod.head_to_head(rows)

    def _tendencies(self, slot: int, identity: Identity) -> TendenciesInfo | None:
        ctx = self._ctx
        mode = ctx.mode if ctx else "1v1"
        page = self.clients.sc2pulse.character_matches(
            [identity.character.id], types=[matching.match_type_for(mode)], limit=25
        )
        recent = matches.recent_results(page.result, identity.character.id)
        if not recent:
            return None
        return TendenciesInfo(
            recent=recent,
            maps=matches.map_records(recent),
            avg_duration_s=matches.avg_duration(recent),
        )

    def _intel(self, slot: int, identity: Identity) -> IntelInfo | None:
        pulse = self.clients.sc2pulse
        pro: ProPlayerEntry | None = identity.pro
        if pro is not None:
            try:
                pro = pulse.pro_player(pro.pro_player.id) or pro
            except ApiError as e:
                logger.debug(f"pro details unavailable: {e}")
        links: dict[str, SocialLink] = {}
        for link in pro.links if pro else []:
            links.setdefault(link.type, link)
        try:
            for group in pulse.character_links([identity.character.id]):
                for link in group.links:
                    links.setdefault(link.type, link)
        except ApiError as e:
            logger.debug(f"character links unavailable: {e}")

        ali = None
        if self.clients.aligulac is not None:
            try:
                aid = intel.aligulac_id(identity, pro)
                if aid is not None:
                    ali = self.clients.aligulac.player(aid)
                elif pro is not None:
                    tag = pro.pro_player.nickname or identity.character.base_name
                    found = self.clients.aligulac.players_by_tag(tag)
                    ali = found[0] if len(found) == 1 else None
            except ApiError as e:
                logger.debug(f"aligulac unavailable: {e}")

        lp = None
        if self.clients.liquipedia is not None and intel.should_query_pro_sources(identity):
            title = (pro.pro_player.nickname if pro else None) or identity.character.base_name
            try:
                lp = self.clients.liquipedia.page_summaries([title]).get(title)
            except ApiError as e:
                logger.debug(f"liquipedia unavailable: {e}")

        ordered = [links[t] for t in sorted(links) if t not in (LinkType.BATTLE_NET,)]
        if pro is None and ali is None and lp is None and not ordered:
            return None
        return IntelInfo(pro=pro, aligulac=ali, liquipedia=lp, links=ordered)

    def _team_stage(self) -> Any:
        ctx = self._ctx
        if ctx is None:
            return None
        gid = ctx.game_id
        with self._lock:
            idents = [p.identity for p in self._results.get(gid, {}).values() if p.identity]
        if len(idents) < 2:
            return None
        region = idents[0].character.region
        queue = matching.queue_for(ctx.mode)
        season = self._season(region)
        ids = [i.character.id for i in idents]
        teams = self.clients.sc2pulse.character_teams(ids, queues=[queue], seasons=[season])
        want = set(ids)
        team = next((t for t in teams if want <= t.character_ids), None)
        if team is None or not team.legacy_uid:
            return None
        series = self.clients.sc2pulse.team_histories([team.legacy_uid])
        return team_summary(team, series, now=self._now())
