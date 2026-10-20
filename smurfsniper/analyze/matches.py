"""Recent ladder matches from one player's perspective (basic tendencies)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from smurfsniper.analyze.history import Record
from smurfsniper.api.sc2pulse.ids import MatchType
from smurfsniper.api.sc2pulse.models import LadderMatch

LADDER_TYPES = {MatchType._1V1, MatchType._2V2, MatchType._3V3, MatchType._4V4, MatchType.ARCHON}


@dataclass(frozen=True)
class RecentResult:
    ts: datetime
    won: bool
    map: str | None
    duration_s: int | None
    race: str | None  # race the player used
    opponent_race: str | None


def recent_results(matches: Sequence[LadderMatch], character_id: int) -> list[RecentResult]:
    """Decided ladder matches, newest first."""
    out: list[RecentResult] = []
    for m in matches:
        if m.match.type not in LADDER_TYPES:
            continue
        me = m.participant_for(character_id)
        if me is None or me.participant.decision not in ("WIN", "LOSS"):
            continue
        opps = m.opponents_of(character_id)
        out.append(
            RecentResult(
                ts=m.match.date,
                won=me.participant.decision == "WIN",
                map=m.map.name if m.map else None,
                duration_s=m.match.duration,
                race=me.race,
                opponent_race=opps[0].race if len(opps) == 1 else None,
            )
        )
    out.sort(key=lambda r: r.ts, reverse=True)
    return out


def map_records(results: Sequence[RecentResult]) -> dict[str, Record]:
    """Per-map record, most played first."""
    acc: dict[str, list[int]] = {}
    for r in results:
        if not r.map:
            continue
        wl = acc.setdefault(r.map, [0, 0])
        wl[0 if r.won else 1] += 1
    ordered = sorted(acc.items(), key=lambda kv: -(kv[1][0] + kv[1][1]))
    return {name: Record(w, lo) for name, (w, lo) in ordered}


def avg_duration(results: Sequence[RecentResult]) -> int | None:
    durations = [r.duration_s for r in results if r.duration_s]
    if not durations:
        return None
    return round(sum(durations) / len(durations))
