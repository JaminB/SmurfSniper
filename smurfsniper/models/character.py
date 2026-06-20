from typing import List, Optional

from pydantic import BaseModel, PrivateAttr

from smurfsniper.api import sc2pulse
from smurfsniper.models.team import Team


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
        if self._team_cache is not None:
            return self._team_cache

        data = sc2pulse.character_teams(self.id)
        teams = [Team.model_validate(entry) for entry in data]
        self._team_cache = teams
        return teams
