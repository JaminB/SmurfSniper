from __future__ import annotations

import sys
import threading
import types
from datetime import UTC, datetime, timedelta

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QLabel, QPushButton

from smurfsniper.app.hotkeys import HotkeyAction
from smurfsniper.core.account import AccountCandidate
from smurfsniper.models.config import Anchor, Config
from smurfsniper.ui.account_picker import EMPTY_TEXT, AccountPickerDialog
from smurfsniper.ui.cheatsheet import FOOTER, HotkeyCheatSheet
from smurfsniper.ui.settings import SettingsHooks, SettingsWindow
from smurfsniper.ui.settings.tab_integrations import CREDITS, SC2PULSE_CREDIT

PLACEHOLDER_WORDS = ("(no data)", "(insufficient data)", "unknown", "None", "(none)", "0-0")


@pytest.fixture(autouse=True)
def fake_keyboard(monkeypatch):
    fake = types.SimpleNamespace(parse_hotkey=lambda b: b)
    monkeypatch.setitem(sys.modules, "keyboard", fake)
    return fake


@pytest.fixture
def hooks():
    calls: list[str] = []
    h = SettingsHooks(
        suspend_hotkeys=lambda: calls.append("suspend"),
        resume_hotkeys=lambda: calls.append("resume"),
        refresh_mmr=lambda: calls.append("refresh"),
        change_account=lambda: calls.append("change"),
        cache_stats=lambda: (12, 4096),
        clear_cache=lambda: calls.append("clear"),
        test_aligulac=lambda key: key == "good",
        version="9.9.9",
    )
    h.calls = calls
    return h


@pytest.fixture
def win(qtbot, hooks):
    cfg = Config()
    cfg.account.name = "Hero"
    cfg.account.character_id = 7
    cfg.account.mmr_by_queue[201] = 4200
    w = SettingsWindow(cfg, hooks)
    qtbot.addWidget(w)
    w.show()
    return w


def test_window_opens_with_every_tab(win):
    assert (win.width(), win.height()) == (720, 560)
    assert (win.minimumWidth(), win.minimumHeight()) == (640, 480)
    assert win.nav.count() == 5
    assert [win.nav.item(i).text() for i in range(5)] == [
        "Account",
        "Overlays",
        "Hotkeys",
        "Integrations",
        "Advanced",
    ]
    assert win.nav.width() == 160
    for name in ("Account", "Overlays", "Hotkeys", "Integrations", "Advanced"):
        win.show_tab(name)
        assert win.stack.currentIndex() == win.tabs.index(win.tab(name))


def test_no_placeholder_text_in_any_tab(win):
    for tab in win.tabs:
        for lb in tab.findChildren(QLabel):
            for bad in PLACEHOLDER_WORDS:
                assert bad not in lb.text(), (tab.title, lb.text())


def test_opacity_slider_emits_changed_with_new_value(win, qtbot):
    tab = win.tab("Overlays")
    with qtbot.waitSignal(win.changed, timeout=1000) as sig:
        tab.opacity.slider.setValue(85)
    assert sig.args[0].overlays.opacity == 0.85
    with qtbot.waitSignal(win.changed, timeout=1000) as sig:
        tab.scale.slider.setValue(120)
    assert sig.args[0].overlays.scale == 1.2
    assert tab.opacity.value_label.text() == "85%"


def test_slider_snaps_to_steps(win):
    tab = win.tab("Overlays")
    tab.opacity.slider.setValue(73)
    assert tab.opacity.value() % 5 == 0


def test_anchor_grid_click_and_offsets(win, qtbot):
    tab = win.tab("Overlays")
    grid = tab.toast_row.grid
    target = grid._cell(Anchor.BOTTOM_LEFT).center().toPoint()
    with qtbot.waitSignal(win.changed, timeout=1000) as sig:
        qtbot.mouseClick(grid, Qt.MouseButton.LeftButton, pos=QPoint(target))
    assert sig.args[0].overlays.toasts.placement.anchor is Anchor.BOTTOM_LEFT
    with qtbot.waitSignal(win.changed, timeout=1000) as sig:
        tab.card_row.off_x.setValue(-40)
    assert sig.args[0].overlays.card.placement.offset_x == -40
    with qtbot.waitSignal(win.changed, timeout=1000) as sig:
        tab.card_row.enabled.setChecked(False)
    assert sig.args[0].overlays.card.enabled is False


def test_changed_emits_independent_copies(win, qtbot):
    tab = win.tab("Overlays")
    with qtbot.waitSignal(win.changed) as a:
        tab.opacity.slider.setValue(60)
    first = a.args[0]
    tab.opacity.slider.setValue(90)
    assert first.overlays.opacity == 0.6


def test_recording_a_hotkey_updates_config(win, qtbot, hooks):
    tab = win.tab("Hotkeys")
    row = tab.rows[HotkeyAction.INTEL]
    row.start_recording()
    assert hooks.calls[-1] == "suspend" and row.recording
    with qtbot.waitSignal(win.changed, timeout=1000) as sig:
        row.edit.setKeySequence(QKeySequence("Ctrl+Shift+5"))
    assert sig.args[0].hotkeys.intel == "ctrl+shift+5"
    assert hooks.calls[-1] == "resume" and not row.recording
    assert row.chip.text() == "Ctrl+Shift+5"


def test_duplicate_binding_is_refused_with_inline_error(win, qtbot):
    tab = win.tab("Hotkeys")
    row = tab.rows[HotkeyAction.INTEL]
    row.start_recording()
    with qtbot.assertNotEmitted(win.changed):
        row.edit.setKeySequence(QKeySequence("Ctrl+Shift+1"))
    assert win.config.hotkeys.intel == "ctrl+shift+2"
    assert not row.message.isHidden() and "Opponent card" in row.message.text()
    assert row.message.property("role") == "error"


def test_conflicting_binding_warns_but_applies(win, qtbot):
    tab = win.tab("Hotkeys")
    with qtbot.waitSignal(win.changed, timeout=1000):
        assert tab.set_binding(HotkeyAction.RIVALS, "alt+3")
    row = tab.rows[HotkeyAction.RIVALS]
    assert not row.message.isHidden() and row.message.property("role") == "warning"


def test_escape_cancels_recording(win, qtbot, hooks):
    tab = win.tab("Hotkeys")
    row = tab.rows[HotkeyAction.REDETECT]
    row.start_recording()
    with qtbot.assertNotEmitted(win.changed):
        qtbot.keyClick(row.edit, Qt.Key.Key_Escape)
    assert not row.recording and hooks.calls[-1] == "resume"
    assert win.config.hotkeys.redetect == "ctrl+shift+r"


def test_reset_one_binding_and_master_toggle(win, qtbot):
    tab = win.tab("Hotkeys")
    tab.set_binding(HotkeyAction.SESSION, "ctrl+shift+8")
    with qtbot.waitSignal(win.changed):
        tab.rows[HotkeyAction.SESSION].reset_btn.click()
    assert win.config.hotkeys.session == "ctrl+shift+3"
    with qtbot.waitSignal(win.changed) as sig:
        tab.enabled.setChecked(False)
    assert sig.args[0].hotkeys.enabled is False


def test_reset_tab_to_defaults(win, qtbot):
    win.tab("Overlays").opacity.slider.setValue(50)
    win.show_tab("Overlays")
    with qtbot.waitSignal(win.changed):
        win.reset_btn.click()
    assert win.config.overlays.opacity == 0.7
    assert win.tab("Overlays").opacity.value() == 70


def test_account_tab(win, qtbot, hooks):
    tab = win.tab("Account")
    assert tab.name_label.text() == "Hero"
    assert "4,200 MMR" in tab.detail_label.text()
    tab.change_btn.click()
    tab.refresh_btn.click()
    assert hooks.calls[-2:] == ["change", "refresh"]
    tab.teammates.edit.setText("Buddy")
    with qtbot.waitSignal(win.changed) as sig:
        tab.teammates.edit.returnPressed.emit()
    assert sig.args[0].account.teammates == ["Buddy"]
    with qtbot.waitSignal(win.changed) as sig:
        tab.override_box.setChecked(True)
    assert sig.args[0].account.mmr_override == tab.override_spin.value()
    with qtbot.waitSignal(win.changed) as sig:
        tab.override_spin.setValue(4321)
    assert sig.args[0].account.mmr_override == 4321
    with qtbot.waitSignal(win.changed) as sig:
        tab.auto.setChecked(False)
    assert sig.args[0].account.auto_detect is False


def test_account_tab_empty_state_hides_missing_data(qtbot, hooks):
    w = SettingsWindow(Config(), hooks)
    qtbot.addWidget(w)
    tab = w.tab("Account")
    assert tab.name_label.text() == "No account selected yet"
    assert not tab.refresh_btn.isEnabled()
    assert not any(bad in tab.detail_label.text() for bad in PLACEHOLDER_WORDS)


def test_account_summary_shows_age():
    from smurfsniper.ui.settings.tab_account import AccountTab

    cfg = Config()
    cfg.account.name = "Hero"
    cfg.account.region = "EU"
    cfg.account.mmr_by_queue[201] = 4210
    cfg.account.mmr_updated_at = datetime(2026, 10, 19, 12, tzinfo=UTC)
    tab = AccountTab(cfg, SettingsHooks())
    now = datetime(2026, 10, 19, 12, tzinfo=UTC) + timedelta(minutes=3)
    assert tab.summary(now) == ("Hero", "EU  ·  4,210 MMR  ·  updated 3m ago")


def test_integrations_tab(win, qtbot):
    tab = win.tab("Integrations")
    texts = [lb.text() for lb in tab.findChildren(QLabel)]
    assert SC2PULSE_CREDIT in texts and CREDITS[0] == SC2PULSE_CREDIT
    assert "Data: SC2Pulse (sc2pulse.nephest.com), non-commercial use" in texts
    with qtbot.waitSignal(win.changed) as sig:
        tab.key_edit.setText("good")
    assert sig.args[0].aligulac_key == "good"
    tab.test_btn.click()
    qtbot.waitUntil(lambda: tab.test_result.text() == "✓ Valid", timeout=2000)
    tab.key_edit.setText("bad")
    tab.test_btn.click()
    qtbot.waitUntil(lambda: tab.test_result.text() == "✕ Invalid key", timeout=2000)
    with qtbot.waitSignal(win.changed) as sig:
        tab.lp_toggle.setChecked(False)
    assert sig.args[0].integrations.liquipedia_enabled is False
    assert not tab.contact.isEnabled()
    # the key is hidden until the eye is toggled
    assert tab.key_edit.echoMode().name == "Password"
    tab.eye.setChecked(True)
    assert tab.key_edit.echoMode().name == "Normal"


def test_integrations_test_runs_off_the_gui_thread(qtbot):
    seen: list[threading.Thread] = []

    def tester(key: str) -> bool:
        seen.append(threading.current_thread())
        return True

    w = SettingsWindow(Config(), SettingsHooks(test_aligulac=tester))
    qtbot.addWidget(w)
    tab = w.tab("Integrations")
    tab.key_edit.setText("k")
    tab.test_btn.click()
    qtbot.waitUntil(lambda: bool(seen), timeout=2000)
    assert seen[0] is not threading.main_thread()


def test_advanced_tab(win, qtbot, hooks):
    tab = win.tab("Advanced")
    assert tab.cache_label.text() == "Cache: 12 entries · 4 KB"
    tab.clear_btn.click()
    assert hooks.calls[-1] == "clear"
    tab.url.setText("http://localhost:6119/game/")
    with qtbot.waitSignal(win.changed) as sig:
        tab.url.editingFinished.emit()
    assert sig.args[0].advanced.sc2_client_url == "http://localhost:6119"
    with qtbot.waitSignal(win.changed) as sig:
        tab.level.setCurrentText("DEBUG")
    assert sig.args[0].advanced.log_level == "DEBUG"
    with qtbot.waitSignal(win.changed) as sig:
        tab.window.setValue(750)
    assert sig.args[0].advanced.mmr_window == 750


def test_set_config_refreshes_pages_without_emitting(win, qtbot):
    cfg = Config()
    cfg.overlays.opacity = 0.9
    cfg.account.name = "Other"
    with qtbot.assertNotEmitted(win.changed):
        win.set_config(cfg)
    assert win.tab("Overlays").opacity.value() == 90
    assert win.tab("Account").name_label.text() == "Other"


# ------------------------------------------------------------- picker/cheatsheet
def make_candidate(name: str, region: str, mmr: int | None, hours: int | None, race="ZERG"):
    from smurfsniper.api.sc2pulse.models import Character

    ch = Character(
        id=abs(hash(name)) % 10_000,
        account_id=1,
        region=region,
        realm=1,
        battlenet_id=1,
        name=name,
        discriminator=1,
    )
    last = datetime.now(UTC) - timedelta(hours=hours) if hours is not None else None
    return AccountCandidate(ch, region, mmr, 4, 50, last, None, 1, race)


def test_picker_debounces_search_and_picks(qtbot):
    d = AccountPickerDialog()
    qtbot.addWidget(d)
    queries: list[str] = []
    d.search_requested.connect(queries.append)
    d.search.setText("Her")
    d.search.setText("Hero#123")
    qtbot.wait(100)
    assert queries == []  # still inside the 400 ms debounce
    qtbot.waitUntil(lambda: queries == ["Hero"], timeout=2000)

    cands = [make_candidate("Hero#1", "EU", 4210, 2), make_candidate("Hero#2", "US", None, None)]
    d.set_results("Hero", cands)
    assert d.results.count() == 2 and d.use_btn.isEnabled()
    assert d.status.isHidden()
    with qtbot.waitSignal(d.chosen) as sig:
        d.use_btn.click()
    assert sig.args[0] is cands[0]


def test_picker_ignores_stale_results_and_shows_empty_state(qtbot):
    d = AccountPickerDialog("Zed")
    qtbot.addWidget(d)
    d._timer.stop()
    d.set_results("Other", [make_candidate("Other#1", "EU", 1, 1)])
    assert d.results.count() == 0
    d.set_results("Zed", [])
    assert d.status.text() == EMPTY_TEXT and not d.use_btn.isEnabled()
    assert "no #1234" in EMPTY_TEXT


def test_picker_detect_automatically_and_cancel(qtbot):
    d = AccountPickerDialog()
    qtbot.addWidget(d)
    with qtbot.waitSignal(d.detect_requested):
        d.auto_btn.click()
    d2 = AccountPickerDialog()
    qtbot.addWidget(d2)
    d2.show()
    d2.cancel_btn.click()
    assert not d2.isVisible()


def test_picker_is_not_click_through(qtbot):
    d = AccountPickerDialog()
    qtbot.addWidget(d)
    assert not d.windowFlags() & Qt.WindowType.WindowTransparentForInput


def test_cheatsheet_lists_all_hotkeys_and_closes_on_escape(qtbot):
    cfg = Config()
    sheet = HotkeyCheatSheet(cfg.hotkeys)
    qtbot.addWidget(sheet)
    sheet.show()
    chips = {a: c.text() for a, c in sheet.chips.items()}
    assert chips[HotkeyAction.OPPONENT_CARD] == "Ctrl+Shift+1"
    assert chips[HotkeyAction.HIDE_ALL] == "Ctrl+Shift+`"
    assert len(chips) == 6
    assert sheet.disabled_note.isHidden()
    texts = [lb.text() for lb in sheet.findChildren(QLabel)]
    assert FOOTER in texts
    qtbot.keyClick(sheet, Qt.Key.Key_Escape)
    assert not sheet.isVisible()


def test_cheatsheet_edit_button_and_rebinding(qtbot):
    cfg = Config()
    sheet = HotkeyCheatSheet(cfg.hotkeys)
    qtbot.addWidget(sheet)
    sheet.show()
    cfg.hotkeys.intel = "ctrl+shift+9"
    cfg.hotkeys.enabled = False
    sheet.set_hotkeys(cfg.hotkeys)
    assert sheet.chips[HotkeyAction.INTEL].text() == "Ctrl+Shift+9"
    assert not sheet.disabled_note.isHidden()
    edit = next(b for b in sheet.findChildren(QPushButton) if b.text().startswith("Edit hotkeys"))
    with qtbot.waitSignal(sheet.edit_requested):
        edit.click()
