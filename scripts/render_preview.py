#!/usr/bin/env python3
"""Render every HUD component offscreen to PNGs (for design review and PR descriptions).

    python scripts/render_preview.py [--out previews] [--only card]

Each component is rendered at scales 1.0 and 1.25 with opacity 0.7 over a dark
gradient that stands in for SC2 terrain. ``hud@<scale>.png`` composites the card,
toasts and hint on a 1600x900 "screen" to show the real footprint.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
if sys.platform == "win32" and "QT_QPA_FONTDIR" not in os.environ:
    # The offscreen platform has no system font database; give it the real fonts.
    os.environ["QT_QPA_FONTDIR"] = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPoint, QRect, QSize, Qt  # noqa: E402
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from smurfsniper.models.config import Config  # noqa: E402
from smurfsniper.ui import preview_data as pd  # noqa: E402
from smurfsniper.ui import tokens as t  # noqa: E402
from smurfsniper.ui.overlay import (  # noqa: E402
    HotkeyHint,
    OpponentCard,
    OverlayWindow,
    Panel,
    ToastSpec,
    ToastStack,
    anchor_point,
    set_animations_enabled,
)
from smurfsniper.ui.overlay.card import dotted  # noqa: E402
from smurfsniper.ui.overlay.widgets import Part, Section, key_row  # noqa: E402
from smurfsniper.ui.panels.intel import build_intel_body  # noqa: E402
from smurfsniper.ui.tokens import TokenContext  # noqa: E402

SCALES = (1.0, 1.25)
OPACITY = 0.7
PAD = 24
HUD_SIZE = QSize(1600, 900)


def terrain(size: QSize) -> QPixmap:
    pm = QPixmap(size)
    g = QLinearGradient(0, 0, size.width(), size.height())
    g.setColorAt(0, QColor("#2B2F36"))
    g.setColorAt(1, QColor("#14161A"))
    p = QPainter(pm)
    p.fillRect(pm.rect(), g)
    p.end()
    return pm


def settle(w: QWidget) -> None:
    app = QApplication.instance()
    w.show()
    for _ in range(3):
        app.processEvents()
    if isinstance(w, OverlayWindow):
        w.reposition()
        app.processEvents()


def render_window(w: QWidget, painter: QPainter, at: QPoint) -> None:
    w.render(painter, at, renderFlags=QWidget.RenderFlag.DrawChildren)


def save_component(w: QWidget, out: Path) -> Path:
    settle(w)
    size = w.size()
    pm = terrain(QSize(size.width() + 2 * PAD, size.height() + 2 * PAD))
    p = QPainter(pm)
    render_window(w, p, QPoint(PAD, PAD))
    p.end()
    pm.save(str(out))
    w.hide()
    return out


# --------------------------------------------------------------- components
def card(tk: TokenContext, profiles, *, stage: str | None = None, team=None) -> OpponentCard:
    c = OpponentCard(tk, Config().overlays.card.placement, now=lambda: pd.NOW)
    c.start(1, [p.seed for p in profiles], my_race="ZERG")
    for i, prof in enumerate(profiles):
        for u in pd.updates_for(1, i, prof):
            c.apply(u)
    if team is not None:
        from smurfsniper.core.lookup import TEAM_SLOT
        from smurfsniper.core.profile import LookupUpdate, Stage

        c.apply(LookupUpdate(1, TEAM_SLOT, Stage.TEAM, team))
    return c


def toasts(tk: TokenContext) -> ToastStack:
    s = ToastStack(tk, Config().overlays.toasts.placement, seconds=60)
    s.push(ToastSpec("SC2Pulse unreachable", "Opponent stats unavailable this game.", "warning"))
    s.push(
        ToastSpec("xXbarcodeXx: likely smurf", "new account (9d)", "danger", chip="Ctrl+Shift+1")
    )
    s.push(ToastSpec("Victory · +24 MMR (4,234)", "Session 5-2 · You 2-0 vs Bob", "win"))
    return s


def intel(tk: TokenContext) -> Panel:
    panel = Panel("Scouting intel", "Ctrl+Shift+2", tk, Config().overlays.panels.placement)
    panel.set_body(build_intel_body([pd.intel_profile()], tk) or [])
    return panel


def stub_panel(tk: TokenContext, title: str, chip: str, rows) -> Panel:
    panel = Panel(title, chip, tk, Config().overlays.panels.placement)
    sec = Section(tk)
    for key, parts in rows:
        sec.add(key_row(tk, key, dotted([Part(x, "caption", t.TEXT_SECONDARY) for x in parts])))
    panel.set_body([sec])
    return panel


def session(tk: TokenContext) -> Panel:
    return stub_panel(
        tk,
        "Session",
        "Ctrl+Shift+3",
        [("GAMES", ["5-2", "+48 MMR"]), ("STREAK", ["W3"]), ("TIME", ["1h 12m"])],
    )


def rivals(tk: TokenContext) -> Panel:
    return stub_panel(
        tk,
        "Rivals",
        "Ctrl+Shift+4",
        [("NEMESIS", ["Bob", "1-5"]), ("VICTIM", ["Alice", "6-1"]), ("MOST", ["Carol", "9 games"])],
    )


def hint(tk: TokenContext) -> HotkeyHint:
    h = HotkeyHint(tk, Config().overlays.hint.placement)
    h.set_items(
        [
            ("Ctrl+Shift+1", "card"),
            ("Ctrl+Shift+2", "intel"),
            ("Ctrl+Shift+3", "session"),
            ("Ctrl+Shift+4", "rivals"),
            ("Ctrl+Shift+`", "hide"),
        ]
    )
    return h


COMPONENTS: dict[str, Callable[[TokenContext], QWidget]] = {
    "card_t0": lambda tk: card(tk, [pd.seed_profile()]),
    "card_t1": lambda tk: card(tk, [pd.pro_profile()]),
    "card_t2": lambda tk: card(tk, [pd.smurf_profile()]),
    "card_2v2": lambda tk: card(tk, pd.duo_profiles(), team=pd.duo_team()),
    "card_4v4": lambda tk: card(tk, pd.quad_profiles()),
    "toasts": toasts,
    "intel": intel,
    "session": session,
    "rivals": rivals,
    "hint": hint,
}


def hud(tk: TokenContext, out: Path) -> Path:
    """Card, toasts and hint composited on a 1600x900 'screen' at their default spots."""
    pm = terrain(HUD_SIZE)
    area = QRect(QPoint(0, 0), HUD_SIZE)
    p = QPainter(pm)
    for w in (card(tk, [pd.smurf_profile()]), toasts(tk), hint(tk)):
        settle(w)
        pos = anchor_point(w.placement, area, w.size(), tk.scale)
        render_window(w, p, pos)
        w.hide()
    p.setPen(QColor(255, 255, 255, 60))
    p.drawText(pm.rect().adjusted(12, 0, 0, -10), int(Qt.AlignmentFlag.AlignBottom), "1600x900")
    p.end()
    pm.save(str(out))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default="previews", help="output directory")
    ap.add_argument("--only", help="render only components whose name starts with this")
    args = ap.parse_args(argv)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    _ = app
    set_animations_enabled(False)
    written: list[Path] = []
    try:
        for scale in SCALES:
            tk = TokenContext(opacity=OPACITY, scale=scale)
            for name, build in COMPONENTS.items():
                if args.only and not name.startswith(args.only):
                    continue
                w = build(tk)
                written.append(save_component(w, out / f"{name}@{scale:g}.png"))
                w.deleteLater()
            if not args.only or "hud".startswith(args.only):
                written.append(hud(tk, out / f"hud@{scale:g}.png"))
    finally:
        set_animations_enabled(True)
    for path in written:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
