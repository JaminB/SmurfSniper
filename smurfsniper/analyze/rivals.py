"""Rivals, nemesis and favourite victim from the local opponent log."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from smurfsniper.analyze.history import Record
from smurfsniper.storage.rows import PlayerLogRow


@dataclass(frozen=True)
class Rival:
    name: str
    region: str | None
    battlenet_id: int
    games: int
    record: Record
    last_played: datetime
    last_mmr: int | None
    last_race: str | None


@dataclass(frozen=True)
class RivalsSummary:
    top: tuple[Rival, ...] = ()
    nemesis: Rival | None = None
    favourite_victim: Rival | None = None

    def is_empty(self) -> bool:
        return not self.top

    def standing(self, region: str | None, battlenet_id: int) -> str | None:
        """``"nemesis"`` / ``"rival"`` for a known opponent, else None."""
        n = self.nemesis
        if n is not None and n.battlenet_id == battlenet_id and n.region == region:
            return "nemesis"
        if any(r.battlenet_id == battlenet_id and r.region == region for r in self.top):
            return "rival"
        return None


def _in_mode(row: PlayerLogRow, mode: str | None) -> bool:
    if mode is None:
        return True
    # Rows logged before the mode column existed were 1v1 in practice.
    return (row.mode or "1v1") == mode


def rivals(
    rows: Sequence[PlayerLogRow],
    *,
    min_games: int = 2,
    top_n: int = 5,
    mode: str | None = "1v1",
) -> RivalsSummary:
    """Opponents met at least ``min_games`` times.

    - nemesis: most ahead of you (losses - wins, then losses), needs 2+ losses and a
      winrate under 50%;
    - favourite victim: the mirror image (wins - losses, then wins), 2+ wins, over 50%.
    """
    groups: dict[tuple[str, int], list[PlayerLogRow]] = {}
    for row in rows:
        if _in_mode(row, mode):
            groups.setdefault((row.region, row.battlenet_id), []).append(row)

    found: list[Rival] = []
    for (region, bnet), group in groups.items():
        if len(group) < min_games:
            continue
        newest = max(group, key=lambda r: (r.created_at, r.id))
        wins = sum(1 for r in group if r.result_for_me == "victory")
        losses = sum(1 for r in group if r.result_for_me == "defeat")
        last_mmr = next(
            (r.mmr for r in sorted(group, key=lambda r: (r.created_at, r.id), reverse=True)
             if r.mmr),
            None,
        )  # fmt: skip
        found.append(
            Rival(
                name=newest.name.split("#")[0],
                region=region,
                battlenet_id=bnet,
                games=len(group),
                record=Record(wins, losses),
                last_played=newest.created_at,
                last_mmr=last_mmr,
                last_race=newest.opp_race,
            )
        )

    found.sort(key=lambda r: (-r.games, -r.last_played.timestamp()))

    def rate(r: Rival) -> float:
        return r.record.wins / r.record.games if r.record.games else 0.5

    nemeses = [r for r in found if r.record.losses >= 2 and rate(r) < 0.5]
    victims = [r for r in found if r.record.wins >= 2 and rate(r) > 0.5]
    nemesis = max(
        nemeses,
        key=lambda r: (r.record.losses - r.record.wins, r.record.losses),
        default=None,
    )
    victim = max(
        victims,
        key=lambda r: (r.record.wins - r.record.losses, r.record.wins),
        default=None,
    )
    return RivalsSummary(top=tuple(found[:top_n]), nemesis=nemesis, favourite_victim=victim)
