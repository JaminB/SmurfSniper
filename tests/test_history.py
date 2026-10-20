from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import TypeAdapter

from smurfsniper.analyze.history import (
    RatingPoint,
    Record,
    account_age_days,
    climb_velocity,
    outcomes,
    rating_points,
    record,
    season_record,
    sparkline,
    trend,
)
from smurfsniper.api.sc2pulse.models import TeamHistorySeries

NOW = datetime(2026, 10, 19, tzinfo=UTC)


def pt(days_ago: float, rating: int, games=None, wins=None, season=68, team="t") -> RatingPoint:
    return RatingPoint(
        ts=NOW - timedelta(days=days_ago),
        rating=rating,
        season=season,
        games=games,
        wins=wins,
        team=team,
    )


def test_rating_points_from_fixture(fixture_json):
    series = TypeAdapter(list[TeamHistorySeries]).validate_python(fixture_json("team_histories"))
    pts = rating_points(series + series)  # duplicates collapse
    assert len(pts) == 18
    assert pts[0].rating == 7696 and pts[0].games == 5 and pts[0].season == 68
    assert pts == sorted(pts, key=lambda p: p.ts)
    outs = outcomes(pts)
    # WINS == GAMES everywhere in the fixture: 37 games, all wins
    assert len(outs) == 32 and all(o.won for o in outs)


def test_outcomes_single_games():
    outs = outcomes([pt(3, 3000, 10, 5), pt(2, 3020, 11, 6), pt(1, 3000, 12, 6)])
    assert [o.won for o in outs] == [True, False]
    assert [o.delta for o in outs] == [20, -20]


def test_outcomes_multi_game_gap():
    outs = outcomes([pt(3, 3000, 10, 5), pt(1, 3050, 14, 8)])
    assert len(outs) == 4
    assert sum(o.won for o in outs) == 3
    assert all(o.delta is None for o in outs)


def test_outcomes_season_boundary_and_teams():
    pts = [
        pt(5, 3000, 50, 30, season=67),
        pt(4, 2800, 1, 1, season=68),  # new season: skipped pair
        pt(3, 2900, 2, 2, season=68),
        pt(2, 4000, 7, 3, team="other"),  # separate team series
    ]
    outs = outcomes(pts)
    assert len(outs) == 1 and outs[0].won


def test_outcomes_fallback_to_rating_delta():
    outs = outcomes([pt(3, 3000), pt(2, 3010), pt(1, 3010), pt(0.5, 2990)])
    assert [o.won for o in outs] == [True, False]


def test_record_windows():
    outs = outcomes([pt(10, 3000), pt(9, 3010), pt(2, 3020), pt(1, 3000)])
    assert record(outs, days=3, now=NOW) == Record(1, 1)
    assert record(outs, days=None, now=NOW) == Record(2, 1)
    assert Record(0, 0).winrate is None
    assert Record(3, 1).winrate == 0.75 and str(Record(3, 1)) == "3-1"


def test_season_record():
    pts = [
        pt(5, 3000, 1, 1, season=67),
        pt(4, 3010, 2, 2, season=67),
        pt(2, 3000, 1, 0),
        pt(1, 3020, 2, 1),
    ]
    outs = outcomes(pts)
    assert season_record(outs, pts, 68) == Record(1, 0)
    assert season_record(outs, pts, 67) == Record(1, 0)


def test_sparkline():
    assert sparkline([1, 2]) is None
    assert sparkline([]) is None
    s = sparkline([1, 2, 3, 4, 5, 6, 7, 8])
    assert s[0] == "▁" and s[-1] == "█" and len(s) == 8
    assert len(sparkline(list(range(30)), width=12)) == 12


def test_trend():
    assert trend([pt(i, 3000) for i in range(4)]) is None
    up = trend([pt(10 - i, 3000 + 20 * i) for i in range(10)])
    assert up.symbol == "▲" and up.slope_per_day == pytest.approx(20)
    down = trend([pt(10 - i, 3000 - 20 * i) for i in range(10)])
    assert down.symbol == "▼"
    flat = trend([pt(10 - i, 3000 + (i % 2)) for i in range(10)])
    assert flat.symbol == "▶"


def test_account_age_and_climb():
    pts = [pt(10, 3000), pt(5, 3100), pt(0, 3200)]
    assert account_age_days(pts, None, NOW) == 10
    assert account_age_days([], NOW - timedelta(days=3), NOW) == 3
    assert account_age_days([], None, NOW) is None
    assert climb_velocity(pts, days=None, now=NOW) == pytest.approx(20)
    assert climb_velocity(pts, days=5) == pytest.approx(20)
    assert climb_velocity(pts[:1]) is None
