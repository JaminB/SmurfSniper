"""Graded 0-100 smurf score with reasons.

Branch weights (identical to the original heuristic):

| code    | rule                                         | points |
|---------|----------------------------------------------|--------|
| wr3d    | 3-day winrate >= 80% with 5+ games           | +35    |
| wr7d    | 7-day winrate >= 75% with 8+ games           | +25    |
| wrlife  | lifetime winrate >= 70% with 30+ games       | +15    |
| age     | account <= 14 days (+30) or <= 30 days (+18) |        |
| climb   | >= 15 MMR/day (+20) or >= 8 MMR/day (+10)    |        |
| alt_peak | another character of the account peaked >= 800 (+35) / >= 400 (+20) higher | |
| peak_gap | peak league >= 3 (+25) / >= 2 (+15) above now, or peak MMR >= 1200 / >= 700 above | |
| off_race | current race < 20% of games, main race 100+ games: higher peak (+20) else (+8) | |

Age and climb need at least 5 rating points. The signals that compare against the
current rating (alt_peak, peak_gap and the higher-peak off_race) need ``current_mmr``.
The total is capped at 100.
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
from smurfsniper.api.sc2pulse.ids import League
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
    character_id: int | None = None  # the opponent's own character (excluded from alts)
    race_peaks: Mapping[str, int] = field(default_factory=dict)  # race -> peak 1v1 rating


def level_for(score: int) -> Level:
    for threshold, level in LEVELS:
        if score >= threshold:
            return level
    return "none"


def league_name(league: int | None) -> str | None:
    if league is None:
        return None
    try:
        return League(league).label
    except ValueError:
        return None


def _alt_signal(inp: SmurfInputs) -> SmurfReason | None:
    if not inp.current_mmr:
        return None
    best: LadderDistinctCharacter | None = None
    for alt in inp.alt_characters:
        if inp.character_id is not None and alt.character.id == inp.character_id:
            continue
        if alt.rating_max and (best is None or alt.rating_max > (best.rating_max or 0)):
            best = alt
    if best is None or not best.rating_max:
        return None
    gap = best.rating_max - inp.current_mmr
    points = 35 if gap >= 800 else 20 if gap >= 400 else 0
    if not points:
        return None
    ch = best.character
    return SmurfReason(
        "alt_peak", f"alt {ch.base_name} ({ch.region}) peaked {best.rating_max:,}", points
    )


def _peak_gap_signal(inp: SmurfInputs) -> SmurfReason | None:
    if not inp.current_mmr or not (inp.peak_mmr or inp.peak_league is not None):
        return None
    league_gap = (
        inp.peak_league - inp.current_league
        if inp.peak_league is not None and inp.current_league is not None
        else 0
    )
    mmr_gap = (inp.peak_mmr - inp.current_mmr) if inp.peak_mmr else 0
    if league_gap >= 3 or mmr_gap >= 1200:
        points = 25
    elif league_gap >= 2 or mmr_gap >= 700:
        points = 15
    else:
        return None
    peak = league_name(inp.peak_league) or f"{inp.peak_mmr:,}"
    peak_text = (
        f"{peak} ({inp.peak_mmr:,})" if inp.peak_mmr and league_name(inp.peak_league) else peak
    )
    now = league_name(inp.current_league) or f"{inp.current_mmr:,}"
    return SmurfReason("peak_gap", f"peaked {peak_text}, now {now}", points)


def _off_race_signal(inp: SmurfInputs) -> SmurfReason | None:
    games = {r: n for r, n in inp.race_games.items() if n > 0}
    total = sum(games.values())
    race = inp.current_race
    if not games or not total or not race or race == "RANDOM":
        return None
    main, main_games = max(games.items(), key=lambda kv: kv[1])
    if main == race or main_games < 100 or games.get(race, 0) / total >= 0.20:
        return None
    label = main.title()
    peak = inp.race_peaks.get(main)
    if inp.current_mmr and peak and peak >= inp.current_mmr + 300:
        return SmurfReason("off_race", f"off-racing: main {label} peaked {peak:,}", 20)
    return SmurfReason("off_race", f"off-racing (main {label})", 8)


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

    reasons.extend(r for r in (_alt_signal(inp), _peak_gap_signal(inp), _off_race_signal(inp)) if r)

    score = min(100, sum(r.points for r in reasons))
    ordered = tuple(sorted(reasons, key=lambda r: -r.points))
    return SmurfAssessment(score=score, level=level_for(score), reasons=ordered)
