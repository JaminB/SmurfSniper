from pathlib import Path
from typing import List, Optional

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


# -------------------- Preferences -------------------- #


class OverlayPreferences(BaseModel):
    seconds_visible: int


class Preferences(BaseModel):
    overlay_1v1: OverlayPreferences
    overlay_2v2: OverlayPreferences

    @classmethod
    def from_yaml(cls, data: dict) -> "Preferences":
        """Handle keys the user writes (1v1_overlay) -> model fields (overlay_1v1)."""
        return cls(
            overlay_1v1=OverlayPreferences(**data["1v1_overlay"]),
            overlay_2v2=OverlayPreferences(**data["2v2_overlay"]),
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
