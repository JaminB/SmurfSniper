from __future__ import annotations

from smurfsniper.app.hotkeys import to_display
from smurfsniper.models.config import Config
from smurfsniper.ui import preview_data as pd
from smurfsniper.ui.overlay import Panel, PanelHost
from smurfsniper.ui.overlay.widgets import Skeleton
from smurfsniper.ui.panels.intel import build_intel_body, links_of
from smurfsniper.ui.tokens import TokenContext


def make(title: str, binding: str) -> Panel:
    return Panel(title, to_display(binding), TokenContext(), Config().overlays.panels.placement)


def test_toggle_shows_hides_and_swaps(qtbot, no_anim):
    host = PanelHost()
    intel = host.toggle("intel", lambda: make("Scouting intel", "ctrl+shift+2"))
    assert intel is not None and intel.isVisible() and host.key == "intel"
    assert host.toggle("intel", lambda: make("Scouting intel", "ctrl+shift+2")) is None
    assert not intel.isVisible() and host.current() is None
    host.toggle("intel", lambda: make("Scouting intel", "ctrl+shift+2"))
    first = host.panel
    rivals = host.toggle("rivals", lambda: make("Rivals", "ctrl+shift+4"))
    assert host.key == "rivals" and rivals.isVisible()
    assert first is not None and not first.isVisible()
    host.hide()
    assert host.current() is None


def test_hidden_panel_survives_gc_until_its_fade_out_ends(qtbot):
    import gc

    host = PanelHost()
    host.toggle("intel", lambda: make("Scouting intel", "ctrl+shift+2"))
    qtbot.waitUntil(lambda: host.panel is not None and host.panel.windowOpacity() > 0.9)
    host.hide()
    gc.collect()
    closing = [w for w in host._closing if w.isVisible()]
    assert len(closing) == 1  # still fading out, not destroyed
    qtbot.waitUntil(lambda: not host._closing, timeout=2000)


def test_header_chip_shows_the_hotkey(qtbot):
    p = make("Scouting intel", "ctrl+shift+2")
    assert p.chip.text().startswith(to_display("ctrl+shift+2"))
    assert p.chip.text().startswith("Ctrl+Shift+2")
    assert p.chip.text().endswith("✕")


def test_loading_then_body(qtbot, no_anim):
    p = make("Scouting intel", "ctrl+shift+2")
    p.set_loading()
    assert p.loading and isinstance(p.body_widgets()[0], Skeleton)
    body = build_intel_body([pd.intel_profile()], p.tokens)
    p.set_body(body)
    assert not p.loading
    assert not any(isinstance(w, Skeleton) for w in p.body_widgets())
    text = " ".join(p.texts())
    assert "Serral" in text and "Aligulac 3,431 (#1)" in text
    assert "FORM" in text and "MAPS" in text and "LINKS" in text
    assert "Last opponent links" in text


def test_intel_body_none_without_data(qtbot):
    assert build_intel_body([pd.seed_profile()], TokenContext()) is None


def test_intel_body_names_each_opponent_in_team_games(qtbot):
    a, b = pd.intel_profile(), pd.smurf_profile()
    body = build_intel_body([a, b], TokenContext())
    assert body is not None and len(body) == 2


def test_links_for_tray():
    links = links_of([pd.intel_profile()])
    labels = [label for label, _ in links]
    assert labels == ["Serral: Liquipedia", "Serral: Twitch", "Serral: Aligulac"]
    assert all(url.startswith("https://") for _, url in links)
