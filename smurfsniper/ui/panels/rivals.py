"""Rivals panel body (Ctrl+Shift+4): nemesis, favourite victim and the most-played list."""

from __future__ import annotations

from datetime import UTC, datetime

from PySide6.QtWidgets import QWidget

from smurfsniper.analyze.rivals import Rival, RivalsSummary
from smurfsniper.core.profile import ago
from smurfsniper.ui import tokens as t
from smurfsniper.ui.overlay.widgets import Part, RaceDot, Row, Section, Text, key_row
from smurfsniper.ui.tokens import TokenContext

EMPTY_TEXT = "Play the same opponent twice to start a rivalry"
RACE_BY_INITIAL = {"ZERG": "Z", "TERRAN": "T", "PROTOSS": "P", "RANDOM": "R"}


def record_color(r: Rival) -> tuple[int, int, int]:
    rec = r.record
    if rec.wins > rec.losses:
        return t.POSITIVE
    if rec.losses > rec.wins:
        return t.NEGATIVE
    return t.TEXT_PRIMARY


def _name(r: Rival) -> str:
    initial = RACE_BY_INITIAL.get(r.last_race or "")
    return f"{r.name} ({initial})" if initial else r.name


def _highlight(tk: TokenContext, key: str, r: Rival | None, now: datetime) -> Row | None:
    if r is None:
        return None
    return key_row(
        tk,
        key,
        [
            Part(_name(r), "body", t.TEXT_PRIMARY, 600, elide=True),
            Part(str(r.record), "body", record_color(r), 600),
            Part(f"last {ago(r.last_played, now)} ago", "caption", t.TEXT_SECONDARY),
        ],
        width=52,
    )


def _list_row(tk: TokenContext, r: Rival, now: datetime) -> Row:
    """``● Bob   2-6   8 games          3d``"""
    row = Row(tk)
    row.lay.addWidget(RaceDot(r.last_race, tk, glyph=r.last_race in t.RACE_GLYPH))
    name = Text(r.name, tk, role="body", weight=600, elide=True)
    name.setFixedWidth(tk.px(104))
    row.lay.addWidget(name)
    rec = Text(str(r.record), tk, role="body", color=record_color(r), weight=600)
    rec.setFixedWidth(tk.px(40))
    row.lay.addWidget(rec)
    row.lay.addWidget(Text(f"{r.games} games", tk, role="caption", color=t.TEXT_SECONDARY))
    row.lay.addStretch(1)
    row.lay.addWidget(Text(ago(r.last_played, now), tk, role="caption", color=t.TEXT_MUTED))
    return row


def build(
    summary: RivalsSummary | None, tk: TokenContext, *, now: datetime | None = None
) -> list[QWidget] | None:
    """None while the summary is still loading; the empty-state row when it has no rivals."""
    if summary is None:
        return None
    now = now or datetime.now(UTC)
    if summary.is_empty():
        sec = Section(tk)
        sec.add(Row.create(tk, [Part(EMPTY_TEXT, "body", t.TEXT_SECONDARY)]))
        return [sec]
    out: list[QWidget] = []
    top = Section(tk)
    shown = top.add(_highlight(tk, "NEMESIS", summary.nemesis, now))
    shown |= top.add(_highlight(tk, "VICTIM", summary.favourite_victim, now))
    if shown:
        out.append(top)
    else:
        top.deleteLater()
    lst = Section(tk)
    for r in summary.top:
        lst.add(_list_row(tk, r, now))
    out.append(lst)
    return out
