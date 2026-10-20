"""SC2Pulse identifiers, enums and id builders."""

from __future__ import annotations

from enum import IntEnum, StrEnum


class Queue(IntEnum):
    """Ladder queue. Sent to the API by name (``LOTV_1V1``)."""

    __param_by_name__ = True

    LOTV_1V1 = 201
    LOTV_2V2 = 202
    LOTV_3V3 = 203
    LOTV_4V4 = 204
    LOTV_ARCHON = 206


class TeamType(IntEnum):
    __param_by_name__ = True

    ARRANGED = 0
    RANDOM = 1


class League(IntEnum):
    __param_by_name__ = True

    BRONZE = 0
    SILVER = 1
    GOLD = 2
    PLATINUM = 3
    DIAMOND = 4
    MASTER = 5
    GRANDMASTER = 6

    @property
    def label(self) -> str:
        return self.name.title()


class MatchType(StrEnum):
    _1V1 = "_1V1"
    _2V2 = "_2V2"
    _3V3 = "_3V3"
    _4V4 = "_4V4"
    ARCHON = "ARCHON"
    COOP = "COOP"
    CUSTOM = "CUSTOM"
    UNKNOWN = "UNKNOWN"


class LinkType(StrEnum):
    ALIGULAC = "ALIGULAC"
    TWITCH = "TWITCH"
    LIQUIPEDIA = "LIQUIPEDIA"
    TWITTER = "TWITTER"
    INSTAGRAM = "INSTAGRAM"
    DISCORD = "DISCORD"
    YOUTUBE = "YOUTUBE"
    BATTLE_NET = "BATTLE_NET"
    REPLAY_STATS = "REPLAY_STATS"
    BILIBILI = "BILIBILI"
    UNKNOWN = "UNKNOWN"


class HistoryColumn(StrEnum):
    TIMESTAMP = "TIMESTAMP"
    RATING = "RATING"
    GAMES = "GAMES"
    GAMES_DELTA = "GAMES_DELTA"
    WINS = "WINS"
    LEAGUE_TYPE = "LEAGUE_TYPE"
    TIER_TYPE = "TIER_TYPE"
    DIVISION_BATTLENET_ID = "DIVISION_BATTLENET_ID"
    GLOBAL_RANK = "GLOBAL_RANK"
    REGION_RANK = "REGION_RANK"
    LEAGUE_RANK = "LEAGUE_RANK"
    GLOBAL_TEAM_COUNT = "GLOBAL_TEAM_COUNT"
    REGION_TEAM_COUNT = "REGION_TEAM_COUNT"
    LEAGUE_TEAM_COUNT = "LEAGUE_TEAM_COUNT"
    SEASON = "SEASON"
    SOURCE = "SOURCE"


class SummaryColumn(StrEnum):
    GAMES = "GAMES"
    LEAGUE_TYPE_MAX = "LEAGUE_TYPE_MAX"
    RATING_MIN = "RATING_MIN"
    RATING_AVG = "RATING_AVG"
    RATING_MAX = "RATING_MAX"
    RATING_LAST = "RATING_LAST"
    REGION_RANK_LAST = "REGION_RANK_LAST"
    REGION_TEAM_COUNT_LAST = "REGION_TEAM_COUNT_LAST"


REGION_IDS = {"US": 1, "EU": 2, "KR": 3, "CN": 5}
RACE_IDS = {"TERRAN": 1, "PROTOSS": 2, "ZERG": 3, "RANDOM": 4}
RACES = tuple(RACE_IDS)


def solo_legacy_uid(
    queue: Queue, region: str, realm: int, battlenet_id: int, race: str | None
) -> str:
    """1v1 team legacy UID, e.g. ``201-0-2-1.315071.3``. ``race=None`` gives ``*``."""
    race_part = RACE_IDS[race.upper()] if race else "*"
    return f"{int(queue)}-0-{REGION_IDS[region]}-{realm}.{battlenet_id}.{race_part}"


def toon_handle(region: str, realm: int, battlenet_id: int) -> str:
    """``regionId-S2-realm-battlenetId``, e.g. ``2-S2-1-315071``."""
    return f"{REGION_IDS[region]}-S2-{realm}-{battlenet_id}"
