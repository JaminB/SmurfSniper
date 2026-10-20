"""Local SC2 client API models (``/game`` and ``/ui``)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

_RACE_CODES = {
    "terr": "TERRAN",
    "terran": "TERRAN",
    "prot": "PROTOSS",
    "protoss": "PROTOSS",
    "zerg": "ZERG",
    "rand": "RANDOM",
    "random": "RANDOM",
}

RESULTS = {"Victory", "Defeat", "Tie"}


def race_code(race: str | None) -> str | None:
    """``Terr``/``Prot``/``Zerg``/``random`` -> ``TERRAN``/``PROTOSS``/``ZERG``/``RANDOM``."""
    if not race:
        return None
    return _RACE_CODES.get(race.strip().lower())


class _Model(BaseModel):
    model_config = ConfigDict(
        extra="ignore", populate_by_name=True, alias_generator=to_camel, frozen=True
    )


class GamePlayer(_Model):
    id: int
    name: str
    type: Literal["user", "computer"] | str = "user"
    race: str = ""
    result: str = "Undecided"

    @property
    def is_human(self) -> bool:
        return self.type == "user"

    @property
    def race_code(self) -> str | None:
        return race_code(self.race)

    @property
    def has_result(self) -> bool:
        return self.result in RESULTS


class GameInfo(_Model):
    is_replay: bool = False
    display_time: float = 0.0
    players: list[GamePlayer] = Field(default_factory=list)

    @property
    def humans(self) -> list[GamePlayer]:
        return [p for p in self.players if p.is_human]

    @property
    def has_result(self) -> bool:
        return any(p.has_result for p in self.players)


class UiInfo(_Model):
    active_screens: list[str] = Field(default_factory=list)

    @property
    def loading(self) -> bool:
        return any("ScreenLoading" in s for s in self.active_screens)
