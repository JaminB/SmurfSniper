"""Session, rivals and intel panels: content, empty states and no placeholder strings."""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
import respx
from PySide6.QtWidgets import QLabel

from smurfsniper.analyze.history import Record
from smurfsniper.analyze.rivals import Rival, RivalsSummary
from smurfsniper.api.registry import build_clients
from smurfsniper.app.hotkeys import HotkeyAction
from smurfsniper.core.events import EventBus
from smurfsniper.core.lookup import LookupPipeline
from smurfsniper.core.rivals import RivalsCache
from smurfsniper.models.config import Config
from smurfsniper.ui import preview_data as pd
from smurfsniper.ui.hud import HudController
from smurfsniper.ui.overlay import Panel
from smurfsniper.ui.panels import rivals as rivals_panel
from smurfsniper.ui.panels import session as session_panel
from smurfsniper.ui.panels.intel import build_intel_body
from smurfsniper.ui.tokens import TokenContext

PLACEHOLDER = re.compile(r"\bNone\b|unknown|\(no data\)|insufficient|\(none\)|\b0-0\b", re.I)
TK = TokenContext()


def texts(widgets) -> list[str]:
    out: list[str] = []
    for w in widgets:
        out.extend(lbl.text() for lbl in w.findChildren(QLabel))
    return out


def assert_clean(widgets) -> None:
    for text in texts(widgets):
        assert not PLACEHOLDER.search(text), text
        assert text.strip(), "empty label"


# ------------------------------------------------------------------ session
def test_session_panel_content(qtbot):
    body = session_panel.build(pd.session_snapshot(), TK)
    qtbot.addWidget(body[0])
    joined = " ".join(texts(body))
    assert "+74 MMR" in joined and "4,152 → 4,226" in joined
    assert "vZ 3-2" in joined and "vT 2-1" in joined and "vP 2-0" in joined
    assert "played" in joined
    assert_clean(body)


def test_session_panel_empty_state_is_one_row(qtbot):
    body = session_panel.build(pd.session_snapshot(0), TK)
    qtbot.addWidget(body[0])
    assert texts(body) == [session_panel.EMPTY_TEXT]
    assert session_panel.build(None, TK)[0] is not None


def test_session_panel_hides_mmr_until_a_rating_is_known(qtbot):
    snap = pd.session_snapshot(3)
    snap = type(snap)(**{**snap.__dict__, "mmr_delta": None, "mmr_now": None, "mmr_points": ()})
    body = session_panel.build(snap, TK)
    qtbot.addWidget(body[0])
    joined = " ".join(texts(body))
    assert "MMR" not in joined and "→" not in joined
    assert re.search(r"\d+-\d+", joined)  # the record is still there
    assert_clean(body)


def test_session_panel_streak_only_from_two(qtbot):
    snap = pd.session_snapshot()
    assert snap.streak == ("W", 1)
    assert "streak" not in " ".join(texts(session_panel.build(snap, TK)))
    longer = type(snap)(**{**snap.__dict__, "streak": ("L", 3)})
    assert "streak L3" in " ".join(texts(session_panel.build(longer, TK)))


# ------------------------------------------------------------------- rivals
def test_rivals_panel_content(qtbot):
    body = rivals_panel.build(pd.rivals_summary(), TK, now=pd.NOW)
    for w in body:
        qtbot.addWidget(w)
    joined = " ".join(texts(body))
    assert "NEMESIS" in joined and "Bob (Z)" in joined and "2-6" in joined
    assert "VICTIM" in joined and "Alice (P)" in joined
    assert "8 games" in joined and "3d" in joined
    assert_clean(body)


def test_rivals_panel_empty_state_and_loading(qtbot):
    body = rivals_panel.build(RivalsSummary(), TK)
    qtbot.addWidget(body[0])
    assert texts(body) == [rivals_panel.EMPTY_TEXT]
    assert rivals_panel.build(None, TK) is None  # still loading


def test_rivals_panel_omits_missing_nemesis_and_victim(qtbot):
    carl = Rival("Carl", "EU", 3, 6, Record(3, 3), pd.NOW - timedelta(days=14), 4100, "TERRAN")
    body = rivals_panel.build(RivalsSummary(top=(carl,)), TK, now=pd.NOW)
    for w in body:
        qtbot.addWidget(w)
    joined = " ".join(texts(body))
    assert "NEMESIS" not in joined and "VICTIM" not in joined and "Carl" in joined
    assert len(body) == 1
    assert_clean(body)


# -------------------------------------------------------------------- intel
def test_intel_panel_shows_tendencies_and_every_smurf_reason(qtbot):
    prof = pd.smurf_profile()
    body = build_intel_body([prof], TK)
    qtbot.addWidget(body[0])
    joined = " ".join(texts(body))
    for key in ("FORM", "VS", "MAPS", "LENGTH", "TIME", "RACE", "SMURF"):
        assert key in joined, key
    assert "vZ 11-3 · vT 4-4 · vP 6-1" in joined
    assert "Usually plays 20:00–23:00" in joined and "Off-race: 4 of last 25" in joined
    assert "62% of wins < 6 min" in joined
    for reason in prof.smurf.assessment.reasons:  # all of them, not just the card's two
        assert reason.text in joined
    assert_clean(body)


def test_intel_panel_omits_rows_without_data(qtbot):
    prof = pd.smurf_profile()
    from dataclasses import replace

    from smurfsniper.core.profile import TendenciesInfo

    thin = replace(
        prof.tendencies.data,
        vs_race={},
        maps={},
        avg_duration_s=None,
        short_win_rate=None,
        peak_hours=None,
        race_switches=0,
        form=("W", "L", "W"),
    )
    prof.tendencies = TendenciesInfo(thin)
    prof.smurf = None
    body = build_intel_body([prof], TK)
    qtbot.addWidget(body[0])
    joined = " ".join(texts(body))
    assert "FORM" in joined
    for key in ("VS", "MAPS", "LENGTH", "TIME", "RACE", "SMURF"):
        assert key not in joined.split(), key
    assert_clean(body)


# ------------------------------------------------------- hotkeys, no network
@pytest.fixture
def hud_env(qtbot, no_anim):
    cfg = Config()
    with respx.mock(assert_all_called=False) as router:
        clients = build_clients(cfg, disk_cache=False)
        pipeline = LookupPipeline(
            clients, None, my_mmr=lambda: 4000, my_region=lambda: "EU", mmr_window=lambda: 500
        )
        bus = EventBus()
        hud = HudController(bus, pipeline, cfg)
        cache = RivalsCache(None, bus, executor=None)
        snapshots = {"snap": pd.session_snapshot()}
        hud.register_panel(
            HotkeyAction.SESSION,
            "Session",
            lambda: session_panel.build(snapshots["snap"], hud.tokens),
        )
        hud.register_panel(
            HotkeyAction.RIVALS,
            "Rivals",
            lambda: rivals_panel.build(cache.summary(), hud.tokens, now=pd.NOW),
            ensure=cache.refresh,
        )
        yield hud, cache, snapshots
        hud.set_hidden(True)
        pipeline.shutdown()
        clients.close()
        cache.shutdown()
    assert router.calls.call_count == 0, "panels must not touch the network"


def test_session_hotkey_toggles_the_panel(hud_env):
    hud, _cache, _ = hud_env
    hud.on_hotkey(HotkeyAction.SESSION.value)
    panel = hud.panels.current(HotkeyAction.SESSION.value)
    assert isinstance(panel, Panel) and panel.chip.text().startswith("Ctrl+Shift+3")
    assert "+74 MMR" in " ".join(panel.texts())
    hud.on_hotkey(HotkeyAction.SESSION.value)
    assert hud.panels.current() is None


def test_rivals_hotkey_loads_locally_then_fills_in(qtbot, hud_env):
    hud, cache, _ = hud_env
    cache.ready.connect(lambda _s: hud.refresh_panel(HotkeyAction.RIVALS))
    hud.on_hotkey(HotkeyAction.RIVALS.value)
    panel = hud.panels.current(HotkeyAction.RIVALS.value)
    assert panel is not None
    qtbot.waitUntil(lambda: cache.summary() is not None, timeout=3000)
    qtbot.waitUntil(lambda: not panel.loading, timeout=3000)
    assert rivals_panel.EMPTY_TEXT in " ".join(panel.texts())  # no store: nothing to show
    hud.on_hotkey(HotkeyAction.SESSION.value)  # another panel's hotkey swaps it
    assert hud.panels.current(HotkeyAction.SESSION.value) is not None
    assert hud.panels.current(HotkeyAction.RIVALS.value) is None


def test_session_panel_updates_in_place_when_the_snapshot_changes(hud_env):
    hud, _cache, snapshots = hud_env
    hud.on_hotkey(HotkeyAction.SESSION.value)
    panel = hud.panels.current(HotkeyAction.SESSION.value)
    assert "+74 MMR" in " ".join(panel.texts())
    snapshots["snap"] = pd.session_snapshot(0)
    hud.refresh_panel(HotkeyAction.SESSION)
    assert " ".join(panel.texts()).count(session_panel.EMPTY_TEXT) == 1
