"""Plain row types returned by the stores (no peewee import, usable by ``analyze``)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

_INVERSE = {"victory": "defeat", "defeat": "victory", "tie": "tie"}


def inverse_result(result: str | None) -> str | None:
    """Victory <-> defeat; tie stays tie."""
    return _INVERSE.get(result) if result else None


@dataclass(frozen=True)
class PlayerLogRow:
    id: int
    battlenet_id: int
    name: str
    realm: int
    region: str
    account_id: int | None
    match_status: str  # opponent's result (legacy column)
    mmr: int | None
    created_at: datetime  # UTC, aware
    character_id: int | None = None
    game_uid: str | None = None
    mode: str | None = None
    my_result: str | None = None  # victory/defeat/tie from the user's perspective
    my_race: str | None = None
    opp_race: str | None = None
    game_seconds: int | None = None
    opp_league: int | None = None

    @property
    def result_for_me(self) -> str | None:
        return self.my_result or inverse_result(self.match_status)


@dataclass(frozen=True)
class Session:
    id: int
    started_at: datetime
    ended_at: datetime | None = None
    character_id: int | None = None


@dataclass(frozen=True)
class SessionOpponent:
    name: str
    race: str | None = None
    character_id: int | None = None
    mmr: int | None = None


@dataclass(frozen=True)
class SessionGame:
    """One finished game of a session (``my_result``: victory/defeat/tie)."""

    session_id: int
    game_uid: str
    started_at: datetime
    ended_at: datetime
    mode: str
    my_result: str | None = None
    my_race: str | None = None
    opponents: tuple[SessionOpponent, ...] = ()
    mmr_before: int | None = None
    mmr_after: int | None = None
    game_seconds: int | None = None
    id: int | None = None
