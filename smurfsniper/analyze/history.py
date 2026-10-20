"""Rating history analysis: points, per-game outcomes, records, trend, sparkline.

Pure functions over typed SC2Pulse models.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from smurfsniper.api.sc2pulse.ids import HistoryColumn
from smurfsniper.api.sc2pulse.models import TeamHistorySeries

BARS = "▁▂▃▄▅▆▇█"
TREND_FLAT_PER_DAY = 2.0  # |slope| below this (MMR/day) is "flat"


@dataclass(frozen=True)
class RatingPoint:
    ts: datetime
    rating: int
    season: int | None = None
    games: int | None = None
    wins: int | None = None
    league: int | None = None
    team: str | None = None  # legacy uid the point came from


@dataclass(frozen=True)
class GameOutcome:
    ts: datetime
    won: bool
    rating_after: int
    delta: int | None


@dataclass(frozen=True)
class Record:
    wins: int
    losses: int

    @property
    def games(self) -> int:
        return self.wins + self.losses

    @property
    def winrate(self) -> float | None:
        return self.wins / self.games if self.games else None

    def __str__(self) -> str:
        return f"{self.wins}-{self.losses}"


@dataclass(frozen=True)
class Trend:
    slope_per_day: float
    symbol: Literal["▲", "▼", "▶"]


def _col(series: TeamHistorySeries, c: HistoryColumn) -> list | None:
    return series.column(c)


def rating_points(series: Sequence[TeamHistorySeries]) -> list[RatingPoint]:
    """Merge every series into points sorted by time, de-duplicated by (team, ts)."""
    out: list[RatingPoint] = []
    seen: set[tuple[str, datetime]] = set()
    for s in series:
        ts = _col(s, HistoryColumn.TIMESTAMP)
        rating = _col(s, HistoryColumn.RATING)
        if not ts or not rating:
            continue
        season = _col(s, HistoryColumn.SEASON)
        games = _col(s, HistoryColumn.GAMES)
        wins = _col(s, HistoryColumn.WINS)
        league = _col(s, HistoryColumn.LEAGUE_TYPE)
        for i, (t, r) in enumerate(zip(ts, rating, strict=False)):
            if t is None or r is None:
                continue
            when = datetime.fromtimestamp(int(t), UTC)
            key = (s.legacy_uid, when)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                RatingPoint(
                    ts=when,
                    rating=int(r),
                    season=season[i] if season else None,
                    games=games[i] if games else None,
                    wins=wins[i] if wins else None,
                    league=league[i] if league else None,
                    team=s.legacy_uid,
                )
            )
    out.sort(key=lambda p: p.ts)
    return out


def outcomes(points: Sequence[RatingPoint]) -> list[GameOutcome]:
    """Per-game results from consecutive points of the same team and season.

    With GAMES/WINS: ``dg = games[i]-games[i-1]``, ``dw = wins[i]-wins[i-1]``. One game
    gives one outcome; several games between snapshots emit ``dw`` wins and ``dg-dw``
    losses at ``ts[i]``. Without them the sign of the rating delta is used (0 skipped).
    """
    by_team: dict[str | None, list[RatingPoint]] = {}
    for p in points:
        by_team.setdefault(p.team, []).append(p)

    out: list[GameOutcome] = []
    for pts in by_team.values():
        pts = sorted(pts, key=lambda p: p.ts)
        for prev, cur in zip(pts, pts[1:], strict=False):
            if prev.season is not None and cur.season is not None and prev.season != cur.season:
                continue
            delta = cur.rating - prev.rating
            if None not in (prev.games, cur.games, prev.wins, cur.wins):
                dg = cur.games - prev.games
                if dg <= 0:
                    continue
                dw = max(0, min(dg, cur.wins - prev.wins))
                if dg == 1:
                    out.append(GameOutcome(cur.ts, dw == 1, cur.rating, delta))
                else:
                    out.extend(GameOutcome(cur.ts, True, cur.rating, None) for _ in range(dw))
                    out.extend(GameOutcome(cur.ts, False, cur.rating, None) for _ in range(dg - dw))
            elif delta != 0:
                out.append(GameOutcome(cur.ts, delta > 0, cur.rating, delta))
    out.sort(key=lambda o: o.ts)
    return out


def record(outs: Sequence[GameOutcome], *, days: int | None, now: datetime) -> Record:
    """Wins/losses in the last ``days`` days (all time if None)."""
    cutoff = None if days is None else now - timedelta(days=days)
    wins = losses = 0
    for o in outs:
        if cutoff is not None and o.ts < cutoff:
            continue
        if o.won:
            wins += 1
        else:
            losses += 1
    return Record(wins, losses)


def season_record(
    outs: Sequence[GameOutcome], points: Sequence[RatingPoint], season: int
) -> Record:
    """Record within one season, using the season of the point at each outcome."""
    season_at = {p.ts: p.season for p in points}
    wins = losses = 0
    for o in outs:
        if season_at.get(o.ts) != season:
            continue
        if o.won:
            wins += 1
        else:
            losses += 1
    return Record(wins, losses)


def trend(points: Sequence[RatingPoint], *, last_n: int = 100) -> Trend | None:
    """Linear regression of rating against days over the last ``last_n`` points."""
    pts = list(points)[-last_n:]
    if len(pts) < 5:
        return None
    t0 = pts[0].ts
    xs = [(p.ts - t0).total_seconds() / 86400 for p in pts]
    ys = [p.rating for p in pts]
    n = len(pts)
    mx, my = sum(xs) / n, sum(ys) / n
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=False)) / den
    if slope > TREND_FLAT_PER_DAY:
        sym = "▲"
    elif slope < -TREND_FLAT_PER_DAY:
        sym = "▼"
    else:
        sym = "▶"
    return Trend(slope_per_day=slope, symbol=sym)


def sparkline(values: Sequence[int], width: int = 12) -> str | None:
    """Unicode bar sparkline of the last ``width`` values; None for fewer than 3."""
    vals = list(values)[-width:]
    if len(vals) < 3:
        return None
    lo, hi = min(vals), max(vals)
    span = max(hi - lo, 1)
    top = len(BARS) - 1
    return "".join(BARS[round((v - lo) / span * top)] for v in vals)


def account_age_days(
    points: Sequence[RatingPoint], candidate_first_seen: datetime | None, now: datetime
) -> int | None:
    """Days since the earliest known activity (history or other evidence)."""
    firsts = [min(p.ts for p in points)] if points else []
    if candidate_first_seen is not None:
        firsts.append(candidate_first_seen)
    if not firsts:
        return None
    return max(0, (now - min(firsts)).days)


def climb_velocity(
    points: Sequence[RatingPoint], *, days: int | None = 14, now: datetime | None = None
) -> float | None:
    """Rating gained per day.

    ``days`` limits the window to the last N days before the newest point; ``None``
    uses the whole history and divides by the days from the first point to ``now``
    (the original lifetime-average definition). Needs at least 2 points.
    """
    pts = sorted(points, key=lambda p: p.ts)
    if len(pts) < 2:
        return None
    last = pts[-1]
    if days is not None:
        cutoff = last.ts - timedelta(days=days)
        pts = [p for p in pts if p.ts >= cutoff]
        if len(pts) < 2:
            return None
    first = pts[0]
    end = now if (now is not None and days is None) else last.ts
    span = max((end - first.ts).days, 1)
    return (last.rating - first.rating) / span
