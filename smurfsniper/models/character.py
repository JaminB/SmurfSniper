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
    tag: str | None = None
    discriminator: int | None = None

    _team_cache: list[Team] | None = PrivateAttr(default=None)

    @property
    def teams(self) -> list[Team]:
        if self._team_cache is not None:
            return self._team_cache

        data = sc2pulse.character_teams(self.id)
        teams = [Team.model_validate(entry) for entry in data]
        self._team_cache = teams
        return teams
