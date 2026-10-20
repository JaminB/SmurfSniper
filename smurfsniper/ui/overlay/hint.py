"""Hotkey hint: a short-lived pill at game start listing the HUD hotkeys."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QWidget

from smurfsniper.models.config import Placement
from smurfsniper.ui import tokens as t
from smurfsniper.ui.overlay.base import OverlayWindow
from smurfsniper.ui.overlay.widgets import Chip, Text
from smurfsniper.ui.tokens import TokenContext


class HotkeyHint(OverlayWindow):
    """``SmurfSniper  [Ctrl+Shift+1] card  [Ctrl+Shift+2] intel ...``"""

    surface_radius = "hint"

    def __init__(
        self,
        tokens: TokenContext,
        placement: Placement,
        *,
        parent: QWidget | None = None,
    ):
        super().__init__(tokens, placement, padding=t.PADDING["hint"], parent=parent)
        self.items: list[tuple[str, str]] = []
        self.row = QWidget()
        self.row.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.lay = QHBoxLayout(self.row)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.body.addWidget(self.row)
        self.surface.setFixedHeight(tokens.px(t.SIZE["hint_h"]))

    def set_items(self, items: Sequence[tuple[str, str]]) -> None:
        """``[(chip text, label), ...]``."""
        self.items = list(items)
        tk = self.tokens
        while self.lay.count():
            item = self.lay.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.lay.setSpacing(tk.px(t.GAP["inline"]))
        self.lay.addWidget(Text("SmurfSniper", tk, role="micro", color=t.TEXT_MUTED, weight=600))
        for chip, label in self.items:
            self.lay.addSpacing(tk.px(t.SPACE["xs"]))
            self.lay.addWidget(Chip(chip, tk), 0, Qt.AlignmentFlag.AlignVCenter)
            self.lay.addWidget(Text(label, tk, role="caption", color=t.TEXT_SECONDARY))
        self.reposition()

    def set_tokens(self, tokens: TokenContext) -> None:
        super().set_tokens(tokens)
        self.surface.setFixedHeight(tokens.px(t.SIZE["hint_h"]))
        self.set_items(self.items)
