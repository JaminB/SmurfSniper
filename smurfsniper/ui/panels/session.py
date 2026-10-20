"""Session tracker panel body (Ctrl+Shift+3).

::

    7-3   +58 MMR   4,152 → 4,210
    ▁▂▃▂▄▅▆▅▇█   streak W3 · 1h 12m played
    vZ 3-1 · vT 2-2 · vP 2-0

With no games the body is the single row "No games yet this session". The MMR figures
only appear once a post-game rating is known.
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from smurfsniper.analyze.history import sparkline
from smurfsniper.analyze.session import SessionSnapshot
from smurfsniper.ui import fmt
from smurfsniper.ui import tokens as t
from smurfsniper.ui.overlay.card import dotted
from smurfsniper.ui.overlay.widgets import Part, Row, Section, Sparkline, Text
from smurfsniper.ui.tokens import TokenContext

EMPTY_TEXT = "No games yet this session"


def played_text(seconds: int) -> str | None:
    """``1h 12m`` / ``42m``; None under a minute."""
    minutes = seconds // 60
    if minutes < 1:
        return None
    h, m = divmod(minutes, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def record_html(snap: SessionSnapshot) -> str:
    pos, neg, mut = t.css(t.POSITIVE), t.css(t.NEGATIVE), t.css(t.TEXT_SECONDARY)
    html = f'<span style="color:{pos}">{snap.wins}</span>-<span style="color:{neg}">{snap.losses}</span>'
    if snap.ties:
        html += f'<span style="color:{mut}">-{snap.ties}</span>'
    return html


def _record_row(snap: SessionSnapshot, tk: TokenContext) -> Row:
    row = Row(tk)
    row.lay.addWidget(Text(record_html(snap), tk, role="title", weight=600, rich=True))
    if snap.mmr_delta is not None:
        color = (
            t.POSITIVE if snap.mmr_delta > 0 else t.NEGATIVE if snap.mmr_delta < 0 else t.TEXT_MUTED
        )
        row.lay.addWidget(
            Text(f"{snap.mmr_delta:+d} MMR", tk, role="body", color=color, weight=600)
        )
        if snap.mmr_start and snap.mmr_now:
            span = f"{snap.mmr_start:,} → {snap.mmr_now:,}"
            row.lay.addWidget(Text(span, tk, role="caption", color=t.TEXT_SECONDARY))
    row.lay.addStretch(1)
    return row


def _streak_row(snap: SessionSnapshot, tk: TokenContext) -> Row | None:
    bars = sparkline(list(snap.mmr_points)) if len(snap.mmr_points) >= 3 else None
    streak = None
    if snap.streak is not None and snap.streak[1] >= 2:
        kind, n = snap.streak
        streak = Part(
            f"streak {kind}{n}", "caption", t.POSITIVE if kind == "W" else t.NEGATIVE, 600
        )
    played = Part(
        f"{p} played" if (p := played_text(snap.time_played_s)) else None,
        "caption",
        t.TEXT_SECONDARY,
    )
    lead = None
    if bars:
        trend = t.POSITIVE if (snap.mmr_delta or 0) >= 0 else t.NEGATIVE
        lead = Sparkline(bars, tk, color=trend)
    return Row.create(tk, dotted([streak, played]), lead=lead)


def build(snap: SessionSnapshot | None, tk: TokenContext) -> list[QWidget]:
    """The panel body; always at least one row."""
    sec = Section(tk)
    if snap is None or snap.games == 0:
        sec.add(Row.create(tk, [Part(EMPTY_TEXT, "body", t.TEXT_SECONDARY)]))
        return [sec]
    sec.add(_record_row(snap, tk))
    sec.add(_streak_row(snap, tk))
    matchups = fmt.join([f"{k} {rec}" for k, rec in snap.by_matchup.items() if rec.games])
    sec.add(Row.create(tk, [Part(matchups, "caption", t.TEXT_SECONDARY)]))
    return [sec]
