from datetime import datetime
from typing import List, Optional, Dict
from pydantic import BaseModel
import httpx

from sc_match_briefer.logger import logger
from sc_match_briefer.models.shared import PreviousStats, CurrentStats
from sc_match_briefer.models.character import Character
from sc_match_briefer.enums import Region, TeamFormat, TeamType
from sc_match_briefer.utils import create_team_legacy_uid
from sc_match_briefer.models.team_history import TeamHistoryPoint, TeamHistory


class Members(BaseModel):
    protossGamesPlayed: Optional[int] = 0
    terranGamesPlayed: Optional[int] = 0
    zergGamesPlayed: Optional[int] = 0
    randomGamesPlayed: Optional[int] = 0

    character: Character
    account: Dict
    clan: Optional[Dict] = None
    raceGames: Dict[str, int]


class PlayerStats(BaseModel):
    leagueMax: int
    ratingMax: int
    totalGamesPlayed: int

    previousStats: PreviousStats
    currentStats: CurrentStats
    members: Members

    def legacy_uid(
        self,
        queue_type: TeamFormat,
        team_type: TeamType = TeamType.ARRANGED,
    ) -> str:
        region_enum = Region[self.members.character.region]
        return create_team_legacy_uid(
            queue_type=queue_type,
            team_type=team_type,
            region=region_enum,
            members=[self.members],
        )

    def get_match_history(self) -> Optional[TeamHistory]:
        urls = []
        for team in self.members.character.teams():
            if team.legacyUid:
                urls.append(f"teamLegacyUid={team.legacyUid}")

        if not urls:
            return None

        url = (
                "https://sc2pulse.nephest.com/sc2/api/team-histories?"
                + "&".join(urls)
                + "&groupBy=LEGACY_UID&static=LEGACY_ID&history=TIMESTAMP&history=RATING"
        )

        with httpx.Client(timeout=10.0) as client:
            r = client.get(url)
            r.raise_for_status()
            data = r.json()

        merged_points: list[TeamHistoryPoint] = []

        for entry in data:
            history = entry.get("history", {})
            timestamps = history.get("TIMESTAMP", [])
            ratings = history.get("RATING", [])
            for ts, rating in zip(timestamps, ratings):
                merged_points.append(TeamHistoryPoint.from_raw(ts, rating))

        if not merged_points:
            return None

        merged_points.sort(key=lambda p: p.timestamp)

        deduped = []
        last_ts = None
        for p in merged_points:
            if last_ts != p.timestamp:
                deduped.append(p)
                last_ts = p.timestamp

        return TeamHistory(
            legacy_uid="merged",
            timestamps=[p.timestamp for p in deduped],
            ratings=[p.rating for p in deduped],
        )


class Player(BaseModel):
    id: int
    name: str
    type: str
    race: str
    result: str

    def matches(self) -> List[PlayerStats]:
        url = f"https://sc2pulse.nephest.com/sc2/api/characters?query={self.name}"

        with httpx.Client(timeout=10.0) as client:
            r = client.get(url)
            r.raise_for_status()
            data = r.json()

        return [PlayerStats.model_validate(entry) for entry in data]

    def get_best_match(self, min_mmr: int = 0, max_mmr: int = 5000) -> PlayerStats:
        candidates = self.matches()

        filtered = [
            c for c in candidates
            if (c.currentStats.rating is not None
                and min_mmr <= c.currentStats.rating <= max_mmr)
        ]

        if not filtered:
            logger.warning(
                f"No matches for {self.name} within MMR range {min_mmr}–{max_mmr}. "
                f"Falling back to unfiltered candidates."
            )
            filtered = candidates

        best = filtered[0]
        newest = datetime.min

        for match in filtered:
            logger.info(f"Evaluating {self.name} candidate with MMR={match.currentStats.rating}")

            for team in match.members.character.teams():
                if not team.lastPlayed:
                    continue

                dt = datetime.fromisoformat(team.lastPlayed.replace("Z", ""))

                if dt > newest:
                    newest = dt
                    best = match

        return best


def print_player_summary(player_name: str, player_stats: PlayerStats, history: "TeamHistory"):
    """
    Print a clean human-friendly summary of player + team history.
    """

    char = player_stats.members.character

    rows = []

    def add(label, value):
        rows.append((label, value))

    # Basic identity
    add("Player", char.name)
    add("Region", char.region)
    add("Race", player_stats.members.raceGames)

    # Rating summary
    add("Current Rating", player_stats.currentStats.rating)
    add("Highest Rating", player_stats.ratingMax)
    add("Total Games Played", player_stats.totalGamesPlayed)

    # Legacy UID
    add("Legacy UID", history.legacy_uid)

    # Recent wins/losses
    add("Wins (1 day)", history.wins_last_day)
    add("Losses (1 day)", history.losses_last_day)

    add("Wins (3 days)", history.wins_last_3_days)
    add("Losses (3 days)", history.losses_last_3_days)

    add("Wins (7 days)", history.wins_last_week)
    add("Losses (7 days)", history.losses_last_week)

    # Rating movement
    if history.ratings:
        add("Latest Rating", history.ratings[-1])
        add("First Recorded Rating", history.ratings[0])
        add("MMR Change (all-time)", history.ratings[-1] - history.ratings[0])

    # Print pretty table
    print("\n" + "=" * 50)
    print(f"  SC2 Player Summary: {player_name}")
    print("=" * 50)

    for label, value in rows:
        print(f"{label:<25} {value}")

    print("=" * 50 + "\n")
