"""Legacy frameless text overlay (replaced by the HUD framework in a later branch)."""

from __future__ import annotations

import re

from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from smurfsniper.models.config import Anchor, Placement
from smurfsniper.ui import tokens
from smurfsniper.ui.overlay_manager import register_overlay

_RGBA_BG = re.compile(r"(background-color:\s*rgba\(\s*\d+,\s*\d+,\s*\d+,\s*)\d+(\s*\))")
_SIZE_PX = re.compile(r"(font-size:\s*)(\d+)(px)")


def styled(style: str, *, opacity: float = 0.7, scale: float = 1.0) -> str:
    """Apply the configured surface opacity and UI scale to a legacy stylesheet."""
    alpha = max(0, min(255, round(opacity * 255)))
    style = _RGBA_BG.sub(lambda m: f"{m.group(1)}{alpha}{m.group(2)}", style)
    return _SIZE_PX.sub(lambda m: f"{m.group(1)}{round(int(m.group(2)) * scale)}px", style)


def anchor_position(
    anchor: Anchor, area: tuple[int, int, int, int], size: tuple[int, int], offset: tuple[int, int]
) -> tuple[int, int]:
    """Top-left point for a widget of ``size`` anchored inside ``area`` (x, y, w, h)."""
    ax, ay, aw, ah = area
    w, h = size
    m = tokens.SCREEN_MARGIN
    name = anchor.value
    if name.endswith("left"):
        x = ax + m
    elif name.endswith("right"):
        x = ax + aw - w - m
    else:
        x = ax + (aw - w) // 2
    if name.startswith("top"):
        y = ay + m
    elif name.startswith("bottom"):
        y = ay + ah - h - m
    else:
        y = ay + (ah - h) // 2
    x += offset[0]
    y += offset[1]
    return max(ax, min(x, ax + aw - w)), max(ay, min(y, ay + ah - h))


def screen_area(index: int | None) -> tuple[int, int, int, int]:
    screens = QGuiApplication.screens()
    screen = screens[index] if index is not None and 0 <= index < len(screens) else None
    screen = screen or QGuiApplication.primaryScreen()
    g = screen.availableGeometry()
    return g.x(), g.y(), g.width(), g.height()


class Overlay(QWidget):
    PLAYER_STYLE = """
        color: #FFFFFF;
        background-color: rgba(15, 15, 15, 178);
        padding: 8px 14px;
        border-radius: 10px;
        font-family: 'Segoe UI';
        font-size: 13px;
        font-weight: 500;
        line-height: 145%;
    """

    TM_STYLE = """
        color: #CCCCCC;
        background-color: rgba(10, 10, 10, 160);
        padding: 6px 10px;
        border-radius: 8px;
        font-family: 'Segoe UI';
        font-size: 12px;
        line-height: 140%;
    """

    def __init__(
        self,
        duration_seconds: int = 40,
        placement: Placement | None = None,
        *,
        screen: int | None = None,
        scale: float = 1.0,
        parent=None,
    ):
        super().__init__(parent)

        self.duration_seconds = duration_seconds
        self.placement = placement or Placement(anchor=Anchor.TOP_CENTER)
        self.screen_index = screen
        self.scale = scale

        app = QApplication.instance()
        if not app:
            raise RuntimeError("QApplication must exist before creating Overlay.")

        register_overlay(self)

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.main_layout.setSpacing(6)

    def add_row(self, blocks: list[str], style: str | None = None, spacing: int = 18):
        row = QHBoxLayout()
        row.setSpacing(spacing)

        for text in blocks:
            lbl = QLabel(text, self)
            if style:
                lbl.setStyleSheet(style)
            row.addWidget(lbl, 1)

        self.main_layout.addLayout(row)

    def _position_overlay(self):
        self.adjustSize()
        p = self.placement
        offset = (round(p.offset_x * self.scale), round(p.offset_y * self.scale))
        x, y = anchor_position(
            p.anchor, screen_area(self.screen_index), (self.width(), self.height()), offset
        )
        self.move(x, y)

    def show(self):
        super().show()

        self._position_overlay()

        loop = QEventLoop()
        QTimer.singleShot(0, loop.quit)
        loop.exec()

        if self.duration_seconds > 0:
            QTimer.singleShot(int(self.duration_seconds * 1000), self.close)


def show_sample(config) -> list[Overlay]:
    """Preview: a sample card, toast and panel at their configured placements for 8 s."""
    ov = config.overlays
    style = styled(Overlay.PLAYER_STYLE, opacity=ov.opacity, scale=ov.scale)
    samples = (
        (ov.card.placement, "🔎 Preview · Opponent card\nDiamond 2 · 4,210 MMR"),
        (ov.toasts.placement, "Toast\nTendencies and recaps appear here"),
        (ov.panels.placement, "Panel\nScouting intel and rivals"),
    )
    shown = []
    for placement, text in samples:
        o = Overlay(duration_seconds=8, placement=placement, screen=ov.screen, scale=ov.scale)
        o.add_row([text], style=style)
        o.show()
        shown.append(o)
    return shown
