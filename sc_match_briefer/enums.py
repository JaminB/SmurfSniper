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


class TeamFormat(Enum):
    _1V1 = 201
    _2V2 = 202
    _3V3 = 203
    _4V4 = 204
    ARCHON = 206


class TeamType(Enum):
    ARRANGED = 0
    RANDOM = 1
