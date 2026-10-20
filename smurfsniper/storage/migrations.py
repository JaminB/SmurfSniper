"""Ordered schema migrations. ``MIGRATIONS[i]`` upgrades schema version i to i+1."""

from __future__ import annotations

from collections.abc import Callable

from peewee import SqliteDatabase

_LEGACY_COLUMNS = "id, battlenet_id, name, realm, region, account_id, match_status, mmr, created_at"


def m001_initial(db: SqliteDatabase) -> None:
    """The legacy ``player_log`` table, exactly as peewee created it before v2."""
    db.execute_sql(
        "CREATE TABLE IF NOT EXISTS player_log ("
        "id INTEGER NOT NULL PRIMARY KEY, "
        "battlenet_id INTEGER NOT NULL, "
        "name VARCHAR(255) NOT NULL, "
        "realm INTEGER NOT NULL, "
        "region VARCHAR(255) NOT NULL, "
        "account_id INTEGER NOT NULL, "
        "match_status VARCHAR(255) NOT NULL "
        "CHECK (match_status IN ('victory', 'defeat', 'tie')), "
        "mmr INTEGER NOT NULL, "
        "created_at DATETIME NOT NULL)"
    )
    db.execute_sql(
        "CREATE INDEX IF NOT EXISTS player_log_battlenet_id ON player_log (battlenet_id)"
    )


def m002_player_log_v2(db: SqliteDatabase) -> None:
    """Add v2 columns and make ``mmr``/``account_id`` nullable.

    SQLite cannot drop NOT NULL with ALTER TABLE, so the table is rebuilt (equivalent
    to ``ADD COLUMN`` for each new column) and ``my_result`` is backfilled as the
    inverse of the opponent's ``match_status``.
    """
    db.execute_sql(
        "CREATE TABLE player_log_v2 ("
        "id INTEGER NOT NULL PRIMARY KEY, "
        "battlenet_id INTEGER NOT NULL, "
        "name VARCHAR(255) NOT NULL, "
        "realm INTEGER NOT NULL, "
        "region VARCHAR(255) NOT NULL, "
        "account_id INTEGER NULL, "
        "match_status VARCHAR(255) NOT NULL "
        "CHECK (match_status IN ('victory', 'defeat', 'tie')), "
        "mmr INTEGER NULL, "
        "created_at DATETIME NOT NULL, "
        "character_id INTEGER NULL, "
        "game_uid TEXT NULL, "
        "mode TEXT NULL, "
        "my_result TEXT NULL, "
        "my_race TEXT NULL, "
        "opp_race TEXT NULL, "
        "game_seconds INTEGER NULL, "
        "opp_league INTEGER NULL)"
    )
    db.execute_sql(
        f"INSERT INTO player_log_v2 ({_LEGACY_COLUMNS}) SELECT {_LEGACY_COLUMNS} FROM player_log"
    )
    db.execute_sql("DROP TABLE player_log")
    db.execute_sql("ALTER TABLE player_log_v2 RENAME TO player_log")
    db.execute_sql(
        "CREATE INDEX IF NOT EXISTS player_log_battlenet_id ON player_log (battlenet_id)"
    )
    db.execute_sql(
        "CREATE UNIQUE INDEX IF NOT EXISTS player_log_game_uid "
        "ON player_log (game_uid, battlenet_id, region) WHERE game_uid IS NOT NULL"
    )
    db.execute_sql(
        "UPDATE player_log SET my_result = CASE match_status "
        "WHEN 'victory' THEN 'defeat' WHEN 'defeat' THEN 'victory' ELSE 'tie' END "
        "WHERE my_result IS NULL"
    )


MIGRATIONS: tuple[Callable[[SqliteDatabase], None], ...] = (m001_initial, m002_player_log_v2)
