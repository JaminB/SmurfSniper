from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from pydantic import TypeAdapter
from PySide6.QtWidgets import QLabel

from smurfsniper.analyze.h2h import H2HInfo
from smurfsniper.analyze.history import Record, Trend
from smurfsniper.analyze.smurf import SmurfAssessment, SmurfReason
from smurfsniper.api.sc2client.models import GamePlayer
from smurfsniper.api.sc2pulse.models import LadderDistinctCharacter
from smurfsniper.core.game_state import GameContext
from smurfsniper.core.profile import (
    GameSeed,
    Identity,
    LookupUpdate,
    OpponentProfile,
    RatingInfo,
    SmurfInfo,
    Stage,
)
from smurfsniper.models.config import Config
from smurfsniper.ui import overlay_manager
from smurfsniper.ui.legacy_render import LegacyRenderer, h2h_lines, player_lines

PLACEHOLDER = re.compile(r"\bNone\b|unknown|\(no data\)|insufficient|\(none\)|\b0-0\b", re.I)
NOW = datetime(2026, 10, 19, tzinfo=UTC)


def identity(fixture_json) -> Identity:
    c = TypeAdapter(list[LadderDistinctCharacter]).validate_python(
        fixture_json("characters_query")
    )[0]
    return Identity(
        character=c.members.character,
        clan=c.members.clan,
        pro=c.members.pro_player,
        candidate=c,
        confidence=1.0,
    )


def full_profile(fixture_json) -> OpponentProfile:
    return OpponentProfile(
        seed=GameSeed("Serral", "ZERG"),
        identity=identity(fixture_json),
        rating=RatingInfo(
            mmr=4410,
            league=4,
            tier=0,
            region_percentile=91.0,
            season_wins=9,
            season_losses=1,
            peak_mmr=7557,
            peak_league=6,
            mmr_to_next_tier=None,
            team=None,
        ),
        smurf=SmurfInfo(
            assessment=SmurfAssessment(82, "likely", (SmurfReason("age", "new account (9d)", 30),)),
            trend=Trend(31.0, "▲"),
            sparkline="▁▂▃▅▇█",
            records={"3d": Record(9, 1)},
        ),
        h2h=H2HInfo(4, 3, 1, 0, NOW - timedelta(days=30), NOW - timedelta(days=2)),
    )


def test_bare_profile_has_no_placeholders():
    lines = player_lines(OpponentProfile(seed=GameSeed("Bob", None)), now=NOW)
    assert lines == ["Bob"]


def test_full_profile_lines(fixture_json):
    lines = player_lines(full_profile(fixture_json), now=NOW)
    text = "\n".join(lines)
    assert not PLACEHOLDER.search(text), text
    assert "MMR 4,410" in text and "Diamond 1" in text and "top 9%" in text
    assert "Likely smurf (82/100) - new account (9d)" in text
    assert "3d 9-1" in text and "Season 9-1" in text and "[BASKGG]" in text
    assert "👑 Serral [BSLSK]" in text
    h = "\n".join(h2h_lines(full_profile(fixture_json), now=NOW))
    assert "Your record: 3W – 1L" in h and "Last played 2d ago" in h


def test_none_smurf_level_hidden(fixture_json):
    prof = full_profile(fixture_json)
    prof.smurf = SmurfInfo(SmurfAssessment(10, "none"), None, None, {})
    text = "\n".join(player_lines(prof, now=NOW))
    assert "smurf" not in text.lower()
    assert not PLACEHOLDER.search(text)


def ctx(n: int = 1) -> GameContext:
    me = GamePlayer(id=1, name="Me")
    opps = tuple(GamePlayer(id=i + 2, name=f"P{i}", race="Zerg") for i in range(n))
    return GameContext(1, NOW, (me, *opps), me, (), opps, "1v1" if n == 1 else "2v2", False)


def renderer(show: bool = False) -> LegacyRenderer:
    return LegacyRenderer(Config(), show=show)


def test_main_waits_for_identity_rating_smurf(qtbot, fixture_json):
    r = renderer(show=True)
    kinds: list[str] = []
    r.rendered.connect(lambda k, g: kinds.append(k))
    r.on_game_started(ctx())
    prof = full_profile(fixture_json)
    r.on_update(LookupUpdate(1, 0, Stage.IDENTITY, prof.identity))
    r.on_update(LookupUpdate(1, 0, Stage.RATING, prof.rating))
    assert kinds == []
    r.on_update(LookupUpdate(1, 0, Stage.SMURF, None, error="boom"))  # failure still counts
    assert kinds == ["main"]
    r.on_update(LookupUpdate(1, 0, Stage.H2H, prof.h2h))
    assert kinds == ["main", "h2h0"]
    assert len(overlay_manager.OPEN_OVERLAYS) == 2
    r.reset()
    assert overlay_manager.OPEN_OVERLAYS == []


def test_unresolved_identity_shows_nothing():
    r = renderer()
    kinds: list[str] = []
    r.rendered.connect(lambda k, g: kinds.append(k))
    r.on_game_started(ctx(2))
    r.on_update(LookupUpdate(1, 0, Stage.IDENTITY, None))
    r.on_update(LookupUpdate(1, 1, Stage.IDENTITY, None))
    assert kinds == []


def test_intel_waits_for_intel_stage(fixture_json):
    r = renderer()
    kinds: list[str] = []
    r.rendered.connect(lambda k, g: kinds.append(k))
    r.on_game_started(ctx())
    prof = full_profile(fixture_json)
    r.on_update(LookupUpdate(1, 0, Stage.IDENTITY, prof.identity))
    r.request_intel()
    assert "intel" not in kinds
    from smurfsniper.core.profile import IntelInfo

    r.on_update(
        LookupUpdate(
            1, 0, Stage.INTEL, IntelInfo(pro=prof.identity.pro, aligulac=None, liquipedia=None)
        )
    )
    assert "intel" in kinds


def _shown_main(qtbot, fixture_json, config: Config | None = None) -> LegacyRenderer:
    r = LegacyRenderer(config or Config(), show=True)
    r.on_game_started(ctx())
    prof = full_profile(fixture_json)
    r.on_update(LookupUpdate(1, 0, Stage.IDENTITY, prof.identity))
    r.on_update(LookupUpdate(1, 0, Stage.RATING, prof.rating))
    r.on_update(LookupUpdate(1, 0, Stage.SMURF, prof.smurf))
    return r


def test_toggle_closes_and_reshows_from_cache_without_updates(qtbot, fixture_json):
    r = _shown_main(qtbot, fixture_json)
    assert r.is_open("main")
    assert r.toggle("main") is False  # visible -> closed
    assert not r.is_open("main")
    assert r.toggle("main") is True  # closed -> shown again from the cached profile
    assert r.is_open("main")
    r.reset()


def test_hide_all_suppresses_and_closes(qtbot, fixture_json):
    r = _shown_main(qtbot, fixture_json)
    seen: list[bool] = []
    r.hidden_changed.connect(seen.append)
    r.set_hidden(True)
    assert not r.is_open("main") and seen == [True]
    r.toggle("main")  # re-showing while hidden stays suppressed
    assert not r.is_open("main")
    r.set_hidden(False)
    assert seen == [True, False]
    r.toggle("main")
    assert r.is_open("main")
    r.reset()


def test_new_game_clears_hide_all(qtbot, fixture_json):
    r = _shown_main(qtbot, fixture_json)
    r.set_hidden(True)
    r.on_game_started(ctx())
    assert r.hidden is False


def test_card_settings_drive_the_overlay(qtbot, fixture_json):
    from smurfsniper.models.config import Anchor

    cfg = Config()
    cfg.overlays.card.placement.anchor = Anchor.BOTTOM_RIGHT
    cfg.overlays.card.auto_hide_seconds = 0  # stay until the game ends
    cfg.overlays.opacity = 0.5
    r = _shown_main(qtbot, fixture_json, cfg)
    ov = r._windows["main"]
    assert ov.placement.anchor is Anchor.BOTTOM_RIGHT and ov.duration_seconds == 0
    label = ov.findChildren(QLabel)[0]
    assert "rgba(15, 15, 15, 128)" in label.styleSheet()  # opacity 0.5 -> alpha 128
    r.reset()


def test_disabled_card_is_never_shown(qtbot, fixture_json):
    cfg = Config()
    cfg.overlays.card.enabled = False
    r = _shown_main(qtbot, fixture_json, cfg)
    assert not r.is_open("main")
