"""analyze.tendencies over the recorded matches plus synthetic ones."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

from smurfsniper.analyze.history import Record
from smurfsniper.analyze.tendencies import peak_window, tendencies
from smurfsniper.api.sc2pulse.models import LadderMatch

ME = 1
OPP = 2
BASE = datetime(2026, 10, 19, 20, 0, tzinfo=UTC)


def mk(
    i: int,
    won: bool,
    *,
    opp_race: str = "ZERG",
    my_race: str = "TERRAN",
    secs: int | None = 600,
    map_name: str = "Alcyone LE",
    hours_ago: float | None = None,
    ts: datetime | None = None,
    me: int = ME,
) -> LadderMatch:
    when = ts or BASE - timedelta(hours=hours_ago if hours_ago is not None else i)

    def part(cid: int, decision: str, race: str, team: int) -> dict:
        return {
            "participant": {
                "matchId": i,
                "playerCharacterId": cid,
                "teamId": team,
                "decision": decision,
            },
            "teamState": {"race": race},
        }

    return LadderMatch.model_validate(
        {
            "match": {
                "id": i,
                "date": when.isoformat(),
                "type": "_1V1",
                "region": "EU",
                "duration": secs,
                "mapId": 1,
            },
            "map": {"id": 1, "name": map_name},
            "participants": [
                part(me, "WIN" if won else "LOSS", my_race, 10),
                part(OPP, "LOSS" if won else "WIN", opp_race, 20),
            ],
        }
    )


def test_fewer_than_three_matches_is_none(fixture_json):
    real = [LadderMatch.model_validate(m) for m in fixture_json("character_matches")["result"]]
    assert tendencies(real, 341427506, tz=UTC) is None
    assert tendencies([mk(1, True), mk(2, False)], ME, tz=UTC) is None


def test_recorded_matches_mixed_with_synthetic(fixture_json):
    """The recorded games are 2v2 (no single opponent race); they still count."""
    real = [LadderMatch.model_validate(m) for m in fixture_json("character_matches")["result"]]
    extra = [mk(100 + i, True, hours_ago=30 + i) for i in range(3)]
    t = tendencies([*real, *extra], 341427506, tz=UTC)
    assert t is None  # synthetic games are for other characters: only the 2 recorded count
    t = tendencies([*real, *[mk(100 + i, True) for i in range(3)]], ME, tz=UTC)
    assert t is not None and t.games == 3  # only the synthetic ones involve character ME


def test_vs_race_maps_duration_and_form():
    ms = [
        mk(1, True, opp_race="ZERG", map_name="Alcyone LE", secs=500),
        mk(2, True, opp_race="ZERG", map_name="Alcyone LE", secs=700),
        mk(3, False, opp_race="ZERG", map_name="Pylon LE", secs=900),
        mk(4, True, opp_race="TERRAN", map_name="Pylon LE", secs=300),
        mk(5, False, opp_race="PROTOSS", map_name="Rainfall LE", secs=None),
    ]
    t = tendencies(ms, ME, tz=UTC)
    assert t is not None and t.games == 5
    assert t.vs_race["ZERG"] == Record(2, 1)
    assert t.vs_race["TERRAN"] == Record(1, 0)
    assert t.vs_race["PROTOSS"] == Record(0, 1)
    assert list(t.maps)[:2] == ["Alcyone LE", "Pylon LE"]
    assert t.maps["Alcyone LE"] == Record(2, 0)
    assert t.avg_duration_s == round((500 + 700 + 900 + 300) / 4)
    assert t.form == ("W", "W", "L", "W", "L")  # newest first
    assert t.streak == ("W", 2)


def test_maps_limited_to_five():
    ms = [mk(i, True, map_name=f"Map {i}") for i in range(8)]
    t = tendencies(ms, ME, tz=UTC)
    assert t is not None and len(t.maps) == 5


def test_form_keeps_last_ten():
    ms = [mk(i, i % 2 == 0) for i in range(15)]
    t = tendencies(ms, ME, tz=UTC)
    assert t is not None and len(t.form) == 10 and t.form[0] == "W"


def test_short_win_rate_needs_five_wins():
    few = [mk(i, True, secs=200) for i in range(4)] + [mk(9, False)]
    assert tendencies(few, ME, tz=UTC).short_win_rate is None
    cheese = [mk(i, True, secs=240) for i in range(5)] + [
        mk(10 + i, True, secs=900) for i in range(3)
    ]
    t = tendencies(cheese, ME, tz=UTC)
    assert t is not None and t.short_win_rate == 5 / 8


def test_active_hours_in_local_time_and_gating():
    tz = timezone(timedelta(hours=2))
    # ten games, all at 20:10 UTC = 22:10 local
    ms = [mk(i, True, ts=datetime(2026, 10, 1 + i, 20, 10, tzinfo=UTC)) for i in range(10)]
    t = tendencies(ms, ME, tz=tz)
    assert t is not None and t.active_hours is not None
    assert t.active_hours[22] == 10 and sum(t.active_hours) == 10
    assert t.peak_hours is not None and 22 in range(t.peak_hours[0], t.peak_hours[0] + 3)
    nine = tendencies(ms[:9], ME, tz=tz)
    assert nine is not None and nine.active_hours is None and nine.peak_hours is None


def test_peak_window_wraps_midnight():
    hours = [0] * 24
    hours[23], hours[0], hours[1] = 4, 3, 2
    assert peak_window(hours) == (23, 2)
    assert peak_window([0] * 24) is None


def test_race_switches():
    ms = [mk(i, True, my_race="TERRAN") for i in range(6)] + [
        mk(10 + i, True, my_race="ZERG") for i in range(2)
    ]
    t = tendencies(ms, ME, tz=UTC)
    assert t is not None
    assert t.races_played == {"TERRAN": 6, "ZERG": 2}
    assert t.race_switches == 2
