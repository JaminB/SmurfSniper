from __future__ import annotations
from datetime import datetime, timedelta
from typing import List, Optional, Dict
from pydantic import BaseModel, field_validator, computed_field


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


from datetime import datetime, timedelta
from typing import List, Dict
from pydantic import BaseModel, computed_field


class TeamHistory(BaseModel):
    legacy_uid: str
    timestamps: List[datetime]
    ratings: List[int]

    @computed_field
    @property
    def mmr_deltas(self) -> List[int]:
        return [
            self.ratings[i] - self.ratings[i - 1]
            for i in range(1, len(self.ratings))
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

