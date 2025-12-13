from pathlib import Path
from typing import List, Optional

import yaml
from pydantic import BaseModel, Field


class Me(BaseModel):
    mmr: int
    name: str


class Team(BaseModel):
    name: str
    mmr: int
    members: List[str]

    def __contains__(self, item: str) -> bool:
        return item in self.members


class OverlayPreferences(BaseModel):
    visible: bool = True
    orientation: str = "horizontal"
    position: str = "top_center"
    seconds_delay_before_show: float = 0.0
    seconds_visible: int = 30


class Preferences(BaseModel):
    overlay_1v1: OverlayPreferences
    overlay_2v2: OverlayPreferences
    overlay_team: OverlayPreferences

    @classmethod
    def from_yaml(cls, data: dict) -> "Preferences":
        return cls(
            overlay_1v1=OverlayPreferences(**data["1v1_overlay"]),
            overlay_2v2=OverlayPreferences(**data["2v2_overlay"]),
            overlay_team=OverlayPreferences(**data["team_overlay"]),
        )


class Config(BaseModel):
    me: Me
    team: Team
    preferences: Optional[Preferences] = None

    @classmethod
    def from_config_file(cls, path: str | Path) -> "Config":
        path = Path(path)
        with path.open("r") as f:
            raw = yaml.safe_load(f)

        if "preferences" in raw:
            raw["preferences"] = Preferences.from_yaml(raw["preferences"])

        return cls.model_validate(raw)
