from __future__ import annotations

from datetime import datetime, timedelta
from statistics import pstdev
from typing import Dict, List, Optional

from pydantic import BaseModel, computed_field, field_validator


class TeamHistoryPoint(BaseModel):
    timestamp: datetime
    rating: int

    @classmethod
    def from_raw(cls, ts: int, rating: int) -> "TeamHistoryPoint":
        return cls(timestamp=datetime.utcfromtimestamp(ts), rating=rating)


class TeamStaticData(BaseModel):
    LEGACY_ID: str


class TeamHistoryData(BaseModel):
    TIMESTAMP: List[int]
    RATING: List[int]

    @field_validator("RATING")
    def matching_lengths(cls, v, info):
        timestamps = info.data.get("TIMESTAMP")
        if timestamps and len(timestamps) != len(v):
            raise ValueError("TIMESTAMP and RATING must have same length")
        return v

    def to_points(self) -> List[TeamHistoryPoint]:
        return [
            TeamHistoryPoint.from_raw(ts, rating)
            for ts, rating in zip(self.TIMESTAMP, self.RATING)
        ]


class TeamHistory(BaseModel):
    legacy_uid: str
    timestamps: List[datetime]
    ratings: List[int]

    @computed_field
    @property
    def mmr_deltas(self) -> List[int]:
        return [
            self.ratings[i] - self.ratings[i - 1] for i in range(1, len(self.ratings))
        ]

    def _count_recent(self, days: int) -> Dict[str, int]:
        cutoff = datetime.utcnow() - timedelta(days=days)
        wins = 0
        losses = 0

        for ts, delta in zip(self.timestamps[1:], self.mmr_deltas):
            if days != -1 and ts < cutoff:
                continue
            if delta > 0:
                wins += 1
            elif delta < 0:
                losses += 1

        return {"wins": wins, "losses": losses}

    @computed_field
    @property
    def current_rating(self) -> int:
        return self.ratings[-1]

    @computed_field
    @property
    def highest_rating(self) -> int:
        return max(self.ratings)

    @computed_field
    @property
    def wins_last_day(self) -> int:
        return self._count_recent(1)["wins"]

    @computed_field
    @property
    def losses_last_day(self) -> int:
        return self._count_recent(1)["losses"]

    @computed_field
    @property
    def wins_last_3_days(self) -> int:
        return self._count_recent(3)["wins"]

    @computed_field
    @property
    def losses_last_3_days(self) -> int:
        return self._count_recent(3)["losses"]

    @computed_field
    @property
    def wins_last_week(self) -> int:
        return self._count_recent(7)["wins"]

    @computed_field
    @property
    def losses_last_week(self) -> int:
        return self._count_recent(7)["losses"]

    @computed_field
    @property
    def wins_last_month(self) -> int:
        return self._count_recent(30)["wins"]

    @computed_field
    @property
    def losses_last_month(self) -> int:
        return self._count_recent(30)["losses"]

    @computed_field
    @property
    def wins_lifetime(self) -> int:
        return self._count_recent(-1)["wins"]

    @computed_field
    @property
    def losses_lifetime(self) -> int:
        return self._count_recent(-1)["losses"]

    @property
    def first_game_played(self) -> Optional[datetime]:
        return min(self.timestamps)

    @property
    def last_game_played(self) -> Optional[datetime]:
        return max(self.timestamps)

    @property
    def account_age_days(self) -> int:
        """Days between the first recorded game and now (0 if no history)."""
        first = self.first_game_played
        if not first:
            return 0
        return max((datetime.utcnow() - first).days, 0)

    @property
    def current_streak(self) -> int:
        """Signed trailing streak: +N win streak, -N loss streak (0 = none).

        Counts consecutive same-direction MMR moves from the most recent game,
        skipping ties (zero deltas).
        """
        streak = 0
        sign = 0
        for delta in reversed(self.mmr_deltas):
            if delta == 0:
                continue
            d = 1 if delta > 0 else -1
            if sign == 0:
                sign = d
            elif d != sign:
                break
            streak += 1
        return sign * streak

    @property
    def longest_win_streak(self) -> int:
        """Longest run of consecutive wins (positive MMR deltas)."""
        best = run = 0
        for delta in self.mmr_deltas:
            if delta > 0:
                run += 1
                best = max(best, run)
            elif delta < 0:
                run = 0
        return best

    @property
    def mmr_volatility(self) -> float:
        """Std-dev of per-game MMR changes (higher = swingier results)."""
        if len(self.mmr_deltas) < 2:
            return 0.0
        return pstdev(self.mmr_deltas)

    @property
    def mmr_climb_velocity(self) -> float:
        """Average MMR gained per day from first to most recent rating.

        Positive = climbing. A fast climb on a low account is a smurf signal.
        """
        if len(self.ratings) < 2:
            return 0.0
        days = max(self.account_age_days, 1)
        return (self.ratings[-1] - self.ratings[0]) / days

    def sparkline(self, days: int = 30) -> str:
        if not self.timestamps or not self.ratings:
            return "(no data)"

        cutoff = datetime.utcnow() - timedelta(days=days)

        points = [r for ts, r in zip(self.timestamps, self.ratings) if ts >= cutoff]

        if len(points) < 3:
            points = self.ratings[-20:]

        if len(points) < 3:
            return "(insufficient data)"

        mn, mx = min(points), max(points)
        span = max(mx - mn, 1)
        normalized = [(p - mn) / span for p in points]

        bars = "▁▂▃▄▅▆▇█"
        n_levels = len(bars)

        spark = "".join(bars[int(v * (n_levels - 1))] for v in normalized)

        return spark
