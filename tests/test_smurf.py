from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from smurfsniper.analyze.history import GameOutcome, RatingPoint
from smurfsniper.analyze.smurf import LEVELS, SmurfInputs, assess, level_for

NOW = datetime(2026, 10, 19, tzinfo=UTC)


def outs(days_ago: float, wins: int, losses: int) -> list[GameOutcome]:
    ts = NOW - timedelta(days=days_ago)
    return [GameOutcome(ts, True, 3000, 10)] * wins + [GameOutcome(ts, False, 3000, -10)] * losses


def points(first_days_ago: float, n: int, start: int, end: int) -> list[RatingPoint]:
    step = first_days_ago / max(n - 1, 1)
    return [
        RatingPoint(
            ts=NOW - timedelta(days=first_days_ago - i * step),
            rating=round(start + (end - start) * i / max(n - 1, 1)),
        )
        for i in range(n)
    ]


OLD_FLAT = points(400, 10, 3000, 3000)  # old account, no climb


@pytest.mark.parametrize(
    "o,pts,expected_codes,expected_score",
    [
        (outs(1, 4, 1), OLD_FLAT, {"wr3d"}, 35),  # 80% with 5
        (outs(1, 3, 1), OLD_FLAT, set(), 0),  # only 4 games
        (outs(1, 7, 3), OLD_FLAT, set(), 0),  # 70% < 80%
        (outs(5, 6, 2), OLD_FLAT, {"wr7d"}, 25),  # 75% with 8, outside 3d
        (outs(100, 21, 9), OLD_FLAT, {"wrlife"}, 15),  # 70% with 30
        (outs(100, 20, 9), OLD_FLAT, set(), 0),  # 29 games
        ([], points(10, 6, 3000, 3000), {"age"}, 30),  # <= 14 days
        ([], points(25, 6, 3000, 3000), {"age"}, 18),  # <= 30 days
        ([], points(400, 6, 3000, 3000 + 15 * 400), {"climb"}, 20),
        ([], points(400, 6, 3000, 3000 + 8 * 400), {"climb"}, 10),
        ([], points(10, 4, 3000, 9000), set(), 0),  # < 5 points: no age/climb
    ],
)
def test_weights(o, pts, expected_codes, expected_score):
    a = assess(SmurfInputs(outcomes=o, points=pts, now=NOW))
    assert {r.code for r in a.reasons} == expected_codes
    assert a.score == expected_score


def test_cap_and_ordering():
    o = outs(1, 10, 0) + outs(5, 10, 0) + outs(20, 20, 0)
    pts = points(7, 20, 2000, 4000)
    a = assess(SmurfInputs(outcomes=o, points=pts, now=NOW))
    assert sum(r.points for r in a.reasons) > 100
    assert a.score == 100 and a.level == "likely"
    assert [r.points for r in a.reasons] == sorted((r.points for r in a.reasons), reverse=True)
    assert a.top_reason.code == "wr3d"
    assert "new account (7d)" in [r.text for r in a.reasons]


def test_levels():
    assert LEVELS == ((70, "likely"), (45, "possible"), (25, "suspicious"))
    assert level_for(70) == "likely"
    assert level_for(69) == "possible"
    assert level_for(45) == "possible"
    assert level_for(25) == "suspicious"
    assert level_for(24) == "none"


def test_empty_is_none():
    a = assess(SmurfInputs(outcomes=[], points=[], now=NOW))
    assert a.score == 0 and a.level == "none" and a.reasons == ()
