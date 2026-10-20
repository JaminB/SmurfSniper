"""Who am I? Auto-detect the player's account, search for candidates, refresh MMR.

Threading: ``identify_me`` is called on the SC2 poller thread, searches and MMR
refreshes run on the executor. Anything that mutates the shared ``Config`` is handed
to the main thread through private queued signals.
"""

from __future__ import annotations

import contextlib
import threading
from collections import deque
from collections.abc import Callable, Sequence
from concurrent.futures import Executor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal, Slot

from smurfsniper.api.sc2client.models import GamePlayer
from smurfsniper.api.sc2pulse.ids import League, Queue, toon_handle
from smurfsniper.api.sc2pulse.models import Character, LadderTeam
from smurfsniper.core import matching
from smurfsniper.core.lookup import pick_team
from smurfsniper.core.profile import ago
from smurfsniper.logger import logger
from smurfsniper.models.config import QUEUE_1V1, Config

if TYPE_CHECKING:
    from smurfsniper.api.registry import Clients
    from smurfsniper.core.game_state import GameContext, GameResult

RETRY_DELAYS = (20.0, 90.0, 300.0)
AUTO_CHOOSE_DAYS = 7
MAX_DETAIL_LOOKUPS = 6
_REGIONS = ("US", "EU", "KR", "CN")


def _league_text(league: int | None, tier: int | None) -> str | None:
    if league is None:
        return None
    try:
        name = League(league).label
    except ValueError:
        return None
    if tier is not None and league != League.GRANDMASTER:
        return f"{name} {tier + 1}"
    return name


@dataclass(frozen=True)
class AccountCandidate:
    character: Character
    region: str
    mmr_1v1: int | None
    league_1v1: int | None
    games_this_season: int | None
    last_played: datetime | None
    clan_tag: str | None
    tier_1v1: int | None = None
    top_race: str | None = None

    def label(self, now: datetime | None = None) -> str:
        """``Name#123 · EU · Diamond 2 · 4,210 MMR · last played 2h ago``."""
        parts: list[str | None] = [
            self.character.name,
            self.region,
            _league_text(self.league_1v1, self.tier_1v1),
            f"{self.mmr_1v1:,} MMR" if self.mmr_1v1 else None,
            f"last played {ago(self.last_played, now or datetime.now(UTC))} ago"
            if self.last_played
            else None,
        ]
        return " · ".join(p for p in parts if p)


def _base(name: str) -> str:
    return name.split("#")[0].strip().casefold()


class AccountService(QObject):
    account_changed = Signal(object)  # AccountConfig
    candidates_ready = Signal(str, list)  # (query, list[AccountCandidate])
    mmr_refreshed = Signal(int, int)  # (queue, rating)
    needs_picker = Signal(list)  # list[str] names seen (ambiguous auto-detect)

    _detected = Signal(str)
    _resolve = Signal(str)
    _auto_choose = Signal(object)
    _mmr_found = Signal(int, int)

    def __init__(
        self,
        config: Config,
        clients: Clients,
        executor: Executor,
        save: Callable[[], None],
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        super().__init__()
        self.config = config
        self.clients = clients
        self._executor = executor
        self._save = save
        self._now = now
        self._lock = threading.Lock()
        self._history: deque[frozenset[str]] = deque(maxlen=3)
        self._game_open = False
        self._announced: frozenset[str] | None = None
        self._cache: dict[str, list[AccountCandidate]] = {}
        self._timers: list[threading.Timer] = []
        self._generation = 0
        self._stopped = False
        self._resolve_tried = False
        self._detected.connect(self._on_detected)
        self._resolve.connect(self._on_resolve)
        self._auto_choose.connect(self.choose)
        self._mmr_found.connect(self._on_mmr_found)

    # -------------------------------------------------------------- identify
    def identify_me(self, players: Sequence[GamePlayer]) -> GamePlayer | None:
        humans = [p for p in players if p.is_human]
        acct = self.config.account
        if acct.name:
            want = _base(acct.name)
            me = next((p for p in humans if _base(p.name) == want), None)
            if me is not None and acct.character_id is None and acct.auto_detect:
                with self._lock:
                    first, self._resolve_tried = not self._resolve_tried, True
                if first:  # known name, unknown character (e.g. migrated v1 config)
                    self._resolve.emit(acct.name)
            return me
        if len(humans) == 1:
            me = humans[0]
            if acct.auto_detect:
                self._detected.emit(me.name)
            return me
        if not acct.auto_detect:
            return None
        mates = {_base(m) for m in acct.teammates}
        current = frozenset(_base(p.name) for p in humans)
        with self._lock:
            games = list(self._history)
        if self._game_open and games and games[-1] == current:
            games.pop()  # this is a re-detect of the game already observed
        recent = [*games[-2:], current]
        counts: dict[str, int] = {}
        for names in recent:
            for n in names:
                counts[n] = counts.get(n, 0) + 1
        mine = sorted(n for n, c in counts.items() if c >= 2 and n in current and n not in mates)
        if len(mine) == 1:
            me = next(p for p in humans if _base(p.name) == mine[0])
            self._detected.emit(me.name)
            return me
        if len(mine) > 1:
            self._announce(mine)
        return None

    def _announce(self, names: list[str]) -> None:
        key = frozenset(names)
        with self._lock:
            if self._announced == key:
                return
            self._announced = key
        self.needs_picker.emit(names)

    def observe_game(self, ctx: GameContext) -> None:
        """Record the human names of a started game (main thread)."""
        names = frozenset(_base(p.name) for p in ctx.players if p.is_human)
        with self._lock:
            if self._game_open and self._history and self._history[-1] == names:
                return
            self._history.append(names)
            self._game_open = True

    @Slot(str)
    def _on_detected(self, name: str) -> None:
        acct = self.config.account
        if acct.name or not acct.auto_detect:
            return
        acct.name = name.split("#")[0].strip()
        logger.info(f"Detected my in-game name: {acct.name}")
        self._save()
        self.account_changed.emit(acct)
        if acct.character_id is None:
            self.search(acct.name, auto=True)

    @Slot(str)
    def _on_resolve(self, name: str) -> None:
        acct = self.config.account
        if acct.character_id is None and acct.auto_detect:
            logger.info(f"Looking up the SC2Pulse account for {name}")
            self.search(name, auto=True)

    # ---------------------------------------------------------------- search
    def search(self, name: str, *, auto: bool = False) -> None:
        """Look ``name`` up on SC2Pulse; results arrive on ``candidates_ready``."""
        query = name.split("#")[0].strip()
        if not query:
            self.candidates_ready.emit(name, [])
            return
        cached = self._cache.get(query.casefold())
        if cached is not None and not auto:
            self.candidates_ready.emit(query, list(cached))
            return
        try:
            self._executor.submit(self._search_job, query, auto)
        except RuntimeError:  # executor shut down
            return

    def _search_job(self, query: str, auto: bool) -> None:
        try:
            cands = self._candidates(query)
        except Exception as e:
            logger.warning(f"Account search for '{query}' failed: {e}")
            self.candidates_ready.emit(query, [])
            return
        self._cache[query.casefold()] = cands
        self.candidates_ready.emit(query, list(cands))
        if not auto:
            return
        cutoff = self._now() - timedelta(days=AUTO_CHOOSE_DAYS)
        recent = [c for c in cands if c.last_played and c.last_played >= cutoff]
        # Candidates past MAX_DETAIL_LOOKUPS have no last_played, so the recency
        # filter is only trusted when every candidate was looked up in detail.
        pool = recent if len(cands) <= MAX_DETAIL_LOOKUPS else cands
        if len(pool) == 1 and pool[0] in recent:
            self._auto_choose.emit(pool[0])
        elif cands:
            self.needs_picker.emit([query])

    def _candidates(self, query: str) -> list[AccountCandidate]:
        pulse = self.clients.sc2pulse
        found = matching.exact_name_matches(pulse.search_characters(query), query)
        seasons: dict[str, int] = {}
        out: list[AccountCandidate] = []
        for i, c in enumerate(found):
            ch = c.character
            team: LadderTeam | None = None
            if i < MAX_DETAIL_LOOKUPS:
                try:
                    if ch.region not in seasons:
                        seasons[ch.region] = pulse.current_season(ch.region).battlenet_id
                    teams = pulse.character_teams(
                        [ch.id], queues=[Queue.LOTV_1V1], seasons=[seasons[ch.region]]
                    )
                    team = pick_team(teams, None)
                except Exception as e:
                    logger.debug(f"candidate detail lookup failed: {e}")
            races = c.members.race_games
            out.append(
                AccountCandidate(
                    character=ch,
                    region=ch.region,
                    mmr_1v1=(team.rating if team and team.rating else c.rating),
                    league_1v1=team.league_id if team else c.league_max,
                    tier_1v1=team.tier_type if team else None,
                    games_this_season=c.current_stats.games_played,
                    last_played=team.last_played if team else None,
                    clan_tag=c.members.clan.tag if c.members.clan else None,
                    top_race=max(races, key=lambda r: races[r]) if races else None,
                )
            )
        epoch = datetime.min.replace(tzinfo=UTC)
        out.sort(key=lambda a: (a.last_played or epoch, a.games_this_season or 0), reverse=True)
        return out

    # ---------------------------------------------------------------- choose
    @Slot(object)
    def choose(self, cand: AccountCandidate) -> None:
        """Persist ``cand`` as my account (main thread)."""
        acct = self.config.account
        ch = cand.character
        acct.character_id = ch.id
        acct.name = ch.base_name
        acct.region = ch.region if ch.region in _REGIONS else None  # type: ignore[assignment]
        try:
            acct.toon_handle = toon_handle(ch.region, ch.realm, ch.battlenet_id)
        except KeyError:
            acct.toon_handle = None
        if cand.mmr_1v1:
            acct.mmr_by_queue[QUEUE_1V1] = cand.mmr_1v1
            acct.mmr_updated_at = self._now()
        logger.info(f"Account set to {ch.name} ({ch.region})")
        self._save()
        self.account_changed.emit(acct)

    # ------------------------------------------------------------------- mmr
    def refresh_mmr_after_game(self, result: GameResult) -> None:
        """Poll SC2Pulse at 20 s, 90 s and 300 s after a game until the rating moves."""
        ctx = result.context
        self._game_open = False
        acct = self.config.account
        if ctx.vs_ai or ctx.mode == "other" or acct.character_id is None or self._stopped:
            return
        queue = int(matching.queue_for(ctx.mode))
        race = ctx.me.race_code if ctx.me else None
        self._cancel_timers()
        gen = self._generation
        for delay in RETRY_DELAYS:
            t = threading.Timer(
                delay, self._submit_attempt, args=(gen, queue, race, ctx.started_at)
            )
            t.daemon = True
            self._timers.append(t)
            t.start()

    def refresh_mmr_now(self, queue: int = QUEUE_1V1) -> None:
        """Settings > Refresh now: one immediate forced attempt that always applies."""
        if self.config.account.character_id is None:
            return
        with contextlib.suppress(RuntimeError):
            self._executor.submit(self._attempt_job, self._generation, queue, None, None, True)

    def _submit_attempt(
        self, gen: int, queue: int, race: str | None, since: datetime | None
    ) -> None:
        if self._stopped or gen != self._generation:
            return
        with contextlib.suppress(RuntimeError):
            self._executor.submit(self._attempt_job, gen, queue, race, since, False)

    def _attempt_job(
        self, gen: int, queue: int, race: str | None, since: datetime | None, always: bool
    ) -> None:
        if gen != self._generation or self._stopped:
            return
        acct = self.config.account
        cid, region = acct.character_id, acct.region or "EU"
        if cid is None:
            return
        try:
            pulse = self.clients.sc2pulse
            try:
                pulse.characters(character_ids=[cid], force_refresh=True)
            except Exception as e:
                logger.debug(f"character refresh failed: {e}")
            season = pulse.current_season(region).battlenet_id
            teams = pulse.character_teams(
                [cid], queues=[Queue(queue)], seasons=[season], force_refresh=True
            )
            team = pick_team(teams, race)
        except Exception as e:
            logger.debug(f"MMR refresh failed: {e}")
            return
        if team is None or team.rating is None:
            return
        changed = team.rating != acct.mmr_by_queue.get(queue) or bool(
            since and team.last_played and team.last_played > since
        )
        if changed or always:
            with self._lock:
                if gen != self._generation:
                    return
                self._generation += 1  # later attempts for this game become no-ops
            self._mmr_found.emit(queue, team.rating)

    @Slot(int, int)
    def _on_mmr_found(self, queue: int, rating: int) -> None:
        acct = self.config.account
        acct.mmr_by_queue[queue] = rating
        acct.mmr_updated_at = self._now()
        self._cancel_timers()
        logger.info(f"MMR updated: queue {queue} = {rating}")
        self._save()
        self.mmr_refreshed.emit(queue, rating)

    def _cancel_timers(self) -> None:
        timers, self._timers = self._timers, []
        for t in timers:
            t.cancel()

    def stop(self) -> None:
        self._stopped = True
        self._cancel_timers()
