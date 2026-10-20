from __future__ import annotations

import re

import pytest
from PySide6.QtWidgets import QLabel

from smurfsniper.analyze.history import Record
from smurfsniper.analyze.smurf import SmurfAssessment
from smurfsniper.core.lookup import TEAM_SLOT
from smurfsniper.core.profile import GameSeed, LookupUpdate, SmurfInfo, Stage
from smurfsniper.models.config import Config
from smurfsniper.ui import preview_data as pd
from smurfsniper.ui.overlay import OpponentCard
from smurfsniper.ui.overlay.widgets import Badge, Row
from smurfsniper.ui.tokens import TokenContext

PLACEHOLDER = re.compile(r"\bNone\b|unknown|\(no data\)|insufficient|\(none\)|\b0-0\b", re.I)


@pytest.fixture
def card(qtbot, no_anim):
    c = OpponentCard(TokenContext(), Config().overlays.card.placement, now=lambda: pd.NOW)
    yield c
    c.hide()
    c.deleteLater()


def all_label_texts(card: OpponentCard) -> list[str]:
    return [w.text() for w in card.findChildren(QLabel)]


def assert_clean(card: OpponentCard) -> None:
    for text in all_label_texts(card):
        assert not PLACEHOLDER.search(text), text
        assert text.strip(), "empty label rendered"


def test_game_only_has_exactly_one_row(card):
    card.start(1, [GameSeed("Serral", "ZERG")])
    card.reveal()
    assert card.row_count() == 1
    assert card.texts() == ["Serral"]
    assert_clean(card)


def test_each_stage_adds_the_expected_rows_and_grows(card):
    prof = pd.smurf_profile()
    card.start(1, [prof.seed], my_race="ZERG")
    card.reveal()
    sec = card.section(0)
    heights = [card.surface.sizeHint().height()]
    expected = {
        Stage.IDENTITY: 1,  # row 1 enriched in place
        Stage.RATING: 2,
        Stage.SMURF: 4,  # + reasons + trend/records
        Stage.H2H: 5,
        Stage.TENDENCIES: 6,
    }
    for u in pd.updates_for(1, 0, prof)[1:]:
        card.apply(u)
        if u.stage in expected:
            assert card.row_count() == expected[u.stage], u.stage
            heights.append(card.surface.sizeHint().height())
    assert heights == sorted(heights)
    assert sec.slot_order() == ["identity", "rating", "reasons", "trend", "h2h", "tendencies"]
    badges = [b.text() for b in sec.rows["identity"].findChildren(Badge)]
    assert badges == ["LIKELY SMURF 82"]
    text = " ".join(card.texts())
    assert "4,410 MMR" in text and "Diamond 1" in text and "top 9%" in text
    assert "3d 9-1 · 7d 15-3" in text and "You" in text and "0-1" in text
    assert "vs Z" in text and "avg 7:40" in text
    assert_clean(card)


def test_set_h2h_none_adds_nothing(card):
    card.start(1, [GameSeed("Bob", "TERRAN")])
    card.section(0).set_h2h(None)
    card.apply(LookupUpdate(1, 0, Stage.H2H, None))
    assert card.row_count() == 1


def test_level_none_adds_no_badge_or_reasons_and_skips_empty_windows(card):
    card.start(1, [GameSeed("Bob", "TERRAN")])
    smurf = SmurfInfo(
        SmurfAssessment(10, "none"),
        None,
        None,
        {"3d": Record(0, 0), "7d": Record(5, 2)},
    )
    card.section(0).set_smurf(smurf)
    sec = card.section(0)
    assert "reasons" not in sec.rows
    assert not sec.rows["identity"].findChildren(Badge)
    assert sec.rows["trend"].texts() == ["7d 5-2"]
    assert_clean(card)


def test_smurf_with_nothing_to_show_adds_no_rows(card):
    card.start(1, [GameSeed("Bob", "TERRAN")])
    card.section(0).set_smurf(SmurfInfo(SmurfAssessment(0, "none"), None, None, {}))
    assert card.row_count() == 1


def test_footprint_within_spec(card):
    prof = pd.smurf_profile()
    card.start(1, [prof.seed], my_race="ZERG")
    for u in pd.updates_for(1, 0, prof):
        card.apply(u)
    card.reveal()
    size = card.surface.size()
    assert size.width() <= 320 and size.height() <= 170, size


def test_width_clamped_and_long_names_elide(card):
    card.start(1, [GameSeed("A" * 80, "PROTOSS")])
    card.reveal()
    assert 248 <= card.surface.width() <= 320


def test_scale_grows_the_card(qtbot, no_anim):
    prof = pd.pro_profile()
    sizes = []
    for scale in (1.0, 1.25):
        c = OpponentCard(TokenContext(scale=scale), Config().overlays.card.placement)
        c.start(1, [prof.seed])
        for u in pd.updates_for(1, 0, prof):
            c.apply(u)
        c.reveal()
        sizes.append(c.surface.size())
        c.hide()
    assert sizes[1].width() > sizes[0].width() and sizes[1].height() > sizes[0].height()


def test_duo_card_with_team_strip(card):
    profs = pd.duo_profiles()
    card.start(1, [p.seed for p in profs])
    for i, p in enumerate(profs):
        for u in pd.updates_for(1, i, p):
            card.apply(u)
    before = card.row_count()
    card.apply(LookupUpdate(1, TEAM_SLOT, Stage.TEAM, pd.duo_team()))
    assert card.row_count() == before + 1
    text = " ".join(card.texts())
    assert "Team" in text and "4,410 MMR" in text and "12-4 this season" in text
    assert "POSSIBLE 51" in [b.text() for b in card.findChildren(Badge)]
    assert_clean(card)


def test_team_none_adds_nothing(card):
    profs = pd.duo_profiles()
    card.start(1, [p.seed for p in profs])
    card.apply(LookupUpdate(1, TEAM_SLOT, Stage.TEAM, None))
    assert card.row_count() == 2


def test_compact_card_one_row_each_plus_top_reason(card):
    profs = pd.quad_profiles()
    card.start(1, [p.seed for p in profs])
    for i, p in enumerate(profs):
        for u in pd.updates_for(1, i, p):
            card.apply(u)
    assert card.mode == "compact"
    assert all(list(s.rows) == ["identity"] for s in card.sections)
    assert card.row_count() == 5
    assert card.texts()[-2:] == ["Bravo:", "3d winrate 9/10"]
    assert_clean(card)


def test_row_create_returns_none_for_empty_parts(qtbot):
    from smurfsniper.ui.overlay.widgets import Part

    assert Row.create(TokenContext(), [Part(None), Part(""), None]) is None


def test_animated_reveal_grow_and_dismiss(qtbot):
    """Animations on: rows fade in, geometry animates, dismiss hides after the fade."""
    c = OpponentCard(TokenContext(), Config().overlays.card.placement, now=lambda: pd.NOW)
    prof = pd.smurf_profile()
    c.start(1, [prof.seed], my_race="ZERG")
    c.reveal()
    assert c.isVisible()
    for u in pd.updates_for(1, 0, prof)[1:]:
        c.apply(u)
    qtbot.wait(300)
    assert c.row_count() == 6 and c.windowOpacity() > 0.9
    assert c.height() == c.target_geometry().height()
    c.dismiss()
    assert c.isVisible() and not c.shown  # fading out
    qtbot.waitUntil(lambda: not c.isVisible(), timeout=2000)
    c.reveal()  # reusable after dismiss
    assert c.shown
    c.hide_now()
