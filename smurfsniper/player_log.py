# smurfsniper/models/player_log.py

from datetime import datetime
from pathlib import Path

from peewee import CharField, Check, DateTimeField, IntegerField, Model, SqliteDatabase
from platformdirs import user_data_dir

from smurfsniper.models.player import Player, PlayerStats

APP_NAME = "smurfsniper"
APP_AUTHOR = "smurfsniper"

data_dir = Path(user_data_dir(APP_NAME, APP_AUTHOR))
data_dir.mkdir(parents=True, exist_ok=True)

db_path = data_dir / "player_log.sqlite3"

db = SqliteDatabase(
    db_path,
    pragmas={
        "journal_mode": "wal",
        "cache_size": -64 * 1000,
        "foreign_keys": 1,
    },
)


class BaseModel(Model):
    class Meta:
        database = db


class PlayerLog(BaseModel):
    battlenet_id = IntegerField(index=True)

    name = CharField()
    realm = IntegerField()
    region = CharField()
    account_id = IntegerField()

    match_status = CharField(
        constraints=[Check("match_status IN ('victory', 'defeat', 'tie')")]
    )

    mmr = IntegerField()
    created_at = DateTimeField(default=datetime.utcnow)

    class Meta:
        table_name = "player_log"
        order_by = ("-created_at",)

    @classmethod
    def from_player(cls, player: Player, max_mmr: int, min_mmr: int, match_status: str):
        return cls.from_player_stats(
            player.get_player_stats(min_mmr, max_mmr), match_status=match_status
        )

    @classmethod
    def from_player_stats(
        cls,
        stats: PlayerStats,
        match_status: str,
    ) -> "PlayerLog":

        if match_status not in {"victory", "defeat", "tie"}:
            raise ValueError("match_status must be one of: victory, defeat, tie")

        mmr = stats.currentStats.rating
        if mmr is None:
            raise ValueError("currentStats.rating is required to log MMR")

        character = stats.members.character

        return cls(
            battlenet_id=character.battlenetId,
            name=character.name,
            realm=character.realm,
            region=character.region,
            account_id=character.accountId,
            match_status=match_status,
            mmr=mmr,
        )

    @classmethod
    def most_recent(cls):
        return cls.select().order_by(cls.id.desc()).first()


def init_player_log_db() -> None:
    db.connect(reuse_if_open=True)
    db.create_tables([PlayerLog])
