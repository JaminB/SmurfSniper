"""Toasts: small, auto-dismissing notices stacked in one click-through window."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from PySide6.QtCore import QPropertyAnimation, Qt, QTimer, Signal
from PySide6.QtWidgets import QGraphicsOpacityEffect, QHBoxLayout, QVBoxLayout, QWidget

from smurfsniper.models.config import Anchor, Placement
from smurfsniper.ui import tokens as t
from smurfsniper.ui.overlay.base import OverlayWindow, Surface, animations_enabled, easing, qcolor
from smurfsniper.ui.overlay.widgets import Chip, Text, elide_lines
from smurfsniper.ui.tokens import TokenContext

Kind = Literal["info", "success", "warning", "danger", "win", "loss"]
KIND_ACCENT: dict[str, tuple[int, int, int]] = {
    "info": t.INFO,
    "success": t.POSITIVE,
    "warning": t.SMURF_BADGE["suspicious"][0],
    "danger": t.NEGATIVE,
    "win": t.POSITIVE,
    "loss": t.NEGATIVE,
}


@dataclass(frozen=True)
class ToastSpec:
    title: str
    body: str | None = None
    kind: Kind = "info"
    accent: tuple[int, int, int] | None = None  # overrides the kind accent (e.g. race)
    id: str | None = None  # same id -> update in place (text + timer reset)
    duration_ms: int | None = None  # None -> config.overlays.toasts.seconds
    chip: str | None = None  # optional hotkey chip, e.g. "Ctrl+Shift+2"


class Toast(Surface):
    """One toast card: title line (+ chip) and an optional 3-line body."""

    expired = Signal(object)  # self, when its timer runs out
    faded_out = Signal(object)  # self, when its fade-out finished

    def __init__(self, spec: ToastSpec, tokens: TokenContext, parent: QWidget | None = None):
        super().__init__(
            tokens, radius="toast", accent=qcolor(spec.accent or KIND_ACCENT[spec.kind])
        )
        self.spec = spec
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._expire)
        self.leaving = False
        self.lay = QVBoxLayout(self)
        self.setFixedWidth(tokens.px(t.SIZE["toast_w"]))
        self._build()

    def _build(self) -> None:
        tk = self.tokens
        v, h = (tk.px(x) for x in t.PADDING["toast"])
        bar = tk.px(t.ACCENT_BAR_WIDTH)
        self.lay.setContentsMargins(h + bar, v, h, v)
        self.lay.setSpacing(tk.px(t.SPACE["xxs"]))
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setSpacing(tk.px(t.GAP["inline"]))
        self.title = Text(self.spec.title, tk, role="body", weight=600, elide=True)
        head.addWidget(self.title, 1)
        self.chip = Chip(self.spec.chip, tk) if self.spec.chip else None
        if self.chip is not None:
            head.addWidget(self.chip, 0, Qt.AlignmentFlag.AlignVCenter)
        self.lay.addLayout(head)
        self.body = None
        if self.spec.body:
            inner = tk.px(t.SIZE["toast_w"]) - 2 * h - bar
            text = Text("", tk, role="caption", color=t.TEXT_SECONDARY, wrap=True)
            text.setText(elide_lines(self.spec.body, text.font(), inner, 3))
            self.body = text
            self.lay.addWidget(text)

    def _expire(self) -> None:
        self.expired.emit(self)

    def _faded(self) -> None:
        self.faded_out.emit(self)

    def _faded_in(self) -> None:
        if not self.leaving:
            self.restore_shadow()

    def texts(self) -> list[str]:
        out = [self.title.text()]
        if self.body is not None:
            out.append(self.body.text())
        if self.chip is not None:
            out.append(self.chip.text())
        return out


class ToastStack(OverlayWindow):
    """Single window holding a vertical stack of ``Toast`` widgets."""

    paints_surface = False

    def __init__(
        self,
        tokens: TokenContext,
        placement: Placement,
        *,
        max_visible: int = 4,
        seconds: float = 6.0,
        parent: QWidget | None = None,
    ):
        super().__init__(tokens, placement, parent=parent)
        self.max_visible = max_visible
        self.seconds = seconds
        self.toasts: list[Toast] = []
        self.body.setSpacing(tokens.px(t.GAP["toast_stack"]))

    # ------------------------------------------------------------------ api
    def push(self, spec: ToastSpec) -> Toast:
        """Show ``spec``; the newest toast sits at the anchor edge."""
        existing = next((x for x in self.toasts if spec.id and x.spec.id == spec.id), None)
        toast = Toast(spec, self.tokens)
        # A bound-method connection (no lambda capturing ``self``) avoids a Python
        # reference cycle that crashes when a stack is garbage-collected.
        toast.expired.connect(self.dismiss_toast)
        toast.faded_out.connect(self._remove)
        if existing is not None and not existing.leaving:
            # Same id: replace in place (new text, fresh timer), no re-entry animation.
            idx = self.toasts.index(existing)
            existing.timer.stop()
            self.body.insertWidget(self.body.indexOf(existing), toast)
            self.body.removeWidget(existing)
            existing.deleteLater()
            self.toasts[idx] = toast
            self._arm(toast)
            self._relayout()
            return toast
        if self._newest_first():
            self.toasts.insert(0, toast)
            self.body.insertWidget(0, toast)
        else:
            self.toasts.append(toast)
            self.body.addWidget(toast)
        self._arm(toast)
        live = [x for x in self.toasts if not x.leaving]
        while len(live) > max(1, self.max_visible):
            oldest = live[-1] if self._newest_first() else live[0]
            live.remove(oldest)
            self.dismiss_toast(oldest)
        if animations_enabled():
            self._fade(toast, 0.0, 1.0, t.ANIM["fade_in"])
        if self.shown:
            self._relayout()
        else:
            self.reveal()
        return toast

    def dismiss_toast(self, toast: Toast) -> None:
        if toast.leaving or toast not in self.toasts:
            return
        toast.leaving = True
        toast.timer.stop()
        if animations_enabled() and self.isVisible():
            anim = self._fade(toast, 1.0, 0.0, t.ANIM["fade_out"])
            anim.finished.connect(toast._faded)
        else:
            self._remove(toast)

    def clear(self) -> None:
        for toast in list(self.toasts):
            toast.timer.stop()
            self.body.removeWidget(toast)
            toast.deleteLater()
        self.toasts = []
        self.hide_now()

    def visible_toasts(self) -> list[Toast]:
        return [x for x in self.toasts if not x.leaving]

    def set_limits(self, *, max_visible: int, seconds: float) -> None:
        self.max_visible = max_visible
        self.seconds = seconds

    def set_tokens(self, tokens: TokenContext) -> None:
        specs = [x.spec for x in self.visible_toasts()]
        self.clear()
        self.tokens = tokens
        self.body.setSpacing(tokens.px(t.GAP["toast_stack"]))
        super().set_tokens(tokens)
        for spec in reversed(specs) if self._newest_first() else specs:
            self.push(spec)

    # ------------------------------------------------------------ internals
    def _newest_first(self) -> bool:
        return not Anchor(self.placement.anchor).value.startswith("bottom")

    def _arm(self, toast: Toast) -> None:
        ms = toast.spec.duration_ms
        if ms is None:
            ms = round(self.seconds * 1000)
        toast.timer.start(max(1, ms))

    def _remove(self, toast: Toast) -> None:
        if toast in self.toasts:
            self.toasts.remove(toast)
        self.body.removeWidget(toast)
        toast.deleteLater()
        if not self.toasts:
            self.dismiss()
        else:
            self._relayout()

    def _relayout(self) -> None:
        self.reposition()

    def _fade(self, toast: Toast, start: float, end: float, spec) -> QPropertyAnimation:
        """Fade a toast. Qt allows one effect per widget, so the drop shadow is swapped
        for an opacity effect during the fade and recreated after a fade-in."""
        holder = QGraphicsOpacityEffect(toast)
        holder.setOpacity(start)
        toast.setGraphicsEffect(holder)
        dur, curve = spec
        anim = QPropertyAnimation(holder, b"opacity", toast)
        anim.setDuration(dur)
        anim.setEasingCurve(easing(curve))
        anim.setStartValue(start)
        anim.setEndValue(end)
        if end >= 1.0:
            anim.finished.connect(toast._faded_in)
        anim.start()
        return anim
