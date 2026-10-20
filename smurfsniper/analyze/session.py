"""Session tracker maths: record, streak, MMR movement and per-matchup results."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from smurfsniper.analyze.history import Record
from smurfsniper.storage.rows import SessionGame

_RACE_INITIAL = {"ZERG": "Z", "TERRAN": "T", "PROTOSS": "P", "RANDOM": "R"}


@dataclass(frozen=True)
class SessionSnapshot:
    started_at: datetime
    games: int
    wins: int
    losses: int
    ties: int
    mmr_start: int | None
    mmr_now: int | None  # last known rating after a game; None until one is known
    mmr_delta: int | None  # mmr_now - mmr_start, only when both are known
    mmr_points: tuple[int, ...]  # mmr_start, then each known mmr_after
    streak: tuple[Literal["W", "L"], int] | None
    time_played_s: int
    by_matchup: dict[str, Record] = field(default_factory=dict)  # "vZ", "vT", ... (1v1 only)


def _streak(results: Sequence[str | None]) -> tuple[Literal["W", "L"], int] | None:
    """Current run of identical decisions, newest game last in ``results``."""
    decided = [r for r in results if r in ("victory", "defeat")]
    if not decided:
        return None
    last = decided[-1]
    n = 0
    for r in reversed(decided):
        if r != last:
            break
        n += 1
    return ("W" if last == "victory" else "L", n)


def matchup_key(opponent_race: str | None) -> str | None:
    initial = _RACE_INITIAL.get(opponent_race or "")
    return f"v{initial}" if initial else None


def snapshot(
    games: Sequence[SessionGame],
    *,
    mmr_start: int | None,
    started_at: datetime | None = None,
) -> SessionSnapshot:
    """Summarise one session. ``games`` are oldest first."""
    wins = sum(1 for g in games if g.my_result == "victory")
    losses = sum(1 for g in games if g.my_result == "defeat")
    ties = sum(1 for g in games if g.my_result == "tie")

    after = [g.mmr_after for g in games if g.mmr_after]
    mmr_now = after[-1] if after else None
    points: tuple[int, ...] = ()
    if mmr_start and after:
        points = (mmr_start, *after)
    delta = mmr_now - mmr_start if mmr_now is not None and mmr_start else None

    acc: dict[str, list[int]] = {}
    for g in games:
        if g.mode != "1v1" or g.my_result not in ("victory", "defeat") or len(g.opponents) != 1:
            continue
        key = matchup_key(g.opponents[0].race)
        if key is None:
            continue
        wl = acc.setdefault(key, [0, 0])
        wl[0 if g.my_result == "victory" else 1] += 1

    start = started_at or (games[0].started_at if games else datetime.now(UTC))
    return SessionSnapshot(
        started_at=start,
        games=len(games),
        wins=wins,
        losses=losses,
        ties=ties,
        mmr_start=mmr_start or None,
        mmr_now=mmr_now,
        mmr_delta=delta,
        mmr_points=points,
        streak=_streak([g.my_result for g in games]),
        time_played_s=sum(g.game_seconds or 0 for g in games),
        by_matchup={k: Record(w, lo) for k, (w, lo) in sorted(acc.items())},
    )
