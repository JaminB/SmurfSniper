from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from pydantic import TypeAdapter

from smurfsniper.analyze.h2h import head_to_head
from smurfsniper.api.sc2client.models import GamePlayer
from smurfsniper.api.sc2pulse.models import LadderDistinctCharacter
from smurfsniper.core.game_state import GameContext, GameResult
from smurfsniper.core.profile import GameSeed, Identity, OpponentProfile
from smurfsniper.storage.db import init_db, schema_version
from smurfsniper.storage.migrations import MIGRATIONS
from smurfsniper.storage.player_log import PlayerLogStore

LEGACY_DDL = (
    'CREATE TABLE "player_log" ("id" INTEGER NOT NULL PRIMARY KEY, '
    '"battlenet_id" INTEGER NOT NULL, "name" VARCHAR(255) NOT NULL, '
    '"realm" INTEGER NOT NULL, "region" VARCHAR(255) NOT NULL, '
    '"account_id" INTEGER NOT NULL, "match_status" VARCHAR(255) NOT NULL '
    "CHECK (match_status IN ('victory', 'defeat', 'tie')), "
    '"mmr" INTEGER NOT NULL, "created_at" DATETIME NOT NULL)'
)


def make_v1(path):
    conn = sqlite3.connect(path)
    conn.execute(LEGACY_DDL)
    conn.execute('CREATE INDEX "playerlog_battlenet_id" ON "player_log" ("battlenet_id")')
    rows = [
        (315071, "Serral#769", 1, "EU", 236695, "victory", 7000, "2025-01-01 10:00:00.000000"),
        (315071, "Serral#769", 1, "EU", 236695, "defeat", 7010, "2025-02-01 10:00:00.000000"),
        (999, "Other#1", 1, "US", 5, "tie", 3000, "2025-03-01 10:00:00"),
    ]
    conn.executemany(
        "INSERT INTO player_log (battlenet_id, name, realm, region, account_id, match_status, "
        "mmr, created_at) VALUES (?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()


def serral(fixture_json) -> LadderDistinctCharacter:
    return TypeAdapter(list[LadderDistinctCharacter]).validate_python(
        fixture_json("characters_query")
    )[0]


def ctx_and_profiles(fixture_json, *, game_id=1, opp_result="Defeat"):
    me = GamePlayer(id=1, name="Me", type="user", race="Terr", result="Victory")
    opp = GamePlayer(id=2, name="Serral", type="user", race="Zerg", result=opp_result)
    ctx = GameContext(
        game_id=game_id,
        started_at=datetime(2026, 10, 19, 12, tzinfo=UTC),
        players=(me, opp),
        me=me,
        allies=(),
        opponents=(opp,),
        mode="1v1",
        vs_ai=False,
    )
    cand = serral(fixture_json)
    prof = OpponentProfile(
        seed=GameSeed("Serral", "ZERG"),
        identity=Identity(
            character=cand.members.character,
            clan=cand.members.clan,
            pro=cand.members.pro_player,
            candidate=cand,
            confidence=0.9,
        ),
    )
    return GameResult(context=ctx, my_result="victory", display_time=612.4), {0: prof}


def test_migration_from_v1(tmp_path):
    path = tmp_path / "player_log.sqlite3"
    make_v1(path)
    db = init_db(path)
    assert schema_version(db) == len(MIGRATIONS)
    store = PlayerLogStore(db)
    rows = store.rows_for("EU", 315071)
    assert [r.match_status for r in rows] == ["defeat", "victory"]  # newest first
    assert [r.my_result for r in rows] == ["victory", "defeat"]  # backfilled inverse
    assert rows[0].created_at.tzinfo is not None
    assert store.all_rows()[0].my_result == "tie"
    h = head_to_head(rows)
    assert (h.games, h.wins, h.losses, h.ties) == (2, 1, 1, 0)
    db.close()
    # re-opening is a no-op
    db = init_db(path)
    assert len(PlayerLogStore(db).all_rows()) == 3
    db.close()


def test_record_game_idempotent(tmp_path, fixture_json):
    db = init_db(tmp_path / "db.sqlite3")
    store = PlayerLogStore(db)
    result, profiles = ctx_and_profiles(fixture_json)
    assert store.record_game(result, profiles) == 1
    assert store.record_game(result, profiles) == 0
    rows = store.rows_for("EU", 315071)
    assert len(rows) == 1
    r = rows[0]
    assert r.match_status == "defeat" and r.my_result == "victory"
    assert r.mode == "1v1" and r.my_race == "TERRAN" and r.opp_race == "ZERG"
    assert r.game_seconds == 612 and r.character_id == 236695
    assert r.mmr == 7065  # no RATING stage: candidate rating used
    # same opponent, different game -> new row
    result2, profiles2 = ctx_and_profiles(fixture_json, game_id=2)
    assert store.record_game(result2, profiles2) == 1
    db.close()


def test_record_game_skips_unresolved_and_unknown(tmp_path, fixture_json):
    db = init_db(tmp_path / "db.sqlite3")
    store = PlayerLogStore(db)
    result, profiles = ctx_and_profiles(fixture_json)
    unresolved = {0: OpponentProfile(seed=GameSeed("Serral", "ZERG"))}
    assert store.record_game(result, unresolved) == 0
    undecided, profs = ctx_and_profiles(fixture_json, opp_result="Undecided")
    unknown = GameResult(context=undecided.context, my_result=None, display_time=0)
    assert store.record_game(unknown, profs) == 0
    db.close()


def test_head_to_head_none():
    assert head_to_head([]) is None
