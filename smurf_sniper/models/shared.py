from typing import Optional

from pydantic import BaseModel


class PreviousStats(BaseModel):
    rating: Optional[int]
    gamesPlayed: Optional[int]
    rank: Optional[int]


class CurrentStats(BaseModel):
    rating: Optional[int]
    gamesPlayed: Optional[int]
    rank: Optional[int]
