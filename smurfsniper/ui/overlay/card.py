"""Opponent card: starts as one row (name + race) and grows as lookup stages land.

Row order inside an ``OpponentSection`` is fixed (identity, rating, smurf reasons,
trend + records, H2H, tendencies). A row whose data is missing is never created.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Literal

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QVBoxLayout, QWidget

from smurfsniper.analyze.h2h import H2HInfo
from smurfsniper.analyze.team import TeamInfo
from smurfsniper.core.profile import (
    GameSeed,
    Identity,
    LookupUpdate,
    RatingInfo,
    SmurfInfo,
    Stage,
    TendenciesInfo,
    ago,
)
from smurfsniper.models.config import Placement
from smurfsniper.ui import fmt
from smurfsniper.ui import tokens as t
from smurfsniper.ui.overlay.base import OverlayWindow, qcolor
from smurfsniper.ui.overlay.widgets import (
    Badge,
    Divider,
    Part,
    RaceDot,
    Row,
    Sparkline,
    reveal_row,
)
from smurfsniper.ui.tokens import TokenContext

Mode = Literal["full", "duo", "compact"]
SLOTS = ("identity", "rating", "reasons", "trend", "h2h", "tendencies")
MODE_SLOTS: dict[Mode, tuple[str, ...]] = {
    "full": SLOTS,
    "duo": ("identity", "rating", "reasons", "h2h"),
    "compact": ("identity",),
}
TREND_COLOR = {"▲": t.POSITIVE, "▼": t.NEGATIVE, "▶": t.TEXT_MUTED}


def dotted(parts: Sequence[Part | None]) -> list[Part]:
    """Interleave muted ``·`` separators between the non-empty parts."""
    kept = [p for p in parts if p is not None and p.text]
    out: list[Part] = []
    for i, p in enumerate(kept):
        if i:
            out.append(Part("·", "caption", t.TEXT_MUTED))
        out.append(p)
    return out


def race_accent(race: str | None) -> QColor:
    return qcolor(t.RACE_ACCENT.get(race, t.RACE_ACCENT[None]))


class OpponentSection(QWidget):
    """One opponent's rows. ``set_*`` only ever adds rows that have data."""

    rows_changed = Signal()

    def __init__(
        self,
        seed: GameSeed,
        tokens: TokenContext,
        *,
        mode: Mode = "full",
        my_race: str | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.seed = seed
        self.tokens = tokens
        self.mode: Mode = mode
        self.my_race = my_race
        self._now = now
        self.identity: Identity | None = None
        self.rating: RatingInfo | None = None
        self.smurf: SmurfInfo | None = None
        self.h2h: H2HInfo | None = None
        self.tendencies: TendenciesInfo | None = None
        self.rows: dict[str, Row] = {}
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(tokens.px(t.GAP["row"]))
        self._render(["identity"], animate=False)

    # ------------------------------------------------------------- stage api
    def set_seed(self, seed: GameSeed) -> None:
        self.seed = seed
        self._render(["identity"])

    def set_identity(self, v: Identity | None) -> None:
        self.identity = v
        self._render(["identity", "rating"])

    def set_rating(self, v: RatingInfo | None) -> None:
        self.rating = v
        self._render(["identity", "rating"])

    def set_smurf(self, v: SmurfInfo | None) -> None:
        self.smurf = v
        self._render(["identity", "reasons", "trend"])

    def set_h2h(self, v: H2HInfo | None) -> None:
        self.h2h = v
        self._render(["h2h"])

    def set_tendencies(self, v: TendenciesInfo | None) -> None:
        self.tendencies = v
        self._render(["tendencies"])

    def apply(self, u: LookupUpdate) -> None:
        setters = {
            Stage.GAME: lambda d: self.set_seed(d) if isinstance(d, GameSeed) else None,
            Stage.IDENTITY: self.set_identity,
            Stage.RATING: self.set_rating,
            Stage.SMURF: self.set_smurf,
            Stage.H2H: self.set_h2h,
            Stage.TENDENCIES: self.set_tendencies,
        }
        fn = setters.get(u.stage)
        if fn is not None and u.data is not None:
            fn(u.data)

    def set_tokens(self, tokens: TokenContext) -> None:
        self.tokens = tokens
        self.lay.setSpacing(tokens.px(t.GAP["row"]))
        for row in self.rows.values():
            self.lay.removeWidget(row)
            row.deleteLater()
        self.rows = {}
        self._render(list(SLOTS), animate=False)

    # ------------------------------------------------------------ properties
    @property
    def name(self) -> str:
        return self.identity.character.base_name if self.identity else self.seed.name

    @property
    def level(self) -> str:
        return self.smurf.assessment.level if self.smurf else "none"

    @property
    def score(self) -> int:
        return self.smurf.assessment.score if self.smurf else 0

    def visible_rows(self) -> list[Row]:
        return [self.rows[s] for s in SLOTS if s in self.rows]

    def texts(self) -> list[str]:
        return [txt for row in self.visible_rows() for txt in row.texts()]

    # ----------------------------------------------------------------- rows
    def _mmr(self) -> int | None:
        if self.rating and self.rating.mmr:
            return self.rating.mmr
        return None

    def _row_identity(self) -> Row | None:
        tk = self.tokens
        ident, rating = self.identity, self.rating
        league = fmt.league_label(rating.league, rating.tier, short=True) if rating else None
        badge = None
        if self.level != "none" and self.smurf:
            badge = Badge.smurf(self.level, self.score, tk, short=self.mode != "full")
        if self.mode == "compact":
            mmr = self._mmr()
            return Row.create(
                tk,
                [
                    Part(self.name, "body", t.TEXT_PRIMARY, 600, elide=True),
                    Part(f"{mmr:,}" if mmr else None, "caption", t.TEXT_SECONDARY),
                ],
                lead=RaceDot(self.seed.race, tk, glyph=False),
                trailing=[badge],
            )
        clan = f"[{ident.clan.tag}]" if ident and ident.clan and ident.clan.tag else None
        # 1v1 keeps row 1 short (the badge lives here) and shows the league in row 2.
        meta = fmt.join(
            [ident.character.region if ident else None, league if self.mode == "duo" else None]
        )
        pro = Badge.pro(tk) if ident and ident.pro else None
        race = RaceDot(self.seed.race, tk) if self.seed.race in t.RACE_GLYPH else None
        return Row.create(
            tk,
            [
                Part(self.name, "body", t.TEXT_PRIMARY, 600, elide=True),
                Part(clan, "caption", t.TEXT_MUTED),
                Part(meta, "micro", t.TEXT_SECONDARY),
            ],
            trailing=[pro, badge, race],
        )

    def _row_rating(self) -> Row | None:
        r = self.rating
        if r is None:
            return None
        mmr = self._mmr()
        peak = None
        if r.peak_mmr and mmr and r.peak_mmr - mmr >= 300:
            peak = f"peak {r.peak_mmr:,}"
        if self.mode == "duo":
            climb = None
            if self.smurf and self.smurf.trend:
                c = fmt.climb(self.smurf.trend.slope_per_day)
                climb = f"climb {c}" if c and self.smurf.trend.slope_per_day > 0 else None
            extra = [Part(climb, "caption", t.TEXT_SECONDARY)]
        else:
            extra = []
        return Row.create(
            self.tokens,
            dotted(
                [
                    Part(fmt.mmr(mmr), "body", t.TEXT_PRIMARY, 600),
                    Part(
                        fmt.league_label(r.league, r.tier) if self.mode == "full" else None,
                        "caption",
                        t.TEXT_SECONDARY,
                    ),
                    Part(fmt.top_percent(r.region_percentile), "caption", t.TEXT_SECONDARY),
                    Part(peak, "caption", t.TEXT_MUTED),
                    *extra,
                ]
            ),
        )

    def _row_reasons(self) -> Row | None:
        if not self.smurf or self.level == "none":
            return None
        n = 2 if self.mode == "full" else 1
        reasons = [r.text for r in self.smurf.assessment.reasons[:n]]
        fg = t.SMURF_BADGE[self.level][0]
        return Row.create(self.tokens, [Part(fmt.join(reasons), "caption", fg, elide=True)])

    def _row_trend(self) -> Row | None:
        s = self.smurf
        if s is None:
            return None
        tk = self.tokens
        symbol = s.trend.symbol if s.trend else None
        color = TREND_COLOR.get(symbol or "", t.TEXT_SECONDARY)
        spark = Sparkline(s.sparkline, tk, color=color) if s.sparkline else None
        records = fmt.records_line(s.records)
        if symbol is None and records is None:
            if spark is not None:
                spark.deleteLater()
            return None
        row = Row.create(
            tk,
            [Part(symbol, "caption", color), Part(records, "caption", t.TEXT_SECONDARY)],
        )
        if row is not None and spark is not None:
            row.lay.insertWidget(1 if symbol else 0, spark, 0)
        elif spark is not None:
            spark.deleteLater()
        return row

    def _row_h2h(self) -> Row | None:
        h = self.h2h
        if h is None:
            return None
        rec = fmt.h2h_record(h.wins, h.losses, h.ties)
        if rec is None:
            return None
        color = (
            t.POSITIVE if h.wins > h.losses else t.NEGATIVE if h.losses > h.wins else t.TEXT_PRIMARY
        )
        return Row.create(
            self.tokens,
            [
                Part("You", "caption", t.TEXT_MUTED),
                Part(rec, "body", color, 600),
                Part("·", "caption", t.TEXT_MUTED),
                Part(f"{ago(h.last, self._now())} ago", "caption", t.TEXT_SECONDARY),
            ],
        )

    def _row_tendencies(self) -> Row | None:
        v = self.tendencies
        if v is None:
            return None
        avg = fmt.duration(v.avg_duration_s)
        return Row.create(
            self.tokens,
            dotted(
                [
                    Part(fmt.vs_race(v.recent, self.my_race), "caption", t.TEXT_SECONDARY),
                    Part(f"avg {avg}" if avg else None, "caption", t.TEXT_SECONDARY),
                ]
            ),
        )

    def _build(self, slot: str) -> Row | None:
        return getattr(self, f"_row_{slot}")()

    def _render(self, slots: Sequence[str], *, animate: bool = True) -> None:
        allowed = MODE_SLOTS[self.mode]
        changed = False
        for slot in slots:
            if slot not in allowed:
                continue
            new = self._build(slot)
            old = self.rows.get(slot)
            if (
                new is not None
                and old is not None
                and new.texts() == old.texts()
                and not self._has_custom(old)
                and not self._has_custom(new)
            ):
                new.deleteLater()
                continue
            if old is not None:
                idx = self.lay.indexOf(old)
                self.lay.removeWidget(old)
                old.deleteLater()
                del self.rows[slot]
                changed = True
            else:
                idx = -1
            if new is None:
                continue
            if idx < 0:
                idx = sum(1 for s in SLOTS[: SLOTS.index(slot)] if s in self.rows)
            self.lay.insertWidget(idx, new)
            self.rows[slot] = new
            changed = True
            if animate and old is None:
                reveal_row(new)
        if changed:
            self.rows_changed.emit()

    @staticmethod
    def _has_custom(row: Row) -> bool:
        """Rows with painted widgets (badges, sparkline) are compared by rebuilding."""
        return any(isinstance(w, Badge | Sparkline | RaceDot) for w in row.children())


class TeamStrip(QWidget):
    """``Team 4,410 MMR · 12-4 this season`` under a 2v2 card."""

    def __init__(self, info: TeamInfo, tokens: TokenContext, parent: QWidget | None = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.row = self.build(info, tokens)
        if self.row is not None:
            lay.addWidget(self.row)

    @staticmethod
    def build(info: TeamInfo | None, tokens: TokenContext) -> Row | None:
        if info is None or info.team is None:
            return None
        team = info.team
        season = f"{team.wins}-{team.losses} this season" if team.wins + team.losses else None
        values = dotted(
            [
                Part(fmt.mmr(team.rating), "body", t.TEXT_PRIMARY, 600),
                Part(fmt.league_label(team.league_id, team.tier_type), "caption", t.TEXT_SECONDARY),
                Part(season, "caption", t.TEXT_SECONDARY),
            ]
        )
        if not values:
            return None
        return Row.create(tokens, [Part("Team", "caption", t.TEXT_MUTED, 600), *values])

    def is_empty(self) -> bool:
        return self.row is None


class OpponentCard(OverlayWindow):
    """The compact HUD card. 1v1: one section; 2v2: two + team strip; 3v3+: compact."""

    changed = Signal()

    def __init__(
        self,
        tokens: TokenContext,
        placement: Placement,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        parent: QWidget | None = None,
    ):
        super().__init__(tokens, placement, padding=t.PADDING["card"], parent=parent)
        self._now = now
        self.sections: list[OpponentSection] = []
        self.mode: Mode = "full"
        self.team: TeamInfo | None = None
        self._team_row: Row | None = None
        self._footer: Row | None = None
        self._dividers: list[Divider] = []
        self.game_id: int | None = None
        self._seeds: list[GameSeed] = []
        self._my_race: str | None = None
        self.body.setSpacing(tokens.px(t.GAP["section"]))

    # ------------------------------------------------------------------ build
    def start(
        self,
        game_id: int,
        seeds: Sequence[GameSeed],
        *,
        my_race: str | None = None,
    ) -> None:
        """Clear and lay out one section per opponent (names + race only)."""
        self.clear()
        self.game_id = game_id
        self._seeds = list(seeds)
        self._my_race = my_race
        n = len(seeds)
        self.mode = "full" if n <= 1 else "duo" if n == 2 else "compact"
        races = {s.race for s in seeds}
        self.set_accent(race_accent(races.pop()) if len(races) == 1 else race_accent(None))
        for i, seed in enumerate(seeds):
            if i and self.mode != "compact":
                d = Divider(self.tokens)
                self._dividers.append(d)
                self.body.addWidget(d)
            sec = OpponentSection(seed, self.tokens, mode=self.mode, my_race=my_race, now=self._now)
            sec.rows_changed.connect(self._on_rows_changed)
            self.sections.append(sec)
            self.body.addWidget(sec)
        if self.mode == "compact":
            self.body.setSpacing(self.tokens.px(t.GAP["row"]))
        else:
            self.body.setSpacing(self.tokens.px(t.GAP["section"]))
        self._fit()

    def clear(self) -> None:
        while self.body.count():
            item = self.body.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.sections = []
        self._dividers = []
        self._team_row = None
        self._footer = None
        self.team = None
        self.game_id = None

    def section(self, slot: int) -> OpponentSection | None:
        return self.sections[slot] if 0 <= slot < len(self.sections) else None

    def apply(self, u: LookupUpdate) -> None:
        """Route one pipeline update to its section (or the team strip)."""
        if u.slot < 0:
            if u.stage is Stage.TEAM:
                self.set_team(u.data if isinstance(u.data, TeamInfo) else None)
            return
        sec = self.section(u.slot)
        if sec is not None:
            sec.apply(u)

    def set_team(self, info: TeamInfo | None) -> None:
        if self.mode == "compact":
            return
        self.team = info
        row = TeamStrip.build(info, self.tokens)
        if row is None:
            return
        if self._team_row is not None:
            self.body.removeWidget(self._team_row)
            self._team_row.deleteLater()
        else:
            d = Divider(self.tokens)
            self._dividers.append(d)
            self.body.addWidget(d)
            reveal_row(row)
        self._team_row = row
        self.body.addWidget(row)
        self._on_rows_changed()

    def set_tokens(self, tokens: TokenContext) -> None:
        seeds_state = [
            (s.identity, s.rating, s.smurf, s.h2h, s.tendencies, s.seed) for s in self.sections
        ]
        gid, team = self.game_id, self.team
        super().set_tokens(tokens)
        if gid is None:
            return
        self.start(gid, [st[5] for st in seeds_state], my_race=self._my_race)
        for sec, (ident, rating, smurf, h2h, tend, _seed) in zip(
            self.sections, seeds_state, strict=False
        ):
            sec.identity, sec.rating, sec.smurf, sec.h2h, sec.tendencies = (
                ident,
                rating,
                smurf,
                h2h,
                tend,
            )
            sec._render(list(SLOTS), animate=False)
        if team is not None:
            self.set_team(team)
        self._fit()

    # ---------------------------------------------------------------- layout
    def _compact_footer(self) -> None:
        if self.mode != "compact":
            return
        worst = max(self.sections, key=lambda s: s.score, default=None)
        row = None
        if worst is not None and worst.level != "none" and worst.smurf:
            reason = worst.smurf.assessment.top_reason
            if reason is not None:
                fg = t.SMURF_BADGE[worst.level][0]
                row = Row.create(
                    self.tokens,
                    [
                        Part(f"{worst.name}:", "caption", t.TEXT_SECONDARY, 600),
                        Part(reason.text, "caption", fg, elide=True),
                    ],
                )
        if self._footer is not None:
            self.body.removeWidget(self._footer)
            self._footer.deleteLater()
            self._footer = None
        if row is not None:
            self._footer = row
            self.body.addWidget(row)

    def _on_rows_changed(self) -> None:
        self._compact_footer()
        self._fit()
        self.changed.emit()

    def _fit(self) -> None:
        """Clamp the surface width to ``card_min_w``..``card_max_w`` and re-place."""
        tk = self.tokens
        self.surface.setMinimumWidth(0)
        self.surface.setMaximumWidth(16777215)
        natural = self.surface.sizeHint().width()
        w = max(tk.px(t.SIZE["card_min_w"]), min(natural, tk.px(t.SIZE["card_max_w"])))
        self.surface.setFixedWidth(w)
        self.reposition()

    def row_count(self) -> int:
        n = sum(len(s.rows) for s in self.sections)
        return n + (1 if self._team_row else 0) + (1 if self._footer else 0)

    def texts(self) -> list[str]:
        out = [txt for s in self.sections for txt in s.texts()]
        for row in (self._team_row, self._footer):
            if row is not None:
                out.extend(row.texts())
        return out
