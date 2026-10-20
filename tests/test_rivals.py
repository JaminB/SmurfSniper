from __future__ import annotations

from datetime import UTC, datetime, timedelta

from smurfsniper.analyze.history import Record
from smurfsniper.analyze.rivals import rivals
from smurfsniper.storage.rows import PlayerLogRow

NOW = datetime(2026, 10, 19, 20, 0, tzinfo=UTC)
_ids = iter(range(1, 10_000))


def row(
    bnet: int,
    name: str,
    result: str,
    *,
    days: int = 1,
    mode: str | None = "1v1",
    mmr: int | None = 4000,
    race: str = "ZERG",
    region: str = "EU",
) -> PlayerLogRow:
    return PlayerLogRow(
        id=next(_ids),
        battlenet_id=bnet,
        name=name,
        realm=1,
        region=region,
        account_id=None,
        match_status={"victory": "defeat", "defeat": "victory", "tie": "tie"}[result],
        mmr=mmr,
        created_at=NOW - timedelta(days=days),
        mode=mode,
        my_result=result,
        opp_race=race,
    )


def games(bnet: int, name: str, wins: int, losses: int, **kw) -> list[PlayerLogRow]:
    return [row(bnet, name, "victory", **kw) for _ in range(wins)] + [
        row(bnet, name, "defeat", **kw) for _ in range(losses)
    ]


def test_nemesis_and_victim_selection():
    rows = games(1, "Bob#1", 2, 6) + games(2, "Alice#2", 7, 1) + games(3, "Carl#3", 3, 3)
    s = rivals(rows)
    assert s.nemesis is not None and s.nemesis.name == "Bob"
    assert s.nemesis.record == Record(2, 6) and s.nemesis.games == 8
    assert s.favourite_victim is not None and s.favourite_victim.name == "Alice"
    assert [r.name for r in s.top] == ["Bob", "Alice", "Carl"]  # by games, ties by recency


def test_nemesis_needs_two_losses_and_losing_record():
    s = rivals(games(1, "A", 0, 1) + games(2, "B", 3, 3) + games(3, "C", 1, 2))
    assert s.nemesis is not None and s.nemesis.name == "C"  # 1-2: the only one that qualifies
    s = rivals(games(2, "B", 3, 3) + games(4, "D", 1, 1))
    assert s.nemesis is None and s.favourite_victim is None


def test_victim_needs_two_wins():
    s = rivals(games(1, "A", 1, 0) + games(2, "B", 2, 1))
    assert s.favourite_victim is not None and s.favourite_victim.name == "B"


def test_min_games_and_top_n():
    rows = games(1, "A", 1, 0) + games(2, "B", 1, 1)
    assert [r.name for r in rivals(rows).top] == ["B"]
    assert rivals(rows, min_games=1).top[0].name in {"A", "B"}
    many = [r for i in range(10) for r in games(i, f"P{i}", 1, 1)]
    assert len(rivals(many, top_n=3).top) == 3
    assert rivals([]).is_empty()


def test_mode_filter_keeps_legacy_rows_as_1v1():
    rows = games(1, "A", 2, 0, mode="2v2") + games(2, "B", 2, 0, mode=None)
    assert [r.name for r in rivals(rows).top] == ["B"]
    assert {r.name for r in rivals(rows, mode=None).top} == {"A", "B"}
    assert [r.name for r in rivals(rows, mode="2v2").top] == ["A"]


def test_tie_break_by_losses_then_stable_order():
    # 1-3 and 0-2 are both 2 behind; the one with more losses is the nemesis
    s = rivals(games(1, "Big", 1, 3) + games(2, "Small", 0, 2))
    assert s.nemesis is not None and s.nemesis.name == "Big"


def test_details_come_from_the_newest_game():
    rows = [
        row(1, "Old#1", "defeat", days=10, mmr=3000, race="TERRAN"),
        row(1, "Bob#1", "defeat", days=1, mmr=4100, race="ZERG"),
    ]
    r = rivals(rows).top[0]
    assert r.name == "Bob" and r.last_mmr == 4100 and r.last_race == "ZERG"
    assert r.last_played == NOW - timedelta(days=1)


def test_standing():
    s = rivals(games(1, "Bob", 2, 6) + games(2, "Carl", 3, 3))
    assert s.standing("EU", 1) == "nemesis"
    assert s.standing("EU", 2) == "rival"
    assert s.standing("EU", 99) is None
    assert s.standing("US", 1) is None
