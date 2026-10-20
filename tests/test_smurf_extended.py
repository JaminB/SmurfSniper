"""The alt-account, peak-gap and off-race signals (spec 5.6)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from smurfsniper.analyze.history import GameOutcome, RatingPoint
from smurfsniper.analyze.smurf import SmurfInputs, assess
from smurfsniper.api.sc2pulse.models import LadderDistinctCharacter

NOW = datetime(2026, 10, 19, tzinfo=UTC)
OLD = [RatingPoint(ts=NOW - timedelta(days=400 - i), rating=3000) for i in range(10)]


def alt(rating_max: int | None, cid: int = 900, name: str = "Main#1", region: str = "EU"):
    return LadderDistinctCharacter.model_validate(
        {
            "ratingMax": rating_max,
            "members": {
                "character": {
                    "id": cid,
                    "accountId": 5,
                    "region": region,
                    "realm": 1,
                    "battlenetId": cid,
                    "name": name,
                }
            },
        }
    )


def run(**kw):
    kw.setdefault("current_mmr", 3000)
    return assess(SmurfInputs(outcomes=[], points=OLD, now=NOW, **kw))


def codes(a) -> dict[str, int]:
    return {r.code: r.points for r in a.reasons}


# ---------------------------------------------------------------- alt_peak
@pytest.mark.parametrize(
    "peak,points",
    [(4500, 35), (3800, 35), (3799, 20), (3400, 20), (3399, None)],
)
def test_alt_peak_thresholds(peak, points):
    """Gap to current (3000): 800+ is the strong tier, 400+ the lesser, never both."""
    got = codes(run(alt_characters=[alt(peak)]))
    assert got == ({"alt_peak": points} if points else {})


def test_alt_peak_reason_text_and_strongest_alt_only():
    a = run(alt_characters=[alt(3500, 1, "Weak#1"), alt(4200, 2, "Strong#9", "US")])
    assert a.reasons[0].code == "alt_peak" and a.reasons[0].points == 35  # not 35 + 20
    assert a.reasons[0].text == "alt Strong (US) peaked 4,200"
    assert a.score == 35


def test_alt_peak_excludes_the_character_itself():
    a = run(alt_characters=[alt(5000, cid=77)], character_id=77)
    assert "alt_peak" not in codes(a)
    assert "alt_peak" in codes(run(alt_characters=[alt(5000, cid=77)], character_id=78))


def test_alt_peak_with_the_recorded_account(fixture_json):
    alts = [LadderDistinctCharacter.model_validate(c) for c in fixture_json("chars_account")]
    a = run(alt_characters=alts, current_mmr=4000, character_id=1)
    assert codes(a)["alt_peak"] == 35 and a.score >= 35
    assert "peaked 8,127" in a.reasons[0].text


def test_alt_without_a_peak_is_ignored():
    assert codes(run(alt_characters=[alt(None)])) == {}


# ---------------------------------------------------------------- peak_gap
@pytest.mark.parametrize(
    "kw,points",
    [
        ({"peak_league": 5, "current_league": 2}, 25),  # 3 leagues
        ({"peak_league": 4, "current_league": 2}, 15),  # 2 leagues
        ({"peak_league": 3, "current_league": 2}, None),  # 1 league
        ({"peak_mmr": 4200}, 25),  # 1200 MMR
        ({"peak_mmr": 3700}, 15),  # 700 MMR
        ({"peak_mmr": 3699}, None),
    ],
)
def test_peak_gap(kw, points):
    got = codes(run(**kw))
    assert got == ({"peak_gap": points} if points else {})


def test_peak_gap_is_not_cumulative_and_reads_well():
    a = run(peak_league=5, current_league=1, peak_mmr=5200)
    assert codes(a) == {"peak_gap": 25}
    assert a.reasons[0].text == "peaked Master (5,200), now Silver"


def test_peak_gap_without_league_names_uses_numbers():
    a = run(peak_mmr=4500)
    assert a.reasons[0].text == "peaked 4,500, now 3,000"


# ---------------------------------------------------------------- off_race
GAMES = {"TERRAN": 300, "ZERG": 20}


def test_off_race_with_a_higher_main_peak():
    a = run(race_games=GAMES, current_race="ZERG", race_peaks={"TERRAN": 3400})
    assert codes(a) == {"off_race": 20}
    assert a.reasons[0].text == "off-racing: main Terran peaked 3,400"


def test_off_race_without_a_higher_peak():
    a = run(race_games=GAMES, current_race="ZERG", race_peaks={"TERRAN": 3200})
    assert codes(a) == {"off_race": 8}
    assert a.reasons[0].text == "off-racing (main Terran)"


@pytest.mark.parametrize(
    "games,race",
    [
        ({"TERRAN": 300, "ZERG": 80}, "ZERG"),  # 21% of games: not off-racing
        ({"TERRAN": 90, "ZERG": 5}, "ZERG"),  # main race under 100 games
        ({"TERRAN": 300, "ZERG": 20}, "TERRAN"),  # playing the main race
        ({"TERRAN": 300, "ZERG": 20}, "RANDOM"),
        ({"TERRAN": 300, "ZERG": 20}, None),
        ({}, "ZERG"),
    ],
)
def test_off_race_does_not_fire(games, race):
    assert "off_race" not in codes(run(race_games=games, current_race=race))


def test_off_race_lesser_variant_works_without_current_mmr():
    a = run(race_games=GAMES, current_race="ZERG", race_peaks={"TERRAN": 9000}, current_mmr=None)
    assert codes(a) == {"off_race": 8}


# ------------------------------------------------------------ cross-cutting
def test_signals_that_compare_ratings_need_current_mmr():
    a = run(
        current_mmr=None,
        alt_characters=[alt(9000)],
        peak_league=6,
        current_league=1,
        peak_mmr=9000,
    )
    assert codes(a) == {}


def test_total_is_capped_at_100_and_reasons_sort_by_points():
    wins = [GameOutcome(NOW - timedelta(hours=1), True, 3000, 10)] * 10
    pts = [RatingPoint(ts=NOW - timedelta(days=10 - i), rating=3000 + 60 * i) for i in range(8)]
    a = assess(
        SmurfInputs(
            outcomes=wins,
            points=pts,
            now=NOW,
            current_mmr=3400,
            peak_league=6,
            current_league=2,
            alt_characters=[alt(5000)],
            race_games=GAMES,
            current_race="ZERG",
            race_peaks={"TERRAN": 4000},
        )
    )
    assert a.score == 100 and a.level == "likely"
    assert sum(r.points for r in a.reasons) > 100
    pts_sorted = [r.points for r in a.reasons]
    assert pts_sorted == sorted(pts_sorted, reverse=True)
    assert a.top_reason is a.reasons[0] and a.top_reason.points == 35


def test_labels_and_thresholds_unchanged():
    assert run(alt_characters=[alt(4000)]).level == "suspicious"  # 35 -> >= 25
    both = run(alt_characters=[alt(4000)], peak_league=5, current_league=2)
    assert both.score == 60 and both.level == "possible"
