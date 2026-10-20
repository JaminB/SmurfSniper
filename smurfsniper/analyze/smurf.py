"""Graded 0-100 smurf score with reasons.

Branch weights (identical to the original heuristic):

| code    | rule                                         | points |
|---------|----------------------------------------------|--------|
| wr3d    | 3-day winrate >= 80% with 5+ games           | +35    |
| wr7d    | 7-day winrate >= 75% with 8+ games           | +25    |
| wrlife  | lifetime winrate >= 70% with 30+ games       | +15    |
| age     | account <= 14 days (+30) or <= 30 days (+18) |        |
| climb   | >= 15 MMR/day (+20) or >= 8 MMR/day (+10)    |        |

Age and climb need at least 5 rating points. The total is capped at 100.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from smurfsniper.analyze.history import (
    GameOutcome,
    RatingPoint,
    account_age_days,
    climb_velocity,
    record,
)
from smurfsniper.api.sc2pulse.models import LadderDistinctCharacter

Level = Literal["none", "suspicious", "possible", "likely"]
LEVELS: tuple[tuple[int, Level], ...] = ((70, "likely"), (45, "possible"), (25, "suspicious"))
MIN_POINTS = 5


@dataclass(frozen=True)
class SmurfReason:
    code: str
    text: str
    points: int


@dataclass(frozen=True)
class SmurfAssessment:
    score: int
    level: Level
    reasons: tuple[SmurfReason, ...] = ()

    @property
    def top_reason(self) -> SmurfReason | None:
        return self.reasons[0] if self.reasons else None


@dataclass(frozen=True)
class SmurfInputs:
    outcomes: Sequence[GameOutcome]
    points: Sequence[RatingPoint]
    now: datetime
    current_mmr: int | None = None
    current_league: int | None = None
    peak_mmr: int | None = None
    peak_league: int | None = None
    race_games: Mapping[str, int] = field(default_factory=dict)
    current_race: str | None = None
    alt_characters: Sequence[LadderDistinctCharacter] = ()


def level_for(score: int) -> Level:
    for threshold, level in LEVELS:
        if score >= threshold:
            return level
    return "none"


def assess(inp: SmurfInputs) -> SmurfAssessment:
    reasons: list[SmurfReason] = []

    r3 = record(inp.outcomes, days=3, now=inp.now)
    if r3.games >= 5 and r3.wins / r3.games >= 0.80:
        reasons.append(SmurfReason("wr3d", f"3d winrate {r3.wins}/{r3.games}", 35))

    r7 = record(inp.outcomes, days=7, now=inp.now)
    if r7.games >= 8 and r7.wins / r7.games >= 0.75:
        reasons.append(SmurfReason("wr7d", f"7d winrate {r7.wins}/{r7.games}", 25))

    rl = record(inp.outcomes, days=None, now=inp.now)
    if rl.games >= 30 and rl.wins / rl.games >= 0.70:
        reasons.append(SmurfReason("wrlife", f"lifetime winrate {rl.wins / rl.games:.0%}", 15))

    if len(inp.points) >= MIN_POINTS:
        age = account_age_days(inp.points, None, inp.now)
        if age is not None and age <= 14:
            reasons.append(SmurfReason("age", f"new account ({age}d)", 30))
        elif age is not None and age <= 30:
            reasons.append(SmurfReason("age", f"young account ({age}d)", 18))

        v = climb_velocity(inp.points, days=None, now=inp.now)
        if v is not None and v >= 15:
            reasons.append(SmurfReason("climb", f"climb +{v:.0f}/day", 20))
        elif v is not None and v >= 8:
            reasons.append(SmurfReason("climb", f"climb +{v:.0f}/day", 10))

    score = min(100, sum(r.points for r in reasons))
    ordered = tuple(sorted(reasons, key=lambda r: -r.points))
    return SmurfAssessment(score=score, level=level_for(score), reasons=ordered)
