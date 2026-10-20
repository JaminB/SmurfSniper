"""Opponent encounter log (schema v2) and its store."""

from __future__ import annotations

import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from peewee import (
    SQL,
    CharField,
    Check,
    DatabaseProxy,
    DateTimeField,
    IntegerField,
    Model,
    SqliteDatabase,
    TextField,
)

from smurfsniper.logger import logger
from smurfsniper.storage.rows import PlayerLogRow, inverse_result

if TYPE_CHECKING:
    from smurfsniper.core.game_state import GameResult
    from smurfsniper.core.profile import OpponentProfile

database_proxy = DatabaseProxy()
_write_lock = threading.Lock()
_RESULTS = {"victory", "defeat", "tie"}


class PlayerLog(Model):
    battlenet_id = IntegerField(index=True)
    name = CharField()
    realm = IntegerField()
    region = CharField()
    account_id = IntegerField(null=True)
    match_status = CharField(constraints=[Check("match_status IN ('victory', 'defeat', 'tie')")])
    mmr = IntegerField(null=True)
    created_at = DateTimeField()
    character_id = IntegerField(null=True)
    game_uid = TextField(null=True)
    mode = TextField(null=True)
    my_result = TextField(null=True)
    my_race = TextField(null=True)
    opp_race = TextField(null=True)
    game_seconds = IntegerField(null=True)
    opp_league = IntegerField(null=True)

    class Meta:
        database = database_proxy
        table_name = "player_log"


def _naive_utc(dt: datetime) -> datetime:
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    return dt


def _aware(dt: datetime | str) -> datetime:
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt)
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _row(m: PlayerLog) -> PlayerLogRow:
    return PlayerLogRow(
        id=m.id,
        battlenet_id=m.battlenet_id,
        name=m.name,
        realm=m.realm,
        region=m.region,
        account_id=m.account_id,
        match_status=m.match_status,
        mmr=m.mmr,
        created_at=_aware(m.created_at),
        character_id=m.character_id,
        game_uid=m.game_uid,
        mode=m.mode,
        my_result=m.my_result,
        my_race=m.my_race,
        opp_race=m.opp_race,
        game_seconds=m.game_seconds,
        opp_league=m.opp_league,
    )


def game_uid(result: GameResult) -> str:
    ctx = result.context
    return f"{ctx.started_at.isoformat()}|{ctx.game_id}"


class PlayerLogStore:
    """Thread-safe access to the player log. Writes are serialised by a lock."""

    def __init__(self, db: SqliteDatabase):
        self.db = db
        database_proxy.initialize(db)

    def record_game(
        self,
        result: GameResult,
        profiles: Mapping[int, OpponentProfile],
        *,
        now: datetime | None = None,
    ) -> int:
        """One row per opponent with a resolved identity. Idempotent per game.

        Returns the number of rows inserted.
        """
        ctx = result.context
        uid = game_uid(result)
        my_result = result.my_result
        created = _naive_utc(now or datetime.now(UTC))
        inserted = 0
        with _write_lock, self.db.connection_context():
            for slot, prof in profiles.items():
                if prof.identity is None or slot >= len(ctx.opponents):
                    continue
                seat = ctx.opponents[slot]
                if not seat.is_human:
                    continue
                opp = seat.result.lower() if seat.result else None
                opp = opp if opp in _RESULTS else inverse_result(my_result)
                mine = my_result if my_result in _RESULTS else inverse_result(opp)
                if opp not in _RESULTS:
                    logger.info(f"Not logging {seat.name}: game result unknown")
                    continue
                ch = prof.identity.character
                mmr = prof.rating.mmr if prof.rating and prof.rating.mmr else None
                if mmr is None:
                    mmr = prof.identity.candidate.rating
                query = PlayerLog.insert(
                    battlenet_id=ch.battlenet_id,
                    name=ch.name,
                    realm=ch.realm,
                    region=ch.region,
                    account_id=ch.account_id,
                    match_status=opp,
                    mmr=mmr,
                    created_at=created,
                    character_id=ch.id,
                    game_uid=uid,
                    mode=ctx.mode,
                    my_result=mine,
                    my_race=ctx.me.race_code if ctx.me else None,
                    opp_race=seat.race_code,
                    game_seconds=int(result.display_time) if result.display_time else None,
                    opp_league=prof.rating.league if prof.rating else None,
                ).on_conflict_ignore()
                cursor = self.db.execute(query)
                if cursor.rowcount and cursor.rowcount > 0:
                    inserted += 1
        if inserted:
            logger.info(f"Logged {inserted} opponent(s) for game {ctx.game_id}")
        return inserted

    def rows_for(self, region: str, battlenet_id: int) -> list[PlayerLogRow]:
        """Every encounter with one opponent, newest first."""
        with self.db.connection_context():
            q = (
                PlayerLog.select()
                .where((PlayerLog.region == region) & (PlayerLog.battlenet_id == battlenet_id))
                .order_by(PlayerLog.created_at.desc(), PlayerLog.id.desc())
            )
            return [_row(m) for m in q]

    def all_rows(self, since: datetime | None = None) -> list[PlayerLogRow]:
        with self.db.connection_context():
            q = PlayerLog.select().order_by(SQL("created_at DESC"), PlayerLog.id.desc())
            if since is not None:
                q = q.where(PlayerLog.created_at >= _naive_utc(since))
            return [_row(m) for m in q]
