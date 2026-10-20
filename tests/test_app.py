"""SmurfSniperApp wiring with a fake keyboard and a mocked SC2 client (no live network)."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import httpx
import pytest
import yaml
from PySide6.QtWidgets import QApplication

from smurfsniper.app.application import SmurfSniperApp
from smurfsniper.app.hotkeys import HotkeyAction
from smurfsniper.models.config import Config

SC2 = "http://localhost:6119"


@pytest.fixture
def keyboard(monkeypatch):
    registered: dict[int, str] = {}
    counter = [0]

    def add_hotkey(binding, cb, **kw):
        counter[0] += 1
        registered[counter[0]] = binding
        return counter[0]

    fake = types.SimpleNamespace(
        parse_hotkey=lambda b: b,
        add_hotkey=add_hotkey,
        remove_hotkey=lambda h: registered.pop(h, None),
        registered=registered,
    )
    monkeypatch.setitem(sys.modules, "keyboard", fake)
    return fake


@pytest.fixture
def app(qtbot, tmp_dirs, pulse, fixture_json, keyboard, tmp_path):
    mock, _ = pulse
    mock.get(f"{SC2}/ui").mock(return_value=httpx.Response(200, json=fixture_json("ui_menu")))
    mock.get(f"{SC2}/game").mock(return_value=httpx.Response(200, json=fixture_json("game_menu")))
    a = SmurfSniperApp(Config(), tmp_dirs["config"] / "config.yaml")
    a.qapp = QApplication.instance()
    a._state = {"first_run_done": True, "picker_skipped": True}  # no balloons or dialogs
    a.start()
    yield a
    a.shutdown()


def test_start_builds_tray_hotkeys_and_service(app, keyboard):
    assert app.tray is not None and app.service is not None
    assert len(keyboard.registered) == 6
    labels = app.tray.menu_labels()
    assert labels[0].startswith("SmurfSniper ")
    for expected in ("Hotkeys…", "Settings…", "Change account…", "Pause lookups", "Sounds", "Quit"):
        assert expected in labels
    assert any(lb.startswith("Hide HUD") and "Ctrl+Shift+`" in lb for lb in labels)
    assert app.tray.hotkeys_action.text() == "Hotkeys…"


def test_tray_status_follows_game_state(app, qtbot):
    qtbot.waitUntil(lambda: app.tray.status_text == "In menus", timeout=5000)
    assert "In menus" in app.tray.icon.toolTip()


def test_hotkeys_route_to_service(app, monkeypatch):
    calls: list[str] = []
    svc = app.service
    monkeypatch.setattr(svc, "request_redetect", lambda: calls.append("redetect"))
    monkeypatch.setattr(svc, "toggle_opponent_card", lambda: calls.append("card"))
    monkeypatch.setattr(svc, "toggle_intel", lambda: calls.append("intel"))
    for action in (
        HotkeyAction.REDETECT,
        HotkeyAction.OPPONENT_CARD,
        HotkeyAction.INTEL,
        HotkeyAction.SESSION,  # later branches: logged, nothing else
        HotkeyAction.RIVALS,
    ):
        app._on_hotkey(action.value)
    assert calls == ["redetect", "card", "intel"]


def test_hide_all_hotkey_toggles_and_mirrors_in_tray(app):
    app._on_hotkey("hide_all")
    assert app.service.hud_hidden and app.tray.hide_action.isChecked()
    app._on_hotkey("hide_all")
    assert not app.service.hud_hidden and not app.tray.hide_action.isChecked()


def test_tray_hide_and_pause_and_sounds(app):
    app.tray.hide_action.setChecked(True)
    assert app.service.hud_hidden
    app.tray.pause_action.setChecked(True)
    assert app.service.paused and app.tray.status_text == "Paused"
    app.tray.pause_action.setChecked(False)
    app.tray.sounds_action.setChecked(False)
    assert app.config.advanced.sounds_enabled is False
    assert app.service.sounds.enabled is False
    assert app._dirty


def test_apply_config_rebinds_hotkeys_without_restart(app, keyboard):
    new = app.config.model_copy(deep=True)
    new.hotkeys.intel = "ctrl+shift+9"
    app.apply_config(new)
    assert "ctrl+shift+9" in keyboard.registered.values()
    assert "ctrl+shift+2" not in keyboard.registered.values()
    assert len(keyboard.registered) == 6
    assert app.config.hotkeys.intel == "ctrl+shift+9"


def test_apply_config_rebuilds_clients_for_a_new_key(app, qtbot):
    assert app.clients.aligulac is None
    old_cache = app.clients.cache
    new = app.config.model_copy(deep=True)
    new.integrations.aligulac_api_key = "k"  # type: ignore[assignment]
    app.apply_config(new)
    # debounced: typing a key does not rebuild the clients on every keystroke
    assert app.clients.aligulac is None and app._rebuild_timer.isActive()
    newer = app.config.model_copy(deep=True)
    newer.integrations.aligulac_api_key = "key"  # type: ignore[assignment]
    app.apply_config(newer)
    qtbot.waitUntil(lambda: app.clients.aligulac is not None, timeout=3000)
    assert app.service.clients is app.clients and app.service.pipeline.clients is app.clients
    assert app.clients.cache is old_cache  # responses stay cached across the rebuild


def test_apply_config_keeps_identity_and_emits_overlay_change(app, qtbot):
    app.config.account.name = "Hero"
    app.config.account.character_id = 9
    app.config.account.mmr_by_queue[201] = 4000
    stale = app.config.model_copy(deep=True)
    app.config.account.mmr_by_queue[201] = 4100  # refreshed after the copy was taken
    stale.overlays.opacity = 0.9
    stale.account.teammates = ["Mate"]
    with qtbot.waitSignal(app.bus.config_changed, timeout=1000):
        app.apply_config(stale)
    assert app.config.account.mmr_by_queue[201] == 4100  # not clobbered by the stale copy
    assert app.config.account.character_id == 9
    assert app.config.account.teammates == ["Mate"]
    assert app.config.overlays.opacity == 0.9


def test_settings_changes_are_saved_debounced(app, qtbot):
    path: Path = app.config_path
    assert not path.exists()
    new = app.config.model_copy(deep=True)
    new.overlays.scale = 1.25
    app.apply_config(new)
    qtbot.waitUntil(path.exists, timeout=3000)
    assert yaml.safe_load(path.read_text(encoding="utf-8"))["overlays"]["scale"] == 1.25


def test_shutdown_without_changes_writes_nothing(app):
    app.shutdown()
    assert not app.config_path.exists()


def test_settings_window_is_a_singleton_and_applies(app, qtbot):
    app.show_settings()
    first = app.settings
    qtbot.addWidget(first)
    app.show_settings("Hotkeys")
    assert app.settings is first and first.stack.currentIndex() == 2
    first.tab("Overlays").opacity.slider.setValue(80)
    assert app.config.overlays.opacity == 0.8


def test_cheatsheet_reflects_rebinding(app):
    app.show_cheatsheet()
    new = app.config.model_copy(deep=True)
    new.hotkeys.rivals = "ctrl+shift+8"
    app.apply_config(new)
    assert app.cheatsheet.chips[HotkeyAction.RIVALS].text() == "Ctrl+Shift+8"
    app.cheatsheet.close()


def test_single_instance_lock(tmp_dirs, qtbot):
    one = SmurfSniperApp(Config(), tmp_dirs["config"] / "c.yaml", headless=True)
    two = SmurfSniperApp(Config(), tmp_dirs["config"] / "c2.yaml", headless=True)
    assert one.acquire_lock() is True
    assert two.acquire_lock() is False
    one._lock.unlock()
    assert two.acquire_lock() is True
    two._lock.unlock()


def test_run_returns_1_when_already_running(tmp_dirs, qtbot):
    holder = SmurfSniperApp(Config(), tmp_dirs["config"] / "c.yaml", headless=True)
    assert holder.acquire_lock()
    second = SmurfSniperApp(Config(), tmp_dirs["config"] / "c2.yaml", headless=True)
    assert second.run() == 1
    holder._lock.unlock()


def test_account_picker_shown_on_first_run_only(qtbot, tmp_dirs, pulse, fixture_json, keyboard):
    mock, _ = pulse
    mock.get(f"{SC2}/ui").mock(return_value=httpx.Response(200, json=fixture_json("ui_menu")))
    mock.get(f"{SC2}/game").mock(return_value=httpx.Response(200, json=fixture_json("game_menu")))
    a = SmurfSniperApp(Config(), tmp_dirs["config"] / "config.yaml")
    a.qapp = QApplication.instance()
    a.start()
    try:
        qtbot.waitUntil(lambda: a.picker is not None, timeout=3000)
        assert a._state["first_run_done"] is True
        a.picker.close()
    finally:
        a.shutdown()
    # a configured account means no dialog next time
    cfg = Config()
    cfg.account.character_id = 1
    b = SmurfSniperApp(cfg, tmp_dirs["config"] / "config.yaml")
    b.qapp = QApplication.instance()
    b.start()
    try:
        qtbot.wait(200)
        assert b.picker is None
    finally:
        b.shutdown()


def test_balloon_click_runs_only_its_own_handler(app):
    assert app.tray is not None
    app._on_needs_picker(["hero", "rival"])
    app.tray.message("SmurfSniper", "plain notice")  # no click handler
    app.tray._message_clicked()
    assert app.picker is None
    app._on_needs_picker(["hero", "rival"])
    app.tray._message_clicked()
    assert app.picker is not None and app.picker.search.text() == "hero"
