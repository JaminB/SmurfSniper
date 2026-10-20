"""Every overlay window must be click-through and never take focus from SC2."""

from __future__ import annotations

from PySide6.QtCore import Qt

from smurfsniper.models.config import Config
from smurfsniper.ui.overlay import (
    HotkeyHint,
    OpponentCard,
    OverlayWindow,
    Panel,
    ToastStack,
)
from smurfsniper.ui.tokens import TokenContext


def all_subclasses(cls: type) -> set[type]:
    out: set[type] = set()
    for sub in cls.__subclasses__():
        out |= {sub, *all_subclasses(sub)}
    return out


def build(cls: type) -> OverlayWindow:
    tk, ov = TokenContext(), Config().overlays
    factories = {
        OpponentCard: lambda: OpponentCard(tk, ov.card.placement),
        ToastStack: lambda: ToastStack(tk, ov.toasts.placement),
        Panel: lambda: Panel("Title", "Ctrl+Shift+2", tk, ov.panels.placement),
        HotkeyHint: lambda: HotkeyHint(tk, ov.hint.placement),
    }
    assert cls in factories, f"add a factory for {cls.__name__}"
    return factories[cls]()


def test_every_overlay_window_is_click_through(qtbot):
    classes = all_subclasses(OverlayWindow)
    assert {OpponentCard, ToastStack, Panel, HotkeyHint} <= classes
    for cls in classes:
        w = build(cls)
        flags = w.windowFlags()
        assert flags & Qt.WindowType.WindowTransparentForInput, cls
        assert flags & Qt.WindowType.WindowDoesNotAcceptFocus, cls
        assert flags & Qt.WindowType.WindowStaysOnTopHint, cls
        assert flags & Qt.WindowType.Tool, cls
        assert w.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating), cls
        assert w.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents), cls
        assert w.focusPolicy() == Qt.FocusPolicy.NoFocus, cls
        w.reveal()
        assert not w.isActiveWindow(), cls
        w.reassert_topmost()
        w.hide_now()
        w.reassert_topmost()
        assert w.windowFlags() & Qt.WindowType.WindowTransparentForInput, cls
