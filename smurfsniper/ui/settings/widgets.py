"""Reusable widgets for the Settings window, picker and cheat-sheet."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from smurfsniper.models.config import Anchor, Config, OverlayConfig
from smurfsniper.ui import tokens as t


def qcolor(c: tuple[int, ...]) -> QColor:
    return QColor(*c)


# ---------------------------------------------------------------------- basics
def label(text: str = "", role: str | None = None, *, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if role:
        lb.setProperty("role", role)
    lb.setWordWrap(wrap)
    return lb


def button(text: str, *, primary: bool = False, flat: bool = False) -> QPushButton:
    b = QPushButton(text)
    if primary:
        b.setProperty("primary", True)
    if flat:
        b.setProperty("flat", True)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b


class Card(QFrame):
    """A raised rounded container."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setProperty("role", "card")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(14, 12, 14, 12)
        self.body.setSpacing(8)


def mono_font(size: int = t.FONT_SIZE["mono"]) -> QFont:
    f = QFont()
    f.setFamilies(t.FONT_MONO)
    f.setPixelSize(size + 1)
    f.setWeight(QFont.Weight.Medium)
    return f


class ChipLabel(QLabel):
    """Keycap-style chip, e.g. ``Ctrl+Shift+1``. Uses the CHIP tokens."""

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(text, parent)
        self.setFont(mono_font())
        fg, bg, border = t.CHIP["fg"], t.CHIP["bg"], t.CHIP["border"]
        self.setStyleSheet(
            f"QLabel {{ color: {t.css(fg)}; background: {t.css(bg)};"
            f" border: 1px solid {t.css(border)}; border-radius: {t.RADIUS['chip']}px;"
            f" padding: {t.CHIP['pad_y'] + 1}px {t.CHIP['pad_x'] + 2}px; }}"
        )
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(128)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)


class ToggleSwitch(QAbstractButton):
    """Small animated-less on/off switch."""

    def __init__(self, checked: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(38, 22)

    def sizeHint(self) -> QSize:
        return QSize(38, 22)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        on = self.isChecked()
        track = qcolor(t.INFO) if on else QColor(255, 255, 255, 40)
        if not self.isEnabled():
            track.setAlpha(60)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 1, 38, 20), 10, 10)
        p.setBrush(QColor("white"))
        x = 19.0 if on else 3.0
        p.drawEllipse(QRectF(x, 4, 16, 16))


class LabeledSlider(QWidget):
    """Slider with a live value label. ``value`` is in display units (e.g. percent)."""

    valueChanged = Signal(int)

    def __init__(self, lo: int, hi: int, step: int, suffix: str = "%"):
        super().__init__()
        self._suffix = suffix
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(lo, hi)
        self.slider.setSingleStep(step)
        self.slider.setPageStep(step)
        self.slider.setTickInterval(step)
        self._step = step
        self.value_label = QLabel()
        self.value_label.setFixedWidth(44)
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.value_label)
        self.slider.valueChanged.connect(self._on_changed)
        self._sync_label(lo)

    def _sync_label(self, v: int) -> None:
        self.value_label.setText(f"{v}{self._suffix}")

    def _on_changed(self, v: int) -> None:
        snapped = round(v / self._step) * self._step
        if snapped != v:
            self.slider.setValue(snapped)
            return
        self._sync_label(v)
        self.valueChanged.emit(v)

    def value(self) -> int:
        return self.slider.value()

    def set_value(self, v: int) -> None:
        was = self.slider.blockSignals(True)
        self.slider.setValue(v)
        self.slider.blockSignals(was)
        self._sync_label(self.slider.value())


# ---------------------------------------------------------------------- anchors
_GRID = [
    [Anchor.TOP_LEFT, Anchor.TOP_CENTER, Anchor.TOP_RIGHT],
    [Anchor.CENTER_LEFT, Anchor.CENTER, Anchor.CENTER_RIGHT],
    [Anchor.BOTTOM_LEFT, Anchor.BOTTOM_CENTER, Anchor.BOTTOM_RIGHT],
]


class AnchorGrid(QWidget):
    """3x3 radio buttons rendered as a mini screen."""

    anchorChanged = Signal(object)

    W, H = 84, 54

    def __init__(self, anchor: Anchor = Anchor.TOP_CENTER, parent: QWidget | None = None):
        super().__init__(parent)
        self._anchor = anchor
        self._hover: Anchor | None = None
        self.setFixedSize(self.W, self.H)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def anchor(self) -> Anchor:
        return self._anchor

    def set_anchor(self, anchor: Anchor) -> None:
        self._anchor = anchor
        self.update()

    def _cell(self, a: Anchor) -> QRectF:
        for r, row in enumerate(_GRID):
            for c, cand in enumerate(row):
                if cand is a:
                    cw, ch = (self.W - 8) / 3, (self.H - 8) / 3
                    return QRectF(4 + c * cw + 2, 4 + r * ch + 2, cw - 4, ch - 4)
        return QRectF()

    def _at(self, pos: QPoint) -> Anchor | None:
        for row in _GRID:
            for a in row:
                if self._cell(a).adjusted(-2, -2, 2, 2).contains(QPointF(pos)):
                    return a
        return None

    def mousePressEvent(self, e: QMouseEvent) -> None:
        a = self._at(e.position().toPoint())
        if a is not None and a is not self._anchor:
            self._anchor = a
            self.update()
            self.anchorChanged.emit(a)

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        a = self._at(e.position().toPoint())
        if a is not self._hover:
            self._hover = a
            self.update()

    def leaveEvent(self, _e) -> None:
        self._hover = None
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.setBrush(QColor(255, 255, 255, 10))
        p.drawRoundedRect(QRectF(0.5, 0.5, self.W - 1, self.H - 1), 6, 6)
        p.setPen(Qt.PenStyle.NoPen)
        for row in _GRID:
            for a in row:
                r = self._cell(a)
                if a is self._anchor:
                    p.setBrush(qcolor(t.INFO))
                elif a is self._hover:
                    p.setBrush(QColor(255, 255, 255, 70))
                else:
                    p.setBrush(QColor(255, 255, 255, 28))
                p.drawRoundedRect(r, 3, 3)


class ScreenPreview(QWidget):
    """200x140 mini screen with the configured surfaces drawn at their anchors."""

    W, H = 200, 140
    _SURFACES = (
        ("card", "Card", (96, 165, 250), (62, 26)),
        ("toasts", "Toasts", (61, 220, 132), (44, 14)),
        ("panels", "Panel", (168, 85, 247), (48, 52)),
        ("hint", "Hint", (245, 184, 61), (40, 8)),
    )

    def __init__(self, overlays: OverlayConfig, parent: QWidget | None = None):
        super().__init__(parent)
        self._ov = overlays
        self.setFixedSize(self.W, self.H)

    def set_overlays(self, overlays: OverlayConfig) -> None:
        self._ov = overlays
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, self.W - 1, self.H - 1), 8, 8)
        p.fillPath(path, QColor(255, 255, 255, 12))
        p.setPen(QPen(QColor(255, 255, 255, 45), 1))
        p.drawPath(path)
        ref_w, ref_h = 1920.0, 1080.0
        sx, sy = self.W / ref_w, self.H / ref_h
        margin = t.SCREEN_MARGIN
        for name, _title, color, (w, h) in self._SURFACES:
            cfg = getattr(self._ov, name)
            place = cfg.placement
            if name != "panels" and not getattr(cfg, "enabled", True):
                continue
            a = place.anchor.value
            x = (
                margin * sx
                if a.endswith("left")
                else self.W - w - margin * sx
                if a.endswith("right")
                else (self.W - w) / 2
            )
            y = (
                margin * sy
                if a.startswith("top")
                else self.H - h - margin * sy
                if a.startswith("bottom")
                else (self.H - h) / 2
            )
            x += place.offset_x * self._ov.scale * sx
            y += place.offset_y * self._ov.scale * sy
            x = max(2, min(x, self.W - w - 2))
            y = max(2, min(y, self.H - h - 2))
            c = QColor(*color)
            fill = QColor(c)
            fill.setAlpha(int(70 + 120 * self._ov.opacity))
            p.setPen(QPen(c, 1))
            p.setBrush(fill)
            p.drawRoundedRect(QRectF(x, y, w, h), 4, 4)


# --------------------------------------------------------------------- chip list
class ChipList(QWidget):
    """Removable text chips with an add field. Emits ``itemsChanged(list[str])``."""

    itemsChanged = Signal(list)

    def __init__(self, placeholder: str = "Add name and press Enter"):
        super().__init__()
        self._items: list[str] = []
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(8)
        self._chips = QWidget()
        self._chip_lay = QVBoxLayout(self._chips)
        self._chip_lay.setContentsMargins(0, 0, 0, 0)
        self._chip_lay.setSpacing(6)
        self._rows: list[QHBoxLayout] = []
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.returnPressed.connect(self._add)
        self._outer.addWidget(self._chips)
        self._outer.addWidget(self.edit)
        self._rebuild()

    def items(self) -> list[str]:
        return list(self._items)

    def set_items(self, items: list[str]) -> None:
        self._items = list(items)
        self._rebuild()

    def _add(self) -> None:
        text = self.edit.text().strip().split("#")[0].strip()
        self.edit.clear()
        if text and text.casefold() not in {i.casefold() for i in self._items}:
            self._items.append(text)
            self._rebuild()
            self.itemsChanged.emit(self.items())

    def _remove(self, text: str) -> None:
        self._items = [i for i in self._items if i != text]
        self._rebuild()
        self.itemsChanged.emit(self.items())

    def _rebuild(self) -> None:
        while self._chip_lay.count():
            item = self._chip_lay.takeAt(0)
            lay = item.layout()
            if lay is not None:
                while lay.count():
                    w = lay.takeAt(0).widget()
                    if w is not None:
                        w.deleteLater()
            w = item.widget()
            if w is not None:
                w.deleteLater()
        row: QHBoxLayout | None = None
        for i, text in enumerate(self._items):
            if i % 3 == 0:
                row = QHBoxLayout()
                row.setSpacing(6)
                self._chip_lay.addLayout(row)
            assert row is not None
            row.addWidget(self._chip(text))
        if row is not None:
            row.addStretch(1)

    def _chip(self, text: str) -> QWidget:
        w = QFrame()
        w.setStyleSheet(
            "QFrame { background: rgba(96,165,250,0.16); border-radius: 11px; }"
            "QLabel { background: transparent; }"
        )
        lay = QHBoxLayout(w)
        lay.setContentsMargins(10, 2, 4, 2)
        lay.setSpacing(4)
        lay.addWidget(QLabel(text))
        x = QPushButton("✕")
        x.setFixedSize(18, 18)
        x.setCursor(Qt.CursorShape.PointingHandCursor)
        x.setStyleSheet(
            "QPushButton { background: transparent; border: none; border-radius: 9px;"
            " color: rgba(255,255,255,0.6); padding: 0; font-size: 10px; }"
            "QPushButton:hover { background: rgba(255,255,255,0.18); color: white; }"
        )
        x.clicked.connect(lambda: self._remove(text))
        lay.addWidget(x)
        return w


# ----------------------------------------------------------------- frameless bar
class TitleBar(QWidget):
    """Draggable title row with a close button, for frameless dialogs."""

    closeRequested = Signal()

    def __init__(self, title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._drag: QPoint | None = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 12, 10, 4)
        self.title = label(title, "h2")
        lay.addWidget(self.title, 1)
        close = button("✕", flat=True)
        close.setFixedSize(28, 28)
        close.setToolTip("Close (Esc)")
        close.clicked.connect(self.closeRequested)
        lay.addWidget(close)

    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = e.globalPosition().toPoint() - self.window().frameGeometry().topLeft()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._drag is not None and e.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(e.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, _e) -> None:
        self._drag = None


# ------------------------------------------------------------- settings plumbing
@dataclass
class SettingsHooks:
    """Callbacks the app gives the Settings window. All are optional (no-ops by default)."""

    change_account: Callable[[], None] = lambda: None
    refresh_mmr: Callable[[], None] = lambda: None
    test_aligulac: Callable[[str], bool] | None = None  # blocking; run off the GUI thread
    cache_stats: Callable[[], tuple[int, int] | None] = lambda: None
    clear_cache: Callable[[], None] = lambda: None
    open_path: Callable[[str], None] = lambda _which: None  # "config" | "logs" | "data"
    preview: Callable[[Config], None] = lambda _cfg: None
    suspend_hotkeys: Callable[[], None] = lambda: None
    resume_hotkeys: Callable[[], None] = lambda: None
    screens: Callable[[], list[str]] = lambda: [s.name() for s in QGuiApplication.screens()]
    version: str = ""


class SettingsTab(QWidget):
    """Base for a settings page. Mutates ``config`` in place and emits ``changed``."""

    changed = Signal()

    def __init__(self, config: Config, hooks: SettingsHooks):
        super().__init__()
        self.config = config
        self.hooks = hooks
        self._loading = False
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(24, 20, 24, 20)
        self.root.setSpacing(14)

    def commit(self) -> None:
        if not self._loading:
            self.changed.emit()

    def refresh(self) -> None:  # reload widgets from self.config
        pass

    def reset_defaults(self) -> None:
        pass

    def set_config(self, config: Config) -> None:
        self.config = config
        self._loading = True
        try:
            self.refresh()
        finally:
            self._loading = False

    def heading(self, title: str, subtitle: str = "") -> None:
        self.root.addWidget(label(title, "title"))
        if subtitle:
            self.root.addWidget(label(subtitle, "muted", wrap=True))


def form_row(title: str, control: QWidget, hint: str = "") -> QWidget:
    """``title`` (+ muted ``hint``) on the left, ``control`` on the right."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(16)
    left = QVBoxLayout()
    left.setSpacing(1)
    left.addWidget(label(title))
    if hint:
        left.addWidget(label(hint, "muted", wrap=True))
    lay.addLayout(left, 1)
    lay.addWidget(control, 0, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return w
