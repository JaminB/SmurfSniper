import httpx
from typing import Optional, Dict, List
from pydantic import BaseModel


class PreviousStats(BaseModel):
    rating: int
    gamesPlayed: int
    rank: int


class CurrentStats(BaseModel):
    rating: int
    gamesPlayed: int
    rank: int


class Character(BaseModel):
    realm: int
    name: str
    id: int
    accountId: int
    region: str
    battlenetId: int
    tag: str
    discriminator: Optional[int]


class Account(BaseModel):
    battleTag: str
    id: int
    partition: str
    hidden: Optional[bool]
    tag: str
    discriminator: Optional[int]


class Clan(BaseModel):
    tag: Optional[str]
    id: Optional[int]
    region: Optional[str]
    name: Optional[str]
    members: Optional[int]
    activeMembers: Optional[int]
    avgRating: Optional[int]
    avgLeagueType: Optional[int]
    games: Optional[int]


class Members(BaseModel):
    protossGamesPlayed: Optional[int]
    character: Character
    account: Account
    clan: Clan
    raceGames: Dict[str, int]


class PlayerEntry(BaseModel):
    leagueMax: int
    ratingMax: int
    totalGamesPlayed: int
    previousStats: PreviousStats
    currentStats: CurrentStats
    members: Members


class SC2CharacterResult(BaseModel):
    leagueMax: int
    ratingMax: int
    totalGamesPlayed: int
    previousStats: PreviousStats
    currentStats: CurrentStats
    members: Members


class Player(BaseModel):
    id: int
    name: str
    type: str
    race: str
    result: str

    def lookup(self) -> List[SC2CharacterResult]:
        """Search SC2Pulse API for characters matching a name."""
        url = f"https://sc2pulse.nephest.com/sc2/api/characters?query={self.name}"

        with httpx.Client(timeout=10.0) as client:
            response = client.get(url)
            response.raise_for_status()
            data = response.json()

        return [SC2CharacterResult.model_validate(entry) for entry in data]


player = {
    "id": 1,
    "name": "CheeseGawd",
    "type": "user",
    "race": "Prot",
    "result": "Undecided"
}

print(Player.model_validate(player).lookup())
