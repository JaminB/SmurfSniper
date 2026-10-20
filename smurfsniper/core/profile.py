"""Opponent profile: per-stage results produced by the lookup pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from smurfsniper.analyze.h2h import H2HInfo
from smurfsniper.analyze.history import Record, Trend
from smurfsniper.analyze.matches import RecentResult
from smurfsniper.analyze.smurf import SmurfAssessment
from smurfsniper.analyze.team import TeamInfo
from smurfsniper.api.aligulac.models import AligulacPlayer
from smurfsniper.api.liquipedia.models import PageSummary
from smurfsniper.api.sc2pulse.models import (
    Character,
    Clan,
    LadderDistinctCharacter,
    LadderTeam,
    ProPlayerEntry,
    SocialLink,
)

__all__ = [
    "GameSeed",
    "H2HInfo",
    "Identity",
    "IntelInfo",
    "LookupUpdate",
    "OpponentProfile",
    "RatingInfo",
    "SmurfInfo",
    "Stage",
    "TeamInfo",
    "TendenciesInfo",
]


class Stage(StrEnum):
    GAME = "game"
    IDENTITY = "identity"
    RATING = "rating"
    SMURF = "smurf"
    H2H = "h2h"
    TENDENCIES = "tendencies"
    INTEL = "intel"
    TEAM = "team"


@dataclass(frozen=True)
class GameSeed:
    name: str
    race: str | None  # TERRAN / PROTOSS / ZERG / RANDOM


@dataclass(frozen=True)
class Identity:
    character: Character
    clan: Clan | None
    pro: ProPlayerEntry | None
    candidate: LadderDistinctCharacter
    confidence: float
    exact_matches: int = 1  # how many SC2Pulse characters share the base name


@dataclass(frozen=True)
class RatingInfo:
    mmr: int | None
    league: int | None
    tier: int | None  # 0 = tier 1 (top of the league)
    region_percentile: float | None
    season_wins: int | None
    season_losses: int | None
    peak_mmr: int | None
    peak_league: int | None
    mmr_to_next_tier: int | None
    team: LadderTeam | None


@dataclass(frozen=True)
class SmurfInfo:
    assessment: SmurfAssessment
    trend: Trend | None
    sparkline: str | None
    records: dict[str, Record]  # keys "3d","7d","30d","season"; only windows with games


@dataclass(frozen=True)
class TendenciesInfo:
    recent: list[RecentResult]
    maps: dict[str, Record]
    avg_duration_s: int | None


@dataclass(frozen=True)
class IntelInfo:
    pro: ProPlayerEntry | None
    aligulac: AligulacPlayer | None
    liquipedia: PageSummary | None
    links: list[SocialLink] = field(default_factory=list)


@dataclass(frozen=True)
class LookupUpdate:
    game_id: int
    slot: int  # opponent index in GameContext.opponents; -1 for TEAM
    stage: Stage
    data: object | None  # None == stage finished with nothing to show
    error: str | None = None


@dataclass
class OpponentProfile:
    """Accumulates stage results for one opponent."""

    seed: GameSeed
    identity: Identity | None = None
    rating: RatingInfo | None = None
    smurf: SmurfInfo | None = None
    h2h: H2HInfo | None = None
    tendencies: TendenciesInfo | None = None
    intel: IntelInfo | None = None
    finished: set[Stage] = field(default_factory=set)
    errors: dict[Stage, str] = field(default_factory=dict)

    _FIELDS = {
        Stage.IDENTITY: "identity",
        Stage.RATING: "rating",
        Stage.SMURF: "smurf",
        Stage.H2H: "h2h",
        Stage.TENDENCIES: "tendencies",
        Stage.INTEL: "intel",
    }

    def apply(self, u: LookupUpdate) -> bool:
        """Record an update; returns True if anything changed."""
        changed = u.stage not in self.finished
        self.finished.add(u.stage)
        if u.error:
            changed = changed or self.errors.get(u.stage) != u.error
            self.errors[u.stage] = u.error
        if u.stage is Stage.GAME and isinstance(u.data, GameSeed):
            changed = changed or self.seed != u.data
            self.seed = u.data
            return changed
        attr = self._FIELDS.get(u.stage)
        if attr is not None and u.data is not None and getattr(self, attr) != u.data:
            setattr(self, attr, u.data)
            changed = True
        return changed

    def done(self, stage: Stage) -> bool:
        return stage in self.finished

    def copy(self) -> OpponentProfile:
        return OpponentProfile(
            seed=self.seed,
            identity=self.identity,
            rating=self.rating,
            smurf=self.smurf,
            h2h=self.h2h,
            tendencies=self.tendencies,
            intel=self.intel,
            finished=set(self.finished),
            errors=dict(self.errors),
        )


def ago(ts: datetime, now: datetime) -> str:
    """Compact relative time: ``5m``, ``3h``, ``2d``, ``3w``, ``4mo``, ``2y``."""
    secs = max(0, int((now - ts).total_seconds()))
    if secs < 3600:
        return f"{max(1, secs // 60)}m"
    if secs < 86400:
        return f"{secs // 3600}h"
    days = secs // 86400
    if days < 14:
        return f"{days}d"
    if days < 60:
        return f"{days // 7}w"
    if days < 730:
        return f"{days // 30}mo"
    return f"{days // 365}y"
