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
        return item in self.members


class OverlayPreferences(BaseModel):
    visible: bool = True
    orientation: str = "horizontal"
    position: str = "top_center"
    seconds_delay_before_show: float = 0.0
    seconds_visible: int = 30

    def to_yaml_dict(self) -> dict:
        return {
            "visible": self.visible,
            "orientation": self.orientation,
            "position": self.position,
            "seconds_delay_before_show": self.seconds_delay_before_show,
            "seconds_visible": self.seconds_visible,
        }


class Preferences(BaseModel):
    overlay_1v1: OverlayPreferences
    overlay_2v2: OverlayPreferences
    overlay_team: OverlayPreferences
    overlay_player_log_1: OverlayPreferences
    overlay_player_log_2: OverlayPreferences
    overlay_external: OverlayPreferences = OverlayPreferences(
        position="top_center"
    )

    @classmethod
    def from_yaml(cls, data: dict) -> "Preferences":
        external_cfg = data.get("external_overlay") or {}
        external = {"position": "top_center", **external_cfg}
        return cls(
            overlay_1v1=OverlayPreferences(**data["1v1_overlay"]),
            overlay_2v2=OverlayPreferences(**data["2v2_overlay"]),
            overlay_team=OverlayPreferences(**data["team_overlay"]),
            overlay_player_log_1=OverlayPreferences(**data["overlay_player_log_1"]),
            overlay_player_log_2=OverlayPreferences(**data["overlay_player_log_2"]),
            overlay_external=OverlayPreferences(**external),
        )

    def to_yaml_dict(self) -> dict:
        """Inverse of from_yaml — emit the on-disk yaml key names."""
        return {
            "1v1_overlay": self.overlay_1v1.to_yaml_dict(),
            "2v2_overlay": self.overlay_2v2.to_yaml_dict(),
            "team_overlay": self.overlay_team.to_yaml_dict(),
            "overlay_player_log_1": self.overlay_player_log_1.to_yaml_dict(),
            "overlay_player_log_2": self.overlay_player_log_2.to_yaml_dict(),
            "external_overlay": self.overlay_external.to_yaml_dict(),
        }

    @classmethod
    def defaults(cls) -> "Preferences":
        return cls(
            overlay_1v1=OverlayPreferences(),
            overlay_2v2=OverlayPreferences(),
            overlay_team=OverlayPreferences(),
            overlay_player_log_1=OverlayPreferences(),
            overlay_player_log_2=OverlayPreferences(),
            overlay_external=OverlayPreferences(),
        )


class Aligulac(BaseModel):
    api_key: str = ""


class Integrations(BaseModel):
    aligulac: Optional[Aligulac] = None


class Config(BaseModel):
    me: Me
    team: Team
    preferences: Optional[Preferences] = None
    integrations: Optional[Integrations] = None

    @classmethod
    def from_config_file(cls, path: str | Path) -> "Config":
        path = Path(path)
        with path.open("r") as f:
            raw = yaml.safe_load(f)

        if "preferences" in raw:
            raw["preferences"] = Preferences.from_yaml(raw["preferences"])

        return cls.model_validate(raw)

    @classmethod
    def defaults(cls) -> "Config":
        """Build a Config from schema defaults for the 'no config found' prefill."""
        return cls(
            me=Me(mmr=2500, name=""),
            team=Team(name="", mmr=2500, members=[]),
            preferences=Preferences.defaults(),
            integrations=Integrations(aligulac=Aligulac()),
        )

    def to_yaml_dict(self) -> dict:
        """Serialize to the on-disk yaml structure (yaml key names)."""
        out: dict = {
            "me": {"mmr": self.me.mmr, "name": self.me.name},
            "team": {
                "name": self.team.name,
                "mmr": self.team.mmr,
                "members": list(self.team.members),
            },
        }
        if self.preferences is not None:
            out["preferences"] = self.preferences.to_yaml_dict()
        # Only emit integrations when there is a real key, so configs that
        # omit the section round-trip cleanly instead of gaining an empty block.
        if (
            self.integrations is not None
            and self.integrations.aligulac is not None
            and self.integrations.aligulac.api_key
        ):
            out["integrations"] = {
                "aligulac": {"api_key": self.integrations.aligulac.api_key}
            }
        return out

    def write_config_file(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(self.to_yaml_dict(), f, sort_keys=False)
