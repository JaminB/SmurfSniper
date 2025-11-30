import httpx
from typing import Optional, List, Dict
from pydantic import BaseModel

from sc_match_briefer.models.team import Team


import httpx
from typing import Optional, List
from pydantic import BaseModel, PrivateAttr

from sc_match_briefer.models.team import Team


class Character(BaseModel):
    realm: int
    name: str
    id: int
    accountId: int
    region: str
    battlenetId: int
    tag: Optional[str] = None
    discriminator: Optional[int] = None

    _team_cache: Optional[List[Team]] = PrivateAttr(default=None)

    @property
    def teams(self) -> List[Team]:
        url = (
            "https://sc2pulse.nephest.com/sc2/api/character-teams"
            f"?characterId={self.id}"
        )

        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url)
            resp.raise_for_status()
            data = resp.json()

        teams = [Team.model_validate(entry) for entry in data]
        self._team_cache = teams
        return teams

