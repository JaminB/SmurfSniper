from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel

# Ranked-ladder match types reported by SC2Pulse. Excludes CUSTOM / co-op so
# opponent records reflect competitive play only.
LADDER_TYPES = {"_1V1", "_2V2", "_3V3", "_4V4", "ARCHON"}


def ladder_only(matches: List["RecentMatch"]) -> List["RecentMatch"]:
    return [m for m in matches if m.type in LADDER_TYPES]


class RecentMatch(BaseModel):
    """A single resolved match from SC2Pulse /character-matches.

    Flattened to the queried player's perspective: ``decision`` is that
    player's result and ``opponent_id`` is the other 1v1 participant.
    """

    date: datetime
    type: str
    region: str
    map_name: Optional[str] = None
    duration: Optional[int] = None
    decision: Optional[str] = None  # "WIN" / "LOSS" / "TIE"
    opponent_id: Optional[int] = None
    rating_change: Optional[int] = None

    @classmethod
    def from_raw(cls, entry: dict, character_id: int) -> Optional["RecentMatch"]:
        """Parse one /character-matches result entry for ``character_id``.

        Returns None if the player's own participant row cannot be found.
        """
        match = entry.get("match", {})
        participants = entry.get("participants", [])

        mine = None
        opponent_id = None
        for p in participants:
            part = p.get("participant", {})
            if part.get("playerCharacterId") == character_id:
                mine = part
            else:
                opponent_id = part.get("playerCharacterId", opponent_id)

        if mine is None:
            return None

        map_info = entry.get("map") or {}
        return cls(
            date=match["date"],
            type=match.get("type", "UNKNOWN"),
            region=match.get("region", ""),
            map_name=map_info.get("name"),
            duration=match.get("duration"),
            decision=mine.get("decision"),
            opponent_id=opponent_id,
            rating_change=mine.get("ratingChange"),
        )


def map_records(matches: List[RecentMatch]) -> Dict[str, Tuple[int, int]]:
    """Per-map (wins, losses) aggregated over the given matches."""
    records: Dict[str, Tuple[int, int]] = {}
    for m in matches:
        if not m.map_name:
            continue
        w, l = records.get(m.map_name, (0, 0))
        if m.decision == "WIN":
            w += 1
        elif m.decision == "LOSS":
            l += 1
        records[m.map_name] = (w, l)
    return records


def avg_duration_seconds(matches: List[RecentMatch]) -> Optional[int]:
    """Average match duration (seconds), ignoring matches with no duration."""
    durations = [m.duration for m in matches if m.duration]
    if not durations:
        return None
    return round(sum(durations) / len(durations))
