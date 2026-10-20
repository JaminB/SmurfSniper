"""Pure candidate selection: which SC2Pulse character is the in-game opponent."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from smurfsniper.api.sc2client.models import GamePlayer
from smurfsniper.api.sc2pulse.ids import MatchType, Queue
from smurfsniper.api.sc2pulse.models import LadderDistinctCharacter

if TYPE_CHECKING:
    from smurfsniper.core.profile import GameSeed

REGION_POINTS = 6
WINDOW_POINTS = 3
RACE_POINTS = 1
ACTIVE_POINTS = 1
RUNNER_UP_PENALTY = 0.2
WIDENED_PENALTY = 0.15

_QUEUES = {
    "1v1": Queue.LOTV_1V1,
    "2v2": Queue.LOTV_2V2,
    "3v3": Queue.LOTV_3V3,
    "4v4": Queue.LOTV_4V4,
}
_MATCH_TYPES = {
    "1v1": MatchType._1V1,
    "2v2": MatchType._2V2,
    "3v3": MatchType._3V3,
    "4v4": MatchType._4V4,
}


def queue_for(mode: str) -> Queue:
    return _QUEUES.get(mode, Queue.LOTV_1V1)


def match_type_for(mode: str) -> MatchType:
    return _MATCH_TYPES.get(mode, MatchType._1V1)


def identify_me(players: Sequence[GamePlayer], my_name: str | None) -> GamePlayer | None:
    """The human whose name matches the configured name (case-insensitive)."""
    if not my_name:
        return None
    want = my_name.split("#")[0].strip().casefold()
    for p in players:
        if p.is_human and p.name.casefold() == want:
            return p
    return None


def _base(name: str) -> str:
    return name.split("#")[0].strip().casefold()


def exact_name_matches(
    candidates: Sequence[LadderDistinctCharacter], name: str
) -> list[LadderDistinctCharacter]:
    want = _base(name)
    return [c for c in candidates if _base(c.members.character.name) == want]


def pick_candidate(
    candidates: Sequence[LadderDistinctCharacter],
    seed: GameSeed,
    *,
    region: str | None,
    my_mmr: int | None,
    window: int = 500,
) -> tuple[LadderDistinctCharacter, float] | None:
    """Best exact-name candidate and a 0-1 confidence, or None.

    Scoring: same region +6, rating within ``my_mmr ± window`` +3 (widened to
    ``2*window`` with lower confidence when nobody fits), has played the seen race
    +1, active this season +1. Ties break toward the higher rating.
    """
    pool = exact_name_matches(candidates, seed.name)
    if not pool:
        return None

    widened = False
    if my_mmr is not None:
        in_window = [c for c in pool if c.rating is not None and abs(c.rating - my_mmr) <= window]
        if not in_window:
            widened = True
            window = 2 * window

    max_score = RACE_POINTS + ACTIVE_POINTS
    if region:
        max_score += REGION_POINTS
    if my_mmr is not None:
        max_score += WINDOW_POINTS

    def score(c: LadderDistinctCharacter) -> int:
        s = 0
        if region and c.members.character.region == region:
            s += REGION_POINTS
        if my_mmr is not None and c.rating is not None and abs(c.rating - my_mmr) <= window:
            s += WINDOW_POINTS
        if seed.race and c.members.race_games.get(seed.race, 0) > 0:
            s += RACE_POINTS
        if c.current_stats.games_played:
            s += ACTIVE_POINTS
        return s

    ranked = sorted(pool, key=lambda c: (score(c), c.rating or 0), reverse=True)
    best = ranked[0]
    best_score = score(best)
    confidence = best_score / max_score if max_score else 1.0
    if len(ranked) > 1 and best_score - score(ranked[1]) <= 1:
        confidence -= RUNNER_UP_PENALTY
    if widened:
        confidence -= WIDENED_PENALTY
    return best, max(0.0, min(1.0, confidence))
