from typing import Dict, List, Optional

from pydantic import BaseModel

from smurfsniper.api import sc2pulse
from smurfsniper.models.team_history import TeamHistory


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

    @classmethod
    def merge(cls, members: list["TeamMember"]) -> "TeamMember":
        if not members:
            raise ValueError("No TeamMember objects provided for merge")

        first_member = members[0]

        protoss = sum(m.protossGamesPlayed or 0 for m in members)
        terran = sum(m.terranGamesPlayed or 0 for m in members)
        zerg = sum(m.zergGamesPlayed or 0 for m in members)
        random_games = sum(m.randomGamesPlayed or 0 for m in members)

        merged_race_games: dict[str, int] = {}
        for m in members:
            for race, value in m.raceGames.items():
                merged_race_games[race] = merged_race_games.get(race, 0) + value

        return cls(
            protossGamesPlayed=protoss,
            terranGamesPlayed=terran,
            zergGamesPlayed=zerg,
            randomGamesPlayed=random_games,
            raceGames=merged_race_games,
            character=first_member.character,
            account=first_member.account,
            clan=first_member.clan,
        )


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

    _match_history_cache: Optional[TeamHistory] = None

    @classmethod
    def merge(cls, teams: List["Team"]) -> "Team":
        if not teams:
            raise ValueError("No teams provided for merge")

        most_recent = max(
            teams, key=lambda t: t.lastPlayed or t.primaryDataUpdated or t.joined or ""
        )

        first_joined = min(
            [team for team in teams if team.joined], key=lambda t: t.joined
        ).joined

        total_wins = sum(t.wins for t in teams)
        total_losses = sum(t.losses for t in teams)
        total_ties = sum(t.ties for t in teams)

        members_by_id: dict[int, list[TeamMember]] = {}

        for team in teams:
            for member in team.members:
                bid = member.character.battlenetId
                members_by_id.setdefault(bid, []).append(member)

        merged_members = [
            TeamMember.merge(member_group) for member_group in members_by_id.values()
        ]

        return cls(
            wins=total_wins,
            losses=total_losses,
            ties=total_ties,
            rating=most_recent.rating,
            id=most_recent.id,
            legacyId=most_recent.legacyId,
            divisionId=most_recent.divisionId,
            season=most_recent.season,
            region=most_recent.region,
            league=most_recent.league,
            globalRank=most_recent.globalRank,
            regionRank=most_recent.regionRank,
            leagueRank=most_recent.leagueRank,
            lastPlayed=most_recent.lastPlayed,
            joined=first_joined,
            primaryDataUpdated=most_recent.primaryDataUpdated,
            members=merged_members,
            globalTeamCount=most_recent.globalTeamCount,
            regionTeamCount=most_recent.regionTeamCount,
            leagueTeamCount=most_recent.leagueTeamCount,
            queueType=most_recent.queueType,
            teamType=most_recent.teamType,
            leagueType=most_recent.leagueType,
            legacyUid=most_recent.legacyUid,
        )

    @property
    def match_history(self) -> Optional[TeamHistory]:

        if self._match_history_cache is not None:
            return self._match_history_cache

        if not self.legacyUid:
            return None

        data = sc2pulse.team_histories([self.legacyUid])
        history = sc2pulse.parse_team_history(data, legacy_uid=self.legacyUid)

        self._match_history_cache = history
        return history
