"""``OverlayWindow``: click-through, never-focused, glass surface with fade/slide.

Every overlay is a frameless top-level whose contents margin leaves room for the
drop shadow. The visible glass is the inner ``Surface`` frame, painted with a rounded
path, a 1px border and an optional 3px accent bar. The window never takes focus and
never receives mouse input, so SC2 keeps both.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QParallelAnimationGroup,
    QPoint,
    QPropertyAnimation,
    QRect,
    QSize,
    Qt,
)
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPaintEvent
from PySide6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QVBoxLayout, QWidget

from smurfsniper.models.config import Anchor, Placement
from smurfsniper.ui import tokens as t
from smurfsniper.ui.tokens import TokenContext

_ANIMATE = True
START_OPACITY = 0.01  # layered windows can flicker at exactly 0 on some GPU drivers

OVERLAY_FLAGS = (
    Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.Tool
    | Qt.WindowType.WindowStaysOnTopHint
    | Qt.WindowType.WindowTransparentForInput
    | Qt.WindowType.WindowDoesNotAcceptFocus
    | Qt.WindowType.NoDropShadowWindowHint
)


def set_animations_enabled(enabled: bool) -> None:
    """Tests and the preview script turn animations off so geometry is immediate."""
    global _ANIMATE
    _ANIMATE = enabled


def animations_enabled() -> bool:
    return _ANIMATE


def easing(name: str) -> QEasingCurve:
    return QEasingCurve(getattr(QEasingCurve.Type, name, QEasingCurve.Type.OutCubic))


def qcolor(rgb: tuple[int, ...], a: int | None = None) -> QColor:
    if a is not None:
        return QColor(rgb[0], rgb[1], rgb[2], a)
    return QColor(*rgb)


# ------------------------------------------------------------------ placement
def screen_rect(index: int | None) -> QRect:
    """Available geometry (device-independent px) of screen ``index`` or the primary."""
    screens = QGuiApplication.screens()
    screen = screens[index] if index is not None and 0 <= index < len(screens) else None
    screen = screen or QGuiApplication.primaryScreen()
    if screen is None:
        return QRect(0, 0, 1920, 1080)
    return screen.availableGeometry()


def anchor_point(placement: Placement, area: QRect, size: QSize, scale: float = 1.0) -> QPoint:
    """Top-left for a window of ``size`` at ``placement`` inside ``area``.

    The anchor sits ``SCREEN_MARGIN`` in from the edge, then the (scaled) offsets are
    added and the result is clamped inside ``area``. Bottom anchors keep the bottom
    edge fixed, so a growing window grows upward.
    """
    m = t.px(t.SCREEN_MARGIN, scale)
    w, h = size.width(), size.height()
    name = Anchor(placement.anchor).value
    if name.endswith("left"):
        x = area.x() + m
    elif name.endswith("right"):
        x = area.x() + area.width() - w - m
    else:
        x = area.x() + (area.width() - w) // 2
    if name.startswith("top"):
        y = area.y() + m
    elif name.startswith("bottom"):
        y = area.y() + area.height() - h - m
    else:
        y = area.y() + (area.height() - h) // 2
    x += t.px(placement.offset_x, scale)
    y += t.px(placement.offset_y, scale)
    x = max(area.x(), min(x, area.x() + area.width() - w))
    y = max(area.y(), min(y, area.y() + area.height() - h))
    return QPoint(x, y)


def slide_vector(anchor: Anchor, distance: int) -> QPoint:
    """Where a revealing window starts relative to its final position."""
    name = Anchor(anchor).value
    if name.startswith("top"):
        return QPoint(0, -distance)
    if name.startswith("bottom"):
        return QPoint(0, distance)
    if name.endswith("right"):
        return QPoint(distance, 0)
    if name.endswith("left"):
        return QPoint(-distance, 0)
    return QPoint(0, distance)


# -------------------------------------------------------------------- surface
class Surface(QFrame):
    """The glass card: rounded fill at the configured opacity, border, accent bar."""

    def __init__(
        self,
        tokens: TokenContext,
        *,
        radius: str = "card",
        accent: QColor | None = None,
        raised: bool = False,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.tokens = tokens
        self.radius_key = radius
        self.accent = accent
        self.raised = raised
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._shadow = QGraphicsDropShadowEffect(self)
        self.setGraphicsEffect(self._shadow)
        self._apply_shadow()

    def restore_shadow(self) -> None:
        """Re-create the drop shadow after a temporary effect (Qt deletes replaced ones)."""
        self._shadow = QGraphicsDropShadowEffect(self)
        self.setGraphicsEffect(self._shadow)
        self._apply_shadow()

    def _apply_shadow(self) -> None:
        s = t.SHADOW
        self._shadow.setBlurRadius(self.tokens.px(s["blur"]))
        self._shadow.setOffset(self.tokens.px(s["dx"]), self.tokens.px(s["dy"]))
        self._shadow.setColor(qcolor(s["color"]))

    def set_tokens(self, tokens: TokenContext) -> None:
        self.tokens = tokens
        self._apply_shadow()
        self.update()

    def set_accent(self, accent: QColor | None) -> None:
        self.accent = accent
        self.update()

    def corner_radius(self) -> float:
        r = t.RADIUS[self.radius_key]
        return min(self.tokens.px(r), self.height() / 2)

    def paintEvent(self, _e: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        bw = t.BORDER_WIDTH
        rect = self.rect().adjusted(0, 0, -bw, -bw)
        r = self.corner_radius()
        path = QPainterPath()
        path.addRoundedRect(rect.toRectF().adjusted(0.5, 0.5, 0, 0), r, r)
        if self.raised:
            fill = qcolor(t.SURFACE_RAISED, self.tokens.raised_alpha)
        else:
            fill = qcolor(t.SURFACE, self.tokens.surface_alpha)
        p.fillPath(path, fill)
        if self.accent is not None:
            p.save()
            p.setClipPath(path)
            bar = self.tokens.px(t.ACCENT_BAR_WIDTH)
            p.fillRect(QRect(0, 0, bar, self.height()), self.accent)
            p.restore()
        p.setPen(qcolor(t.BORDER))
        p.drawPath(path)
        p.end()


# ------------------------------------------------------------------- window
class OverlayWindow(QWidget):
    """Base for every HUD surface. Subclasses fill ``self.body`` (the surface layout)."""

    surface_radius = "card"
    paints_surface = True

    def __init__(
        self,
        tokens: TokenContext,
        placement: Placement,
        *,
        accent: QColor | None = None,
        padding: tuple[int, int] = t.PADDING["card"],
        parent: QWidget | None = None,
    ):
        super().__init__(parent, OVERLAY_FLAGS)
        self.tokens = tokens
        self.placement = placement
        self.padding = padding
        self._dismissing = False
        self._anim: QAbstractAnimation | None = None
        self._geo_anim: QPropertyAnimation | None = None
        self._then: Callable[[], None] | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._outer = QVBoxLayout(self)
        self._outer.setSpacing(0)
        if self.paints_surface:
            self.surface: QWidget = Surface(tokens, radius=self.surface_radius, accent=accent)
        else:
            self.surface = QWidget()
            self.surface.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._outer.addWidget(self.surface)
        self.body = QVBoxLayout(self.surface)
        self._apply_margins()

    # ---------------------------------------------------------------- tokens
    def _apply_margins(self) -> None:
        m = self.tokens.px(t.SHADOW["blur"] / 2)
        self._outer.setContentsMargins(m, m, m, m)
        if self.paints_surface:
            v, h = (self.tokens.px(x) for x in self.padding)
            bar = self.tokens.px(t.ACCENT_BAR_WIDTH) if self._has_accent() else 0
            self.body.setContentsMargins(h + bar, v, h, v)
        else:
            self.body.setContentsMargins(0, 0, 0, 0)

    def _has_accent(self) -> bool:
        return isinstance(self.surface, Surface) and self.surface.accent is not None

    def set_tokens(self, tokens: TokenContext) -> None:
        """Opacity / scale changed live."""
        self.tokens = tokens
        if isinstance(self.surface, Surface):
            self.surface.set_tokens(tokens)
        self._apply_margins()
        self.reposition()

    def set_accent(self, accent: QColor | None) -> None:
        if isinstance(self.surface, Surface):
            self.surface.set_accent(accent)
        self._apply_margins()

    def set_placement(self, placement: Placement) -> None:
        self.placement = placement
        self.reposition()

    # -------------------------------------------------------------- geometry
    def target_geometry(self) -> QRect:
        self.adjustSize()
        size = self.sizeHint().expandedTo(self.minimumSizeHint())
        size = size.boundedTo(self.maximumSize())
        area = screen_rect(self.tokens.screen)
        return QRect(anchor_point(self.placement, area, size, self.tokens.scale), size)

    def reposition(self) -> None:
        """Recompute geometry from the placement and the content size."""
        geo = self.target_geometry()
        if self.isVisible() and _ANIMATE and not self._dismissing and geo != self.geometry():
            dur, curve = t.ANIM["card_resize"]
            if self._geo_anim is None:
                self._geo_anim = QPropertyAnimation(self, b"geometry", self)
            self._geo_anim.stop()
            self._geo_anim.setDuration(dur)
            self._geo_anim.setEasingCurve(easing(curve))
            self._geo_anim.setStartValue(self.geometry())
            self._geo_anim.setEndValue(geo)
            self._geo_anim.start()
        else:
            if self._geo_anim is not None:
                self._geo_anim.stop()
            self.setGeometry(geo)

    # ------------------------------------------------------------- show/hide
    @property
    def shown(self) -> bool:
        """Visible and not on its way out."""
        return self.isVisible() and not self._dismissing

    def reveal(self) -> None:
        """Show at the final geometry with a fade + short slide from the anchor side."""
        self._stop_anim()
        self._dismissing = False
        if self._geo_anim is not None:
            self._geo_anim.stop()
        geo = self.target_geometry()
        if self.isVisible():
            self.setWindowOpacity(1.0)
            self.reposition()
            self.raise_()
            return
        self.setGeometry(geo)
        if not _ANIMATE:
            self.setWindowOpacity(1.0)
            self.show()
            self.raise_()
            return
        self.setWindowOpacity(START_OPACITY)
        self.show()
        self.raise_()
        fade_ms, fade_curve = t.ANIM["fade_in"]
        slide_ms, slide_curve = t.ANIM["slide_in"]
        group = QParallelAnimationGroup(self)
        fade = QPropertyAnimation(self, b"windowOpacity", group)
        fade.setDuration(fade_ms)
        fade.setEasingCurve(easing(fade_curve))
        fade.setStartValue(START_OPACITY)
        fade.setEndValue(1.0)
        group.addAnimation(fade)
        slide = QPropertyAnimation(self, b"pos", group)
        slide.setDuration(slide_ms)
        slide.setEasingCurve(easing(slide_curve))
        offset = slide_vector(self.placement.anchor, self.tokens.px(t.ANIM["slide_px"]))
        slide.setStartValue(geo.topLeft() + offset)
        slide.setEndValue(geo.topLeft())
        group.addAnimation(slide)
        self._anim = group
        group.start()

    def dismiss(self, *, then: Callable[[], None] | None = None) -> None:
        """Fade out and hide (the window is kept for reuse)."""
        if not self.isVisible():
            self._dismissing = False
            if then is not None:
                then()
            return
        if self._dismissing:
            return
        self._stop_anim()
        if not _ANIMATE:
            self.hide()
            if then is not None:
                then()
            return
        self._dismissing = True
        self._then = then
        dur, curve = t.ANIM["fade_out"]
        fade = QPropertyAnimation(self, b"windowOpacity", self)
        fade.setDuration(dur)
        fade.setEasingCurve(easing(curve))
        fade.setStartValue(self.windowOpacity())
        fade.setEndValue(START_OPACITY)
        fade.finished.connect(self._fade_out_done)  # bound method: no reference cycle
        self._anim = fade
        fade.start()

    def _fade_out_done(self) -> None:
        if not self._dismissing:
            return
        self._dismissing = False
        self.hide()
        self.setWindowOpacity(1.0)
        then, self._then = self._then, None
        if then is not None:
            then()

    def hide_now(self) -> None:
        self._stop_anim()
        self._dismissing = False
        self.hide()

    def reassert_topmost(self) -> None:
        """Some setups drop top-most after alt-tab. Cheap when hidden; raise when shown."""
        if self.isVisible():
            self.raise_()
        else:
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

    def _stop_anim(self) -> None:
        if self._anim is not None:
            self._anim.stop()
            self._anim = None
