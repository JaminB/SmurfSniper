from typing import Dict, List, Optional

from pydantic import BaseModel


class TeamLeague(BaseModel):
    type: int
    queueType: int
    teamType: int


class Clan(BaseModel):
    tag: Optional[str] = None
    id: Optional[int] = None
    region: Optional[str] = None
    name: Optional[str] = None
    members: Optional[int] = None
    activeMembers: Optional[int] = None
    avgRating: Optional[int] = None
    avgLeagueType: Optional[int] = None
    games: Optional[int] = None


class Character(BaseModel):
    realm: int
    name: str
    id: int
    accountId: int
    region: str
    battlenetId: int
    tag: Optional[str] = None
    discriminator: Optional[int] = None


class Account(BaseModel):
    battleTag: str
    id: int
    partition: str
    hidden: Optional[bool] = None
    tag: Optional[str] = None
    discriminator: Optional[int] = None


class TeamMember(BaseModel):
    protossGamesPlayed: Optional[int] = 0
    terranGamesPlayed: Optional[int] = 0
    zergGamesPlayed: Optional[int] = 0
    randomGamesPlayed: Optional[int] = 0

    character: Character
    account: Account
    clan: Optional[Clan] = None

    raceGames: Dict[str, int]


class Team(BaseModel):
    rating: int
    wins: int
    losses: int
    ties: int

    id: int
    legacyId: str
    divisionId: Optional[int]
    season: int
    region: str

    league: TeamLeague

    globalRank: Optional[int] = None
    regionRank: Optional[int] = None
    leagueRank: Optional[int] = None

    lastPlayed: Optional[str] = None
    joined: Optional[str] = None
    primaryDataUpdated: Optional[str] = None

    members: List[TeamMember]

    globalTeamCount: Optional[int] = None
    regionTeamCount: Optional[int] = None
    leagueTeamCount: Optional[int] = None

    queueType: int
    teamType: int
    leagueType: int

    legacyUid: str
