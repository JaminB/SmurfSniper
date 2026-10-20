"""Team summary for 2v2 and larger games."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime

from smurfsniper.analyze.history import (
    Record,
    outcomes,
    rating_points,
    record,
    season_record,
    sparkline,
)
from smurfsniper.api.sc2pulse.models import LadderTeam, TeamHistorySeries

WINDOWS = (("3d", 3), ("7d", 7), ("30d", 30))


@dataclass(frozen=True)
class TeamInfo:
    team: LadderTeam | None
    members_races: list[str] = field(default_factory=list)
    sparkline: str | None = None
    records: dict[str, Record] = field(default_factory=dict)


def windowed_records(outs, points, *, now: datetime, season: int | None) -> dict[str, Record]:
    """Records for 3d/7d/30d/season; windows with no games are omitted."""
    recs: dict[str, Record] = {}
    for key, days in WINDOWS:
        r = record(outs, days=days, now=now)
        if r.games:
            recs[key] = r
    if season is not None:
        r = season_record(outs, points, season)
        if r.games:
            recs["season"] = r
    return recs


def team_summary(
    team: LadderTeam | None,
    series: Sequence[TeamHistorySeries],
    *,
    now: datetime | None = None,
) -> TeamInfo:
    now = now or datetime.now(UTC)
    races: list[str] = []
    if team is not None:
        for m in team.members:
            if m.main_race:
                races.append(m.main_race)
    points = rating_points(series)
    outs = outcomes(points)
    recs = windowed_records(outs, points, now=now, season=team.season if team else None)
    return TeamInfo(
        team=team,
        members_races=races,
        sparkline=sparkline([p.rating for p in points]),
        records=recs,
    )
