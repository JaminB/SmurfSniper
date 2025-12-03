from pathlib import Path
from typing import List

import yaml
from pydantic import BaseModel


class Me(BaseModel):
    mmr: int
    name: str


class Team(BaseModel):
    name: str
    mmr: int
    members: List[str]

    def __contains__(self, item: str) -> bool:
        """Allows:  if player.name in config.team"""
        return item in self.members


class Config(BaseModel):
    me: Me
    team: Team  # <-- now matches YAML (singular)

    @classmethod
    def from_config_file(cls, path: str | Path) -> "Config":
        path = Path(path)
        with path.open("r") as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)
