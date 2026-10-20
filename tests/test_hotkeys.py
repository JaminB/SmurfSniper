from __future__ import annotations

import sys
import threading
import types

import pytest
from PySide6.QtCore import QThread
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication

from smurfsniper.app.hotkeys import (
    DEFAULT_BINDINGS,
    HotkeyAction,
    HotkeyManager,
    from_qkeysequence,
    normalize,
    to_display,
    validate_bindings,
)
from smurfsniper.models.config import HotkeyConfig


class FakeKeyboard(types.SimpleNamespace):
    def __init__(self, bad: set[str] | None = None):
        super().__init__()
        self.registered: dict[int, tuple[str, object, dict]] = {}
        self.removed: list[int] = []
        self.bad = bad or set()
        self._next = 0

    def parse_hotkey(self, binding: str):
        if binding in self.bad:
            raise ValueError(binding)
        return binding

    def add_hotkey(self, binding, callback, **kw):
        self._next += 1
        self.registered[self._next] = (binding, callback, kw)
        return self._next

    def remove_hotkey(self, handle):
        self.removed.append(handle)
        self.registered.pop(handle, None)

    def fire(self, binding: str) -> None:
        """Call the callback from a foreign thread, like the keyboard hook thread."""
        cb = next(c for b, c, _ in self.registered.values() if b == binding)
        t = threading.Thread(target=cb)
        t.start()
        t.join()


@pytest.fixture
def kb(monkeypatch: pytest.MonkeyPatch) -> FakeKeyboard:
    fake = FakeKeyboard()
    monkeypatch.setitem(sys.modules, "keyboard", fake)
    return fake


def issues_for(cfg: HotkeyConfig, level: str | None = None):
    return [i for i in validate_bindings(cfg) if level is None or i.level == level]


def test_defaults_are_valid(kb):
    assert issues_for(HotkeyConfig()) == []


def test_duplicate_is_an_error(kb):
    cfg = HotkeyConfig(intel="ctrl+shift+1")
    errs = issues_for(cfg, "error")
    assert [e.action for e in errs] == [HotkeyAction.INTEL]
    assert "Opponent card" in errs[0].message


def test_missing_modifier_is_an_error(kb):
    errs = issues_for(HotkeyConfig(redetect="r"), "error")
    assert errs and errs[0].action is HotkeyAction.REDETECT
    assert issues_for(HotkeyConfig(redetect="ctrl"), "error")


def test_unparsable_is_an_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "keyboard", FakeKeyboard(bad={"ctrl+shift+`"}))
    errs = issues_for(HotkeyConfig(), "error")
    assert [e.action for e in errs] == [HotkeyAction.HIDE_ALL]


def test_sc2_conflicts_warn(kb):
    warns = issues_for(HotkeyConfig(session="ctrl+f1", rivals="alt+3"), "warning")
    assert {w.action for w in warns} == {HotkeyAction.SESSION, HotkeyAction.RIVALS}
    assert issues_for(HotkeyConfig(session="ctrl+f1"), "error") == []


def test_to_display_and_normalize():
    assert to_display("ctrl+shift+`") == "Ctrl+Shift+`"
    assert to_display("shift+ctrl+r") == "Ctrl+Shift+R"
    assert to_display("alt+f5") == "Alt+F5"
    assert normalize("Shift+Control+1") == "ctrl+shift+1"


def test_from_qkeysequence():
    assert from_qkeysequence(QKeySequence("Ctrl+Shift+1")) == "ctrl+shift+1"
    assert from_qkeysequence(QKeySequence("Ctrl+Shift+`")) == "ctrl+shift+`"
    assert from_qkeysequence(QKeySequence("Alt+F5")) == "alt+f5"
    assert from_qkeysequence(QKeySequence("Ctrl+Shift+~")) == "ctrl+shift+`"
    assert from_qkeysequence(QKeySequence()) is None
    assert from_qkeysequence(QKeySequence("Ctrl")) is None


def test_start_registers_all_without_suppress(kb, qtbot):
    mgr = HotkeyManager(HotkeyConfig())
    assert mgr.start() == []
    assert {b for b, _, _ in kb.registered.values()} == set(DEFAULT_BINDINGS.values())
    assert all(
        kw == {"suppress": False, "trigger_on_release": False}
        for _, _, kw in kb.registered.values()
    )
    mgr.stop()
    assert not kb.registered


def test_triggered_is_delivered_on_main_thread(kb, qtbot):
    mgr = HotkeyManager(HotkeyConfig())
    mgr.start()
    seen: list[tuple[str, bool]] = []
    app = QApplication.instance()

    def slot(action: str) -> None:
        seen.append((action, QThread.currentThread() == app.thread()))

    mgr.triggered.connect(slot)
    kb.fire("ctrl+shift+2")
    qtbot.waitUntil(lambda: bool(seen), timeout=2000)
    assert seen == [("intel", True)]


def test_debounce(kb, qtbot):
    now = [100.0]
    mgr = HotkeyManager(HotkeyConfig(), clock=lambda: now[0])
    mgr.start()
    got: list[str] = []
    mgr.triggered.connect(got.append)
    kb.fire("ctrl+shift+1")
    now[0] += 0.1
    kb.fire("ctrl+shift+1")  # within 300 ms: dropped
    now[0] += 0.1
    kb.fire("ctrl+shift+2")  # a different action is independent
    now[0] += 0.5
    kb.fire("ctrl+shift+1")
    qtbot.waitUntil(lambda: len(got) == 3, timeout=2000)
    assert got == ["opponent_card", "intel", "opponent_card"]


def test_apply_rebinds_without_restart(kb):
    mgr = HotkeyManager(HotkeyConfig())
    mgr.start()
    new = HotkeyConfig(intel="ctrl+shift+9")
    assert mgr.apply(new) == []
    bindings = {b for b, _, _ in kb.registered.values()}
    assert "ctrl+shift+9" in bindings and "ctrl+shift+2" not in bindings
    assert len(kb.registered) == 6


def test_errors_are_not_registered(kb):
    mgr = HotkeyManager(HotkeyConfig(intel="ctrl+shift+1"))
    issues = mgr.start()
    assert [i.action for i in issues if i.level == "error"] == [HotkeyAction.INTEL]
    assert len(kb.registered) == 5


def test_suspend_and_resume(kb):
    mgr = HotkeyManager(HotkeyConfig())
    mgr.start()
    mgr.suspend()
    assert not kb.registered
    mgr.resume()
    assert len(kb.registered) == 6


def test_disabled_registers_nothing(kb):
    mgr = HotkeyManager(HotkeyConfig(enabled=False))
    assert mgr.start() == []
    assert not kb.registered


def test_unavailable_keyboard_reports_errors(monkeypatch):
    class Broken(types.SimpleNamespace):
        pass

    def boom(*_a, **_k):
        raise OSError("no hook")

    broken = Broken(add_hotkey=boom, remove_hotkey=boom, parse_hotkey=lambda b: b)
    monkeypatch.setitem(sys.modules, "keyboard", broken)
    mgr = HotkeyManager(HotkeyConfig())
    issues = mgr.start()
    assert mgr.unavailable
    assert issues and all(i.level == "error" for i in issues)
    assert "administrator" in issues[0].message
    # once the hook can be installed again, the warning clears
    monkeypatch.setitem(sys.modules, "keyboard", FakeKeyboard())
    assert not [i for i in mgr.apply(HotkeyConfig()) if i.level == "error"]
    assert not mgr.unavailable


def test_conflict_warning_text_names_control_groups_only_for_digits(kb):
    cfg = HotkeyConfig(session="ctrl+f1", rivals="alt+3")
    by = {i.action: i.message for i in issues_for(cfg, "warning")}
    assert "control groups" not in by[HotkeyAction.SESSION]
    assert "control groups" in by[HotkeyAction.RIVALS]
