from __future__ import annotations

import pytest

from smurfsniper.models.config import Anchor, Config, Placement
from smurfsniper.ui.overlay import ToastSpec, ToastStack
from smurfsniper.ui.tokens import TokenContext


@pytest.fixture
def stack(qtbot, no_anim):
    s = ToastStack(TokenContext(), Config().overlays.toasts.placement, max_visible=3, seconds=60)
    yield s
    s.clear()
    s.deleteLater()


def titles(stack: ToastStack) -> list[str]:
    return [x.spec.title for x in stack.visible_toasts()]


def test_newest_first_and_max_visible(stack):
    for i in range(5):
        stack.push(ToastSpec(f"t{i}"))
    assert titles(stack) == ["t4", "t3", "t2"]
    assert stack.isVisible()


def test_bottom_anchor_puts_newest_at_bottom(qtbot, no_anim):
    s = ToastStack(TokenContext(), Placement(anchor=Anchor.BOTTOM_RIGHT), seconds=60)
    s.push(ToastSpec("a"))
    s.push(ToastSpec("b"))
    assert titles(s) == ["a", "b"]
    s.clear()


def test_update_in_place_by_id_resets_timer(qtbot, stack):
    stack.push(ToastSpec("first", id="x", duration_ms=300))
    qtbot.wait(200)
    toast = stack.push(ToastSpec("second", "body", id="x", duration_ms=300))
    assert titles(stack) == ["second"]
    assert toast.texts()[:2] == ["second", "body"]
    qtbot.wait(200)  # 400 ms after the first push: still alive because the timer reset
    assert titles(stack) == ["second"]
    qtbot.waitUntil(lambda: not stack.toasts, timeout=2000)


def test_auto_dismiss_hides_window(qtbot, stack):
    stack.push(ToastSpec("bye", duration_ms=50))
    assert stack.isVisible()
    qtbot.waitUntil(lambda: not stack.toasts, timeout=2000)
    assert not stack.isVisible()


def test_auto_dismiss_with_animations(qtbot):
    s = ToastStack(TokenContext(), Config().overlays.toasts.placement, seconds=60)
    s.push(ToastSpec("anim", duration_ms=50))
    qtbot.waitUntil(lambda: not s.toasts, timeout=3000)
    qtbot.waitUntil(lambda: not s.isVisible(), timeout=3000)


def test_chip_and_body_rendered(stack):
    toast = stack.push(ToastSpec("Bob: likely smurf", "new account (9d)", "danger", chip="Ctrl+1"))
    assert toast.texts() == ["Bob: likely smurf", "new account (9d)", "Ctrl+1"]
