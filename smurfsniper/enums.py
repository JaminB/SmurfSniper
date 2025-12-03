from enum import Enum


class Region(Enum):
    US = 1
    EU = 2
    KR = 3
    CN = 5


class RaceCode(Enum):
    TERRAN = 1
    PROTOSS = 2
    ZERG = 3
    RANDOM = 4

    @classmethod
    def from_alias(cls, alias: str) -> "RaceCode":
        if not alias:
            raise ValueError("Empty race alias")

        normalized = alias.strip().lower()

        mapping = {
            "terr": cls.TERRAN,
            "terran": cls.TERRAN,
            "prot": cls.PROTOSS,
            "protoss": cls.PROTOSS,
            "zerg": cls.ZERG,
            "rand": cls.RANDOM,
            "random": cls.RANDOM,
        }

        try:
            return mapping[normalized]
        except KeyError:
            try:
                return cls[alias.upper()]
            except KeyError:
                raise ValueError(f"Unknown race alias: {alias!r}")


class TeamFormat(Enum):
    _1V1 = 201
    _2V2 = 202
    _3V3 = 203
    _4V4 = 204
    ARCHON = 206


class TeamType(Enum):
    ARRANGED = 0
    RANDOM = 1


from enum import IntEnum


class League(IntEnum):
    BRONZE = 0
    SILVER = 1
    GOLD = 2
    PLATINUM = 3
    DIAMOND = 4
    MASTER = 5
    GRANDMASTER = 6

    @classmethod
    def from_int(cls, value: int) -> "League":
        return cls(value)
