"""Adapter: ``LookupUpdate`` stream -> the legacy ``Overlay`` text blocks.

Kept until the HUD redesign replaces it. Lines are only added when their data
exists, so nothing like "unknown" or "(no data)" is ever shown.
"""

from __future__ import annotations

import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from smurfsniper.analyze.smurf import SmurfAssessment
from smurfsniper.api.sc2pulse.ids import League
from smurfsniper.core.game_state import GameContext
from smurfsniper.core.lookup import TEAM_SLOT
from smurfsniper.core.profile import GameSeed, LookupUpdate, OpponentProfile, Stage, ago
from smurfsniper.logger import logger
from smurfsniper.models.config import Config, Placement
from smurfsniper.ui.overlay_manager import close_all_overlays
from smurfsniper.ui.overlays import Overlay, styled

SMURF_LABEL = {
    "suspicious": "Suspiciously strong",
    "possible": "Possible smurf",
    "likely": "Likely smurf",
}
RACE_LABEL = {"TERRAN": "Terran", "PROTOSS": "Protoss", "ZERG": "Zerg", "RANDOM": "Random"}


def league_label(league: int | None, tier: int | None = None) -> str | None:
    if league is None:
        return None
    try:
        name = League(league).label
    except ValueError:
        return None
    if tier is not None and league != League.GRANDMASTER:
        return f"{name} {tier + 1}"
    return name


def top_percent(region_percentile: float | None) -> str | None:
    if region_percentile is None:
        return None
    top = max(0.0, 100.0 - region_percentile)
    return f"top {top:.1f}%" if top < 1 else f"top {top:.0f}%"


def smurf_line(a: SmurfAssessment) -> str | None:
    if a.level == "none":
        return None
    line = f"⚠ {SMURF_LABEL[a.level]} ({a.score}/100)"
    if a.top_reason:
        line += f" - {a.top_reason.text}"
    return line


def _join(parts, sep: str = "  ") -> str:
    return sep.join(p for p in parts if p)


def player_lines(prof: OpponentProfile, *, now: datetime) -> list[str]:
    """Main HUD lines for one opponent. Every line is optional except the name."""
    ident, rating, smurf = prof.identity, prof.rating, prof.smurf
    name = ident.character.base_name if ident else prof.seed.name
    peak_league = None
    if rating and rating.peak_league is not None:
        peak_league = rating.peak_league
    elif ident:
        peak_league = ident.candidate.league_max
    head = _join(
        [
            name,
            f"[{ident.clan.tag}]" if ident and ident.clan else None,
            ident.character.region if ident else None,
            f"| max {league_label(peak_league)}" if league_label(peak_league) else None,
        ]
    )
    lines = [head]
    if ident and ident.pro and ident.pro.pro_player.nickname:
        team = ident.pro.pro_team.short_name if ident.pro.pro_team else None
        lines.append(
            _join([f"👑 {ident.pro.pro_player.nickname}", f"[{team}]" if team else None], " ")
        )

    mmr = rating.mmr if rating else (ident.candidate.rating if ident else None)
    rating_line = _join(
        [
            f"MMR {mmr:,}" if mmr else None,
            smurf.trend.symbol if smurf and smurf.trend else None,
            smurf.sparkline if smurf else None,
            league_label(rating.league, rating.tier) if rating else None,
            top_percent(rating.region_percentile) if rating else None,
        ]
    )
    if rating_line:
        lines.append(rating_line)

    race = prof.seed.race
    main = ident.candidate.members.main_race if ident else None
    if race:
        note = (
            f" (main {RACE_LABEL.get(main, main)})"
            if main and main != race and race != "RANDOM"
            else ""
        )
        lines.append(f"Race: {RACE_LABEL.get(race, race)}{note}")

    if smurf:
        sl = smurf_line(smurf.assessment)
        if sl:
            lines.append(sl)
        if smurf.records:
            lines.append(" · ".join(f"{k} {r}" for k, r in smurf.records.items()))
    if (
        rating
        and rating.season_wins is not None
        and (rating.season_wins + (rating.season_losses or 0))
    ):
        lines.append(f"Season {rating.season_wins}-{rating.season_losses or 0}")
    if rating and rating.peak_mmr and mmr and rating.peak_mmr - mmr >= 300:
        lines.append(f"Peak {rating.peak_mmr:,} (-{rating.peak_mmr - mmr:,})")
    return lines


def compact_line(prof: OpponentProfile) -> str:
    """One line per opponent for 3v3/4v4."""
    ident, rating, smurf = prof.identity, prof.rating, prof.smurf
    name = ident.character.base_name if ident else prof.seed.name
    mmr = rating.mmr if rating else (ident.candidate.rating if ident else None)
    badge = None
    if smurf and smurf.assessment.level != "none":
        badge = f"⚠ {SMURF_LABEL[smurf.assessment.level]} {smurf.assessment.score}"
    return _join([name, RACE_LABEL.get(prof.seed.race or ""), f"{mmr:,}" if mmr else None, badge])


def h2h_lines(prof: OpponentProfile, *, now: datetime) -> list[str] | None:
    h = prof.h2h
    if h is None or not h.games:
        return None
    name = prof.identity.character.base_name if prof.identity else prof.seed.name
    region = prof.identity.character.region if prof.identity else None
    record = f"{h.wins}W – {h.losses}L" + (f" – {h.ties}T" if h.ties else "")
    times = "time" if h.games == 1 else "times"
    return [
        _join([name, f"({region})" if region else None], " "),
        f"Played {h.games} {times}",
        f"Your record: {record}",
        f"Last played {ago(h.last, now)} ago",
    ]


def intel_lines(prof: OpponentProfile) -> list[str] | None:
    lines: list[str] = []
    intel, tend = prof.intel, prof.tendencies
    if intel and intel.pro:
        pp = intel.pro.pro_player
        team = intel.pro.pro_team.short_name if intel.pro.pro_team else None
        lines.append(
            _join(
                [
                    f"👑 {pp.nickname}" if pp.nickname else None,
                    f"[{team}]" if team else None,
                    pp.country,
                    pp.name,
                    f"${pp.earnings:,}" if pp.earnings else None,
                ]
            )
        )
    if intel and intel.aligulac:
        al = intel.aligulac
        rank = al.current_rating.position if al.current_rating else None
        lines.append(_join(["Aligulac", al.tag, f"#{rank}" if rank else None, al.team]))
    if intel and intel.liquipedia and intel.liquipedia.extract:
        lines.extend(textwrap.wrap(intel.liquipedia.extract, 60)[:3])
    if intel and intel.links:
        lines.append("Links: " + " · ".join(link.type.title() for link in intel.links))
    if tend and tend.recent:
        lines.append("Form: " + " ".join("W" if r.won else "L" for r in tend.recent[:10]))
        if tend.maps:
            top = list(tend.maps.items())[:3]
            lines.append("Maps: " + " · ".join(f"{m} {r}" for m, r in top))
        if tend.avg_duration_s:
            mins, secs = divmod(tend.avg_duration_s, 60)
            lines.append(f"Avg game {mins}:{secs:02d}")
    if not lines:
        return None
    name = prof.identity.character.base_name if prof.identity else prof.seed.name
    return [f"🔎 {name}", *lines]


@dataclass(frozen=True)
class SurfacePrefs:
    """Where and how long one legacy overlay is shown (derived from the v2 config)."""

    visible: bool
    placement: Placement
    seconds_visible: int
    orientation: str = "horizontal"
    delay: float = 0.0


class LegacyRenderer(QObject):
    """Accumulates ``OpponentProfile``s and shows the legacy overlays once ready."""

    rendered = Signal(str, int)  # (overlay kind, game_id)
    hidden_changed = Signal(bool)

    def __init__(
        self,
        config: Config,
        *,
        chime: Callable[[str], None] | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        show: bool = True,
    ):
        super().__init__()
        self.config = config
        self._chime = chime
        self._now = now
        self._show = show
        self.game_id: int | None = None
        self.ctx: GameContext | None = None
        self.profiles: dict[int, OpponentProfile] = {}
        self.team = None
        self._team_done = False
        self._shown: set[str] = set()
        self._timers: list[QTimer] = []
        self._windows: dict[str, Overlay] = {}
        self.hidden = False
        self._intel_requested = False
        self.dropped = 0

    # ----------------------------------------------------------------- slots
    @Slot(object)
    def on_game_started(self, ctx: GameContext) -> None:
        self.reset()
        self.game_id = ctx.game_id
        self.ctx = ctx
        self.profiles = {
            i: OpponentProfile(seed=GameSeed(p.name, p.race_code))
            for i, p in enumerate(ctx.opponents)
        }

    @Slot(object)
    def on_update(self, u: LookupUpdate) -> None:
        if u.game_id != self.game_id:
            self.dropped += 1
            return
        if u.slot == TEAM_SLOT:
            self._team_done = True
            self.team = u.data
            self._maybe_team()
            return
        prof = self.profiles.get(u.slot)
        if prof is None:
            return
        prof.apply(u)
        if u.stage is Stage.H2H and u.data is not None:
            self._show_h2h(u.slot, prof)
        self._maybe_main()
        if self._intel_requested and u.stage in (Stage.INTEL, Stage.IDENTITY, Stage.TENDENCIES):
            self._maybe_intel()

    def request_intel(self) -> None:
        """Intel hotkey: show the intel overlay once INTEL finished for every resolved slot."""
        if not self.profiles:
            logger.info("Intel: no current opponent")
            return
        self._shown.discard("intel")
        self._intel_requested = True
        self._maybe_intel()

    def reset(self) -> None:
        for t in self._timers:
            t.stop()
            t.deleteLater()
        self._timers = []
        close_all_overlays()
        self._windows = {}
        self.set_hidden(False)
        self.game_id = None
        self.ctx = None
        self.profiles = {}
        self.team = None
        self._team_done = False
        self._shown = set()
        self._intel_requested = False

    # -------------------------------------------------------------- internals
    @staticmethod
    def _slot_ready(prof: OpponentProfile) -> bool:
        if not prof.done(Stage.IDENTITY):
            return False
        if prof.identity is None:
            return True
        return prof.done(Stage.RATING) and prof.done(Stage.SMURF)

    def _prefs(self, surface: str, slot: int = 0) -> SurfacePrefs:
        """``surface`` is ``card``, ``toasts`` or ``panels`` (see ``OverlayConfig``)."""
        ov = self.config.overlays
        if surface == "card":
            return SurfacePrefs(ov.card.enabled, ov.card.placement, ov.card.auto_hide_seconds)
        if surface == "toasts":
            p = ov.toasts.placement
            p = p.model_copy(update={"offset_y": p.offset_y + slot * 96})
            return SurfacePrefs(ov.toasts.enabled, p, round(ov.toasts.seconds))
        return SurfacePrefs(True, ov.panels.placement, 30)

    def toggle(self, kind: str) -> bool:
        """Close the ``kind`` overlay if it is open, else show it again from cached data."""
        ov = self._windows.get(kind)
        if ov is not None and ov.isVisible():
            ov.close()
            return False
        if kind == "main":
            self._shown.discard("main")
            self._maybe_main(chime=False)
        elif kind == "intel":
            self.request_intel()
        return True

    def is_open(self, kind: str) -> bool:
        ov = self._windows.get(kind)
        return ov is not None and ov.isVisible()

    def set_hidden(self, hidden: bool) -> None:
        changed = hidden != self.hidden
        self.hidden = hidden
        if hidden:
            close_all_overlays()
        if changed:
            self.hidden_changed.emit(hidden)

    def _display(self, kind: str, prefs: SurfacePrefs, rows: list[list[str]], style: str) -> None:
        self._shown.add(kind)
        if not prefs.visible or not rows or self.hidden:
            return
        self.rendered.emit(kind, self.game_id or 0)
        if not self._show:
            return
        game_id = self.game_id
        ov_cfg = self.config.overlays
        style = styled(style, opacity=ov_cfg.opacity, scale=ov_cfg.scale)

        def build() -> None:
            if self.game_id != game_id or self.hidden:
                return
            ov = Overlay(
                duration_seconds=prefs.seconds_visible,
                placement=prefs.placement,
                screen=ov_cfg.screen,
                scale=ov_cfg.scale,
            )
            for row in rows:
                ov.add_row(row, style=style, spacing=12)
            self._windows[kind] = ov
            ov.show()

        delay = int(max(0.0, prefs.delay) * 1000)
        if delay <= 0:
            build()
            return
        t = QTimer(self)
        t.setSingleShot(True)
        t.timeout.connect(build)
        t.start(delay)
        self._timers.append(t)

    def _layout(self, blocks: list[str], orientation: str) -> list[list[str]]:
        if orientation == "vertical":
            return [[b] for b in blocks]
        return [blocks]

    def _maybe_main(self, *, chime: bool = True) -> None:
        if "main" in self._shown or not self.profiles:
            return
        if not all(self._slot_ready(p) for p in self.profiles.values()):
            return
        if not any(p.identity for p in self.profiles.values()):
            self._shown.add("main")
            logger.info("No SC2Pulse records for this game's opponents")
            return
        now = self._now()
        n = len(self.profiles)
        ordered = [self.profiles[i] for i in sorted(self.profiles)]
        if n == 1:
            prefs = self._prefs("card")
            blocks = ["\n".join(player_lines(ordered[0], now=now))]
        elif n == 2:
            prefs = self._prefs("card")
            blocks = ["\n".join(player_lines(p, now=now)) for p in ordered]
        else:
            prefs = self._prefs("card")
            blocks = ["\n".join(compact_line(p) for p in ordered)]
            worst = max(
                (p for p in ordered if p.smurf),
                key=lambda p: p.smurf.assessment.score,
                default=None,
            )
            if (
                worst
                and worst.smurf.assessment.level != "none"
                and worst.smurf.assessment.top_reason
            ):
                name = worst.identity.character.base_name if worst.identity else worst.seed.name
                blocks[0] += f"\n{name}: {worst.smurf.assessment.top_reason.text}"
        self._display("main", prefs, self._layout(blocks, prefs.orientation), Overlay.PLAYER_STYLE)
        if self._chime and chime:
            likely = any(p.smurf and p.smurf.assessment.level == "likely" for p in ordered)
            self._chime("two" if likely or n == 1 else "one")

    def _maybe_team(self) -> None:
        info = self.team
        if "team" in self._shown or info is None or info.team is None:
            return
        team = info.team
        lines = [
            _join(
                [
                    "Team",
                    f"{team.rating:,} MMR" if team.rating else None,
                    league_label(team.league_id, team.tier_type),
                    info.sparkline,
                ]
            )
        ]
        if team.wins or team.losses:
            lines.append(f"Season {team.wins}-{team.losses}")
        if info.records:
            lines.append(" · ".join(f"{k} {r}" for k, r in info.records.items()))
        if info.members_races:
            lines.append(" / ".join(RACE_LABEL.get(r, r) for r in info.members_races))
        prefs = self._prefs("card")
        self._display("team", prefs, [["\n".join(lines)]], Overlay.PLAYER_STYLE)

    def _show_h2h(self, slot: int, prof: OpponentProfile) -> None:
        kind = f"h2h{slot}"
        lines = h2h_lines(prof, now=self._now())
        if kind in self._shown or not lines:
            return
        prefs = self._prefs("toasts", slot % 2)
        self._display(kind, prefs, self._layout(lines, prefs.orientation), Overlay.PLAYER_STYLE)

    def _maybe_intel(self) -> None:
        if "intel" in self._shown:
            return
        for p in self.profiles.values():
            if not p.done(Stage.IDENTITY):
                return
            if p.identity is not None and not p.done(Stage.INTEL):
                return
        blocks = [
            "\n".join(lines)
            for p in self.profiles.values()
            if (lines := intel_lines(p)) is not None
        ]
        self._intel_requested = False
        if not blocks:
            self._shown.add("intel")
            logger.info("Intel: nothing found for this game's opponents")
            return
        close_all_overlays()
        self._display("intel", self._prefs("panels"), [blocks], Overlay.PLAYER_STYLE)
