"""On-demand panels. Each panel shows its own hotkey as a chip; that hotkey closes it."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from smurfsniper.models.config import Placement
from smurfsniper.ui import tokens as t
from smurfsniper.ui.overlay.base import OverlayWindow
from smurfsniper.ui.overlay.widgets import Chip, Divider, Skeleton, Text
from smurfsniper.ui.tokens import TokenContext

CLOSE_GLYPH = "✕"


class Panel(OverlayWindow):
    """Header (title + ``[hotkey ✕]`` chip), divider, body sections."""

    surface_radius = "panel"

    def __init__(
        self,
        title: str,
        hotkey_display: str,
        tokens: TokenContext,
        placement: Placement,
        accent: QColor | None = None,
        *,
        parent: QWidget | None = None,
    ):
        super().__init__(tokens, placement, accent=accent, padding=(0, 0), parent=parent)
        self.title_text = title
        self.hotkey_display = hotkey_display
        self.loading = False
        self.body.setSpacing(0)
        self._build_header()
        self.content = QWidget()
        self.content.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.content_lay = QVBoxLayout(self.content)
        self.body.addWidget(self.content)
        self._apply_content_margins()
        self.surface.setFixedWidth(tokens.px(t.SIZE["panel_w"]))
        self.surface.setMaximumHeight(tokens.px(t.SIZE["panel_max_h"]))

    def _apply_margins(self) -> None:
        super()._apply_margins()
        self.body.setContentsMargins(0, 0, 0, 0)  # header/content carry their own padding

    def _build_header(self) -> None:
        tk = self.tokens
        self.header = QWidget()
        self.header.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        lay = QHBoxLayout(self.header)
        v, h = (tk.px(x) for x in t.PADDING["panel_header"])
        bar = tk.px(t.ACCENT_BAR_WIDTH) if self._has_accent() else 0
        lay.setContentsMargins(h + bar, v, h, v)
        lay.setSpacing(tk.px(t.GAP["inline"]))
        self.title = Text(self.title_text, tk, role="title", weight=600, elide=True)
        lay.addWidget(self.title, 1)
        self.chip = Chip(f"{self.hotkey_display}  {CLOSE_GLYPH}", tk)
        lay.addWidget(self.chip, 0, Qt.AlignmentFlag.AlignVCenter)
        self.body.addWidget(self.header)
        self.body.addWidget(Divider(tk))

    def _apply_content_margins(self) -> None:
        tk = self.tokens
        v, h = (tk.px(x) for x in t.PADDING["panel"])
        bar = tk.px(t.ACCENT_BAR_WIDTH) if self._has_accent() else 0
        self.content_lay.setContentsMargins(h + bar, v, h, v)
        self.content_lay.setSpacing(tk.px(t.GAP["section"]))

    # ------------------------------------------------------------------ api
    def _clear_content(self) -> None:
        while self.content_lay.count():
            item = self.content_lay.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

    def set_body(self, sections: Sequence[QWidget]) -> None:
        self._clear_content()
        self.loading = False
        for i, sec in enumerate(sections):
            if i:
                self.content_lay.addWidget(Divider(self.tokens))
            self.content_lay.addWidget(sec)
        self.reposition()

    def set_loading(self, label: str = "Loading…") -> None:
        """A single pulsing row; only while a requested stage is in flight."""
        self._clear_content()
        self.loading = True
        self.content_lay.addWidget(Skeleton(label, self.tokens))
        self.reposition()

    def body_widgets(self) -> list[QWidget]:
        return [
            self.content_lay.itemAt(i).widget()
            for i in range(self.content_lay.count())
            if self.content_lay.itemAt(i).widget() is not None
        ]

    def texts(self) -> list[str]:
        return [w.text() for w in self.findChildren(QLabel)]


class PanelHost:
    """One panel slot: a panel's hotkey toggles it, another panel's hotkey swaps it."""

    def __init__(self) -> None:
        self.key: str | None = None
        self.panel: Panel | None = None
        # Panels fading out. Python owns these parentless windows, so dropping the
        # last reference (or a GC pass over the dismiss callback cycle) would destroy
        # one mid-fade; keep them until the fade is done.
        self._closing: list[Panel] = []

    def toggle(self, key: str, builder: Callable[[], Panel]) -> Panel | None:
        """Visible ``key`` -> dismiss it. Otherwise dismiss the current one, show ``key``."""
        if self.key == key and self.panel is not None and self.panel.shown:
            self.hide()
            return None
        self.hide()
        panel = builder()
        self.key, self.panel = key, panel
        panel.reveal()
        return panel

    def current(self, key: str | None = None) -> Panel | None:
        if self.panel is None or not self.panel.shown:
            return None
        if key is not None and self.key != key:
            return None
        return self.panel

    def hide(self) -> None:
        old, self.panel, self.key = self.panel, None, None
        if old is not None:
            self._closing.append(old)
            old.dismiss(then=lambda: self._closed(old))

    def _closed(self, panel: Panel) -> None:
        if panel in self._closing:
            self._closing.remove(panel)
        panel.deleteLater()

    def set_tokens(self, tokens: TokenContext) -> None:
        if self.panel is not None:
            self.panel.set_tokens(tokens)
