"""Head-to-head record against one opponent, from the local player log."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from smurfsniper.storage.rows import PlayerLogRow


@dataclass(frozen=True)
class H2HInfo:
    games: int
    wins: int
    losses: int
    ties: int
    first: datetime
    last: datetime
    rivalry: str | None = None  # "rival" / "nemesis" (set by the lookup pipeline)


def head_to_head(rows: Sequence[PlayerLogRow]) -> H2HInfo | None:
    """None when there are no rows. Results are from the user's perspective."""
    if not rows:
        return None
    wins = losses = ties = 0
    for r in rows:
        res = r.result_for_me
        if res == "victory":
            wins += 1
        elif res == "defeat":
            losses += 1
        else:
            ties += 1
    stamps = [r.created_at for r in rows]
    return H2HInfo(
        games=len(rows), wins=wins, losses=losses, ties=ties, first=min(stamps), last=max(stamps)
    )
