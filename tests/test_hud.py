"""HudController driven by synthetic bus events (no network: any request fails the test)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import respx

from smurfsniper.api.registry import build_clients
from smurfsniper.api.sc2client.models import GamePlayer
from smurfsniper.app.hotkeys import HotkeyAction
from smurfsniper.core.events import EventBus
from smurfsniper.core.game_state import GameContext, GameResult, GameState
from smurfsniper.core.lookup import LookupPipeline
from smurfsniper.core.profile import LookupUpdate, Stage
from smurfsniper.models.config import Config
from smurfsniper.ui import preview_data as pd
from smurfsniper.ui.hud import HudController
from smurfsniper.ui.overlay import ToastSpec
from smurfsniper.ui.overlay.widgets import Skeleton

T0 = datetime(2026, 10, 19, 20, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = T0

    def __call__(self) -> datetime:
        return self.now


def ctx(game_id: int = 1, opponents=(("xXbarcodeXx", "Zerg"),), mode="1v1") -> GameContext:
    me = GamePlayer(id=1, name="Me", race="Zerg")
    opps = tuple(GamePlayer(id=i + 2, name=n, race=r) for i, (n, r) in enumerate(opponents))
    return GameContext(game_id, T0, (me, *opps), me, (), opps, mode, False)


@pytest.fixture
def env(qtbot, no_anim):
    """(hud, bus, pipeline, router, clock). The router has no routes: any call is a failure."""
    cfg = Config()
    with respx.mock(assert_all_called=False) as router:
        clients = build_clients(cfg, disk_cache=False)
        pipeline = LookupPipeline(
            clients, None, my_mmr=lambda: 4000, my_region=lambda: "EU", mmr_window=lambda: 500
        )
        bus = EventBus()
        clock = Clock()
        chimes: list[str] = []
        hud = HudController(bus, pipeline, cfg, now=clock, chime=chimes.append)
        hud.chimes = chimes  # type: ignore[attr-defined]
        yield hud, bus, pipeline, router, clock
        hud.reset_for_new_game()
        pipeline.shutdown()
        clients.close()
    assert router.calls.call_count == 0, "HUD made a network call"


def start(hud, bus, c: GameContext | None = None) -> GameContext:
    c = c or ctx()
    bus.state_changed.emit(GameState.IN_GAME)
    bus.game_started.emit(c)
    return c


def feed(hud, game_id: int, slot: int, prof, *, upto: Stage | None = None) -> None:
    for u in pd.updates_for(game_id, slot, prof):
        hud.on_update(u)
        if u.stage is upto:
            break


def toast_titles(hud) -> list[str]:
    return [t.spec.title for t in hud.toasts.visible_toasts()]


def test_card_reveals_on_game_update_and_grows(env):
    hud, bus, *_ = env
    start(hud, bus)
    assert not hud.card.isVisible()
    hud.on_update(LookupUpdate(1, 0, Stage.GAME, hud.profiles[0].seed))
    assert hud.card.shown and hud.card.row_count() == 1
    feed(hud, 1, 0, pd.smurf_profile())
    assert hud.card.row_count() == 6
    assert hud.hint.isVisible()


def test_replay_gives_no_card(env):
    hud, bus, *_ = env
    bus.state_changed.emit(GameState.REPLAY)
    hud.on_game_started(ctx())
    feed(hud, 1, 0, pd.smurf_profile())
    assert not hud.card.isVisible()
    assert not hud.hint.isVisible()
    hud.on_toast(ToastSpec("suppressed in replays"))
    assert toast_titles(hud) == []


def test_replay_shows_card_when_enabled(env):
    hud, bus, *_ = env
    hud.config.overlays.show_in_replays = True
    bus.state_changed.emit(GameState.REPLAY)
    hud.on_game_started(ctx())
    feed(hud, 1, 0, pd.smurf_profile(), upto=Stage.GAME)
    assert hud.card.shown


def test_menu_dismisses_card(env):
    hud, bus, *_ = env
    start(hud, bus)
    feed(hud, 1, 0, pd.smurf_profile())
    assert hud.card.shown
    bus.state_changed.emit(GameState.MENU)
    assert not hud.card.isVisible() and not hud.hint.isVisible()


def test_hide_all_hides_everything_and_next_game_resets(env):
    hud, bus, *_ = env
    seen: list[bool] = []
    hud.hidden_changed.connect(seen.append)
    start(hud, bus)
    feed(hud, 1, 0, pd.smurf_profile())
    hud.on_toast(ToastSpec("hello"))
    hud.on_hotkey(HotkeyAction.INTEL.value)
    assert hud.panels.current() is not None
    hud.on_hotkey(HotkeyAction.HIDE_ALL.value)
    assert hud.hud_hidden and seen == [True]
    assert not hud.card.isVisible() and not hud.hint.isVisible()
    assert hud.panels.current() is None and not hud.toasts.isVisible()
    hud.on_toast(ToastSpec("dropped while hidden"))
    assert toast_titles(hud) == []
    start(hud, bus, ctx(2))
    assert not hud.hud_hidden and seen == [True, False]
    hud.on_update(LookupUpdate(2, 0, Stage.GAME, hud.profiles[0].seed))
    assert hud.card.shown


def test_card_hotkey_clears_hide_all(env):
    hud, bus, *_ = env
    start(hud, bus)
    feed(hud, 1, 0, pd.smurf_profile())
    hud.set_hidden(True)
    hud.on_hotkey(HotkeyAction.OPPONENT_CARD.value)
    assert not hud.hud_hidden and hud.card.shown


def test_card_hotkey_after_auto_hide_reshows_from_cache(env, qtbot):
    hud, bus, pipeline, router, _ = env
    hud.config.overlays.card.auto_hide_seconds = 1
    start(hud, bus)
    feed(hud, 1, 0, pd.smurf_profile())
    rows = hud.card.row_count()
    qtbot.waitUntil(lambda: not hud.card.isVisible(), timeout=3000)
    hud.on_hotkey(HotkeyAction.OPPONENT_CARD.value)
    assert hud.card.shown and hud.card.row_count() == rows
    hud.on_hotkey(HotkeyAction.OPPONENT_CARD.value)
    assert not hud.card.isVisible()
    assert router.calls.call_count == 0


def test_auto_hide_counts_from_last_row_change(env, qtbot):
    hud, bus, *_ = env
    hud.config.overlays.card.auto_hide_seconds = 1
    start(hud, bus)
    prof = pd.smurf_profile()
    feed(hud, 1, 0, prof, upto=Stage.RATING)
    qtbot.wait(700)
    hud.on_update(LookupUpdate(1, 0, Stage.SMURF, prof.smurf))
    qtbot.wait(600)  # 1.3 s after reveal, 0.6 s after the last change
    assert hud.card.shown
    qtbot.waitUntil(lambda: not hud.card.isVisible(), timeout=3000)


def test_card_hotkey_without_game_toasts(env):
    hud, *_ = env
    hud.on_hotkey(HotkeyAction.OPPONENT_CARD.value)
    assert toast_titles(hud) == ["No opponent yet"]
    assert hud.toasts.visible_toasts()[0].spec.chip == "Ctrl+Shift+1"


def test_last_game_card_reachable_for_ten_minutes(env):
    hud, bus, _p, _r, clock = env
    c = start(hud, bus)
    feed(hud, 1, 0, pd.smurf_profile())
    bus.game_ended.emit(GameResult(c, "victory", 600.0))
    bus.state_changed.emit(GameState.MENU)
    assert not hud.card.isVisible()
    clock.now = T0 + timedelta(minutes=9)
    hud.on_hotkey(HotkeyAction.OPPONENT_CARD.value)
    assert hud.card.shown
    hud.on_hotkey(HotkeyAction.OPPONENT_CARD.value)
    clock.now = T0 + timedelta(minutes=11)
    hud.on_hotkey(HotkeyAction.OPPONENT_CARD.value)
    assert not hud.card.isVisible()
    assert "No opponent yet" in toast_titles(hud)


def test_stale_game_update_is_ignored(env):
    hud, bus, *_ = env
    start(hud, bus, ctx(1))
    start(hud, bus, ctx(2, opponents=(("Bob", "Terr"),)))
    hud.on_update(LookupUpdate(1, 0, Stage.GAME, pd.smurf_profile().seed))
    assert hud.dropped == 1
    assert hud.card.texts() == ["Bob"]
    assert not hud.card.isVisible()


def test_likely_smurf_toasts_when_card_dismissed_and_chimes(env):
    hud, bus, *_ = env
    hud.config.overlays.card.enabled = False  # card never auto-shows
    start(hud, bus)
    feed(hud, 1, 0, pd.smurf_profile())
    assert toast_titles(hud) == ["xXbarcodeXx: likely smurf"]
    toast = hud.toasts.visible_toasts()[0]
    assert toast.spec.kind == "danger" and toast.spec.chip == "Ctrl+Shift+1"
    assert hud.chimes == ["two"]


def test_likely_smurf_no_toast_when_card_visible(env):
    hud, bus, *_ = env
    start(hud, bus)
    feed(hud, 1, 0, pd.smurf_profile())
    assert toast_titles(hud) == []
    assert hud.chimes == ["two"]


def test_pulse_down_toast_once_per_game(env):
    hud, bus, *_ = env
    start(hud, bus, ctx(1, opponents=(("A", "Zerg"), ("B", "Terr")), mode="2v2"))
    hud.on_update(LookupUpdate(1, 0, Stage.IDENTITY, None, error="Unavailable"))
    hud.on_update(LookupUpdate(1, 1, Stage.IDENTITY, None, error="Unavailable"))
    assert toast_titles(hud) == ["SC2Pulse unreachable"]


def test_intel_hotkey_requests_once_and_fills_panel(env, monkeypatch):
    hud, bus, pipeline, *_ = env
    calls: list[tuple] = []
    monkeypatch.setattr(pipeline, "ensure", lambda *a: calls.append(a))
    monkeypatch.setattr(type(pipeline), "game_id", property(lambda self: 1))
    start(hud, bus)
    prof = pd.smurf_profile()
    feed(hud, 1, 0, prof, upto=Stage.H2H)
    hud.profiles[0].smurf = None  # nothing to show yet: the panel opens in its loading state
    hud.on_hotkey(HotkeyAction.INTEL.value)
    assert {c[2] for c in calls} == {Stage.INTEL, Stage.TENDENCIES}
    panel = hud.panels.current(HotkeyAction.INTEL.value)
    assert panel is not None and panel.loading
    assert isinstance(panel.body_widgets()[0], Skeleton)
    assert panel.chip.text().startswith("Ctrl+Shift+2")
    hud.on_update(LookupUpdate(1, 0, Stage.TENDENCIES, prof.tendencies))
    assert not panel.loading and "FORM" in " ".join(panel.texts())
    hud.on_hotkey(HotkeyAction.INTEL.value)  # same hotkey closes it
    assert hud.panels.current() is None


def test_intel_hotkey_with_nothing_known_toasts(env):
    hud, bus, *_ = env
    start(hud, bus)
    hud.on_update(LookupUpdate(1, 0, Stage.GAME, hud.profiles[0].seed))
    hud.on_update(LookupUpdate(1, 0, Stage.IDENTITY, None))  # no SC2Pulse match
    hud.on_hotkey(HotkeyAction.INTEL.value)
    assert hud.panels.current() is None
    assert toast_titles(hud) == ["No intel yet"]


def test_intel_links_emitted_for_tray(env):
    hud, bus, *_ = env
    links: list[list] = []
    hud.links_changed.connect(links.append)
    start(hud, bus)
    feed(hud, 1, 0, pd.intel_profile())
    assert links and links[-1][0] == (
        "Serral: Liquipedia",
        "https://liquipedia.net/starcraft2/Serral",
    )


def test_hint_items_and_short_hint_after_five_games(env):
    hud, bus, *_ = env
    start(hud, bus)
    assert [label for _, label in hud.hint.items] == ["card", "intel", "hide"]
    for gid in range(2, 7):
        start(hud, bus, ctx(gid))
    assert hud.games_seen == 6
    assert hud.hint.items == [("Ctrl+Shift+`", "hide"), ("Ctrl+Shift+1", "card")]


def test_hint_disabled(env):
    hud, bus, *_ = env
    hud.config.overlays.hint.enabled = False
    start(hud, bus)
    assert not hud.hint.isVisible()


def test_registered_panel_toggles_and_appears_in_hint(env, qtbot):
    from smurfsniper.ui.overlay.widgets import Part, Row

    hud, bus, *_ = env
    hud.register_panel(
        HotkeyAction.SESSION,
        "Session",
        lambda: [Row.create(hud.tokens, [Part("5-2")])],
    )
    start(hud, bus)
    feed(hud, 1, 0, pd.intel_profile())
    assert "session" in [label for _, label in hud.hint.items]
    hud.on_hotkey(HotkeyAction.SESSION.value)
    panel = hud.panels.current(HotkeyAction.SESSION.value)
    assert panel is not None and panel.title.text() == "Session"
    hud.on_hotkey(HotkeyAction.INTEL.value)  # another panel's hotkey swaps it
    assert hud.panels.current(HotkeyAction.SESSION.value) is None
    hud.on_hotkey(HotkeyAction.SESSION.value)
    hud.on_hotkey(HotkeyAction.SESSION.value)
    assert hud.panels.current() is None


def test_config_change_applies_tokens_live(env):
    hud, bus, *_ = env
    start(hud, bus)
    feed(hud, 1, 0, pd.pro_profile())
    w0 = hud.card.surface.width()
    new = hud.config
    new.overlays.scale = 1.25
    new.overlays.opacity = 0.9
    bus.config_changed.emit(new)
    assert hud.tokens.scale == 1.25 and hud.card.tokens.opacity == 0.9
    assert hud.card.surface.width() > w0
    assert hud.card.row_count() == 2  # rows rebuilt, none lost


def test_vs_ai_has_no_card(env):
    hud, bus, *_ = env
    me = GamePlayer(id=1, name="Me", race="Zerg")
    c = GameContext(1, T0, (me,), me, (), (), "other", True)
    start(hud, bus, c)
    assert hud.card.sections == [] and not hud.card.isVisible()


def test_preview_shows_sample_surfaces(env, qtbot):
    hud, *_ = env
    hud.preview()
    assert len(hud._previews) == 3
    assert all(w.isVisible() for w in hud._previews[::2])  # card + panel


def test_preview_twice_then_ends(env, qtbot):
    hud, *_ = env
    hud.preview()
    hud.preview()  # replaces the first set without crashing
    card = hud._previews[0]
    assert card.isVisible()
    hud._end_preview()
    assert not card.isVisible()
    qtbot.wait(10)


def test_duplicate_game_started_keeps_arrived_rows(env):
    hud, bus, *_ = env
    c = start(hud, bus)
    feed(hud, 1, 0, pd.smurf_profile())
    rows = hud.card.row_count()
    assert rows > 1
    bus.game_started.emit(c)  # same game delivered again (e.g. after an early update)
    assert hud.card.row_count() == rows and hud.card.shown
