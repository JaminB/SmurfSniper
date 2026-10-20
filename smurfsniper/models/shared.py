from pydantic import BaseModel


class PreviousStats(BaseModel):
    rating: int | None
    gamesPlayed: int | None
    rank: int | None


class CurrentStats(BaseModel):
    rating: int | None
    gamesPlayed: int | None
    rank: int | None
