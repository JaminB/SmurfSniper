from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from sc_match_briefer.models.player import Player, PlayerStats
from sc_match_briefer.enums import League, RaceCode



class PlayerAnalysis(BaseModel):
    current_race: Optional[str] = None
    player_stats: PlayerStats

    @classmethod
    def from_player(cls, player: Player) -> "PlayerAnalysis":
        best_match = player.get_best_match()
        stats = PlayerStats.model_validate(best_match)
        return cls(player_stats=stats)

    @property
    def name(self) -> str:
        return self.player_stats.members.character.name

    @property
    def max_league(self) -> str:
        return League.from_int(self.player_stats.leagueMax).name

    @property
    def current_mmr(self) -> Optional[int]:
        return (
            self.player_stats.currentStats.rating
            or self.player_stats.previousStats.rating
        )

    @property
    def previous_mmr(self) -> Optional[int]:
        return self.player_stats.previousStats.rating

    @property
    def mmr_trend(self) -> str:
        cur = self.current_mmr
        prev = self.previous_mmr
        if cur is None or prev is None:
            return "unknown"
        if cur > prev:
            return "rising"
        if cur < prev:
            return "falling"
        return "flat"

    @property
    def total_games(self) -> int:
        return self.player_stats.totalGamesPlayed

    @property
    def most_played_race(self) -> str:
        races = self.player_stats.members.raceGames
        if not races:
            return "unknown"
        key = max(races, key=lambda r: races.get(r, 0))
        return RaceCode[key].name

    @property
    def wins_last_day(self) -> int:
        return self.player_stats.match_history.wins_last_day

    @property
    def losses_last_day(self) -> int:
        return self.player_stats.match_history.losses_last_day

    @property
    def wins_last_3_days(self) -> int:
        return self.player_stats.match_history.wins_last_3_days

    @property
    def losses_last_3_days(self) -> int:
        return self.player_stats.match_history.losses_last_3_days

    @property
    def wins_last_week(self) -> int:
        return self.player_stats.match_history.wins_last_week

    @property
    def losses_last_week(self) -> int:
        return self.player_stats.match_history.losses_last_week

    @property
    def wins_last_month(self) -> int:
        return self.player_stats.match_history.wins_last_month

    @property
    def losses_last_month(self) -> int:
        return self.player_stats.match_history.losses_last_month

    @property
    def wins_lifetime(self) -> int:
        return self.player_stats.match_history.wins_lifetime

    @property
    def losses_lifetime(self) -> int:
        return self.player_stats.match_history.losses_lifetime

    @property
    def last_played(self) -> Optional[datetime]:
        timestamps = self.player_stats.match_history.timestamps
        if not timestamps:
            return None
        return max(timestamps)

    @property
    def teammates(self) -> dict[str, dict[str, Optional[datetime]]]:
        result = {}
        my_name = self.name
        history = self.player_stats.match_history

        if not history:
            return {}

        for team in self.player_stats.members.character.teams:
            ts = (
                datetime.fromisoformat(team.lastPlayed.replace("Z", ""))
                if team.lastPlayed
                else None
            )
            if not ts:
                continue

            for member in team.members:
                n = member.character.name
                if n == my_name:
                    continue
                entry = result.setdefault(
                    n, {"count": 0, "last_played": None}
                )
                entry["count"] += 1
                if entry["last_played"] is None or ts > entry["last_played"]:
                    entry["last_played"] = ts

        return result

    def summary(self) -> dict:
        partners_readable = {
            name: (
                info["last_played"].isoformat()
                if info.get("last_played") else "unknown"
            )
            for name, info in self.teammates.items()
        }

        return {
            "Player": self.name,
            "Max League": self.max_league,
            "Current MMR": self.current_mmr,
            "Trend": self.mmr_trend,
            "Most Played Race": self.most_played_race,
            "Total Games": self.total_games,
            "Wins (1d)": self.wins_last_day,
            "Losses (1d)": self.losses_last_day,
            "Wins (3d)": self.wins_last_3_days,
            "Losses (3d)": self.losses_last_3_days,
            "Wins (7d)": self.wins_last_week,
            "Losses (7d)": self.losses_last_week,
            "Wins (30d)": self.wins_last_month,
            "Losses (30d)": self.losses_last_month,
            "Lifetime Wins": self.wins_lifetime,
            "Lifetime Losses": self.losses_lifetime,
            "Last Played": self.last_played.isoformat() if self.last_played else None,
            "Frequent Teammates": partners_readable,
        }

    def pretty_print(self) -> None:
        table = self.summary()
        print("\n=== Player Analysis ===")
        for k, v in table.items():
            print(f"{k:22}: {v}")
        print("========================\n")


