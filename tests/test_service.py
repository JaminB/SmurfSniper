"""End-to-end: fake SC2 client + recorded SC2Pulse responses through the real Service."""

from __future__ import annotations

import httpx

from smurfsniper.api import transport as tr
from smurfsniper.api.registry import build_clients
from smurfsniper.core.events import EventBus
from smurfsniper.models.config import Config, Me, Preferences, Team
from smurfsniper.service import Service
from smurfsniper.sounds import SoundPlayer
from smurfsniper.storage.db import init_db
from smurfsniper.storage.player_log import PlayerLogStore

SC2 = "http://localhost:6119"


def test_full_game_flow(qtbot, tmp_path, fixture_json, pulse, monkeypatch):
    mock, _ = pulse

    def boom(path: str) -> None:
        raise AssertionError(f"network on GUI thread: {path}")

    monkeypatch.setattr(tr, "gui_thread_hook", boom)
    ui = mock.get(f"{SC2}/ui").mock(
        return_value=httpx.Response(200, json=fixture_json("ui_ingame"))
    )
    game = mock.get(f"{SC2}/game").mock(
        return_value=httpx.Response(200, json=fixture_json("game_1v1"))
    )
    cfg = Config(
        me=Me(mmr=7000, name="Me"),
        team=Team(name="", mmr=0, members=[]),
        preferences=Preferences.defaults(),
    )
    db = init_db(tmp_path / "db.sqlite3")
    store = PlayerLogStore(db)
    clients = build_clients(cfg, disk_cache=False)
    bus = EventBus()
    service = Service(cfg, clients, store, bus, hotkeys=False, sounds=SoundPlayer(enabled=False))
    service.renderer._show = False
    rendered: list[str] = []
    service.renderer.rendered.connect(lambda k, g: rendered.append(k))
    ended = []
    bus.game_ended.connect(ended.append)

    service.start()
    service.poller.ui_interval_ms = 50
    try:
        qtbot.waitUntil(lambda: "main" in rendered, timeout=8000)
        game.mock(return_value=httpx.Response(200, json=fixture_json("game_result")))
        qtbot.waitUntil(lambda: bool(ended), timeout=8000)
        qtbot.waitUntil(lambda: len(store.all_rows()) == 1, timeout=5000)
    finally:
        service.stop()
        db.close()
    row = store.all_rows()[0]
    assert row.name == "Serral#769" and row.my_result == "victory" and row.mode == "1v1"
    assert ui.call_count > 0


def test_hotkey_signals_handled_on_main_thread(qtbot, tmp_path, fixture_json, pulse):
    """Keyboard callbacks emit from the hook thread; handlers must run on the GUI thread."""
    import threading

    mock, _ = pulse
    mock.get(f"{SC2}/ui").mock(return_value=httpx.Response(200, json=fixture_json("ui_menu")))
    mock.get(f"{SC2}/game").mock(return_value=httpx.Response(200, json=fixture_json("game_menu")))
    cfg = Config(me=Me(mmr=7000, name="Me"), team=Team(name="", mmr=0, members=[]))
    db = init_db(tmp_path / "db.sqlite3")
    clients = build_clients(cfg, disk_cache=False)
    sounds = SoundPlayer(enabled=False)
    played: list[threading.Thread] = []
    sounds.play = lambda kind: played.append(threading.current_thread())
    service = Service(cfg, clients, PlayerLogStore(db), EventBus(), hotkeys=False, sounds=sounds)
    service.start()
    try:
        for sig in (service.redetect_requested, service.intel_requested):
            t = threading.Thread(target=sig.emit)
            t.start()
            t.join()
        qtbot.waitUntil(lambda: len(played) == 2, timeout=3000)
    finally:
        service.stop()
        db.close()
    assert all(t is threading.main_thread() for t in played)
