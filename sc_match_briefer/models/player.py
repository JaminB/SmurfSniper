from datetime import datetime
from typing import Dict, List, Optional, Set

import httpx
from pydantic import BaseModel

from sc_match_briefer.enums import League, Region, TeamFormat, TeamType
from sc_match_briefer.logger import logger
from sc_match_briefer.models.character import Character
from sc_match_briefer.models.shared import CurrentStats, PreviousStats
from sc_match_briefer.models.team_history import TeamHistory, TeamHistoryPoint
from sc_match_briefer.utils import create_team_legacy_uid


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

    # internal memoized cache per instance
    _match_history_cache: Optional[TeamHistory] = None

    @property
    def max_league(self) -> str:
        """Return the string league name from leagueMax integer."""
        return League.from_int(self.leagueMax).name

    @property
    def match_history(self) -> Optional[TeamHistory]:
        """
        Fetch full match history across all teams, merge into a single time series,
        dedupe timestamps, and cache for future use.
        """
        # --- return memoized version ---
        if self._match_history_cache is not None:
            return self._match_history_cache

        # collect all UIDs
        urls: Set[str] = set()
        for team in self.members.character.teams:
            if team.legacyUid:
                urls.add(f"teamLegacyUid={team.legacyUid}")

        if not urls:
            return None

        # limit to first 10 UIDs (API constraint/subtle rate protection)
        url = (
            "https://sc2pulse.nephest.com/sc2/api/team-histories?"
            + "&".join(list(urls)[:10])
            + "&groupBy=LEGACY_UID&static=LEGACY_ID&history=TIMESTAMP&history=RATING"
        )

        with httpx.Client(timeout=10.0) as client:
            r = client.get(url)
            r.raise_for_status()
            data = r.json()

        merged_points: List[TeamHistoryPoint] = []

        for entry in data:
            history = entry.get("history", {})
            timestamps = history.get("TIMESTAMP", [])
            ratings = history.get("RATING", [])
            for ts, rating in zip(timestamps, ratings):
                merged_points.append(TeamHistoryPoint.from_raw(ts, rating))

        if not merged_points:
            return None

        merged_points.sort(key=lambda p: p.timestamp)

        deduped: List[TeamHistoryPoint] = []
        last_ts = None
        for p in merged_points:
            if p.timestamp != last_ts:
                deduped.append(p)
                last_ts = p.timestamp

        history = TeamHistory(
            legacy_uid="merged",
            timestamps=[p.timestamp for p in deduped],
            ratings=[p.rating for p in deduped],
        )

        self._match_history_cache = history
        return history

    def legacy_uid(
        self,
        queue_type: TeamFormat,
        team_type: TeamType = TeamType.ARRANGED,
    ) -> str:
        """Compute the player's team legacy UID for a given queue."""
        region_enum = Region[self.members.character.region]
        return create_team_legacy_uid(
            queue_type=queue_type,
            team_type=team_type,
            region=region_enum,
            members=[self.members],
        )


class Player(BaseModel):
    id: int
    name: str
    type: str
    race: str
    result: str

    @classmethod
    def from_player_name(cls, player_name: str) -> "Player":
        """
        Convenience constructor for creating a Player model
        from just a name string. Useful for manual lookups or CLI tools.
        """
        player_name = player_name.strip()

        return cls(
            id=1,  # dummy ID (SC2Pulse will not use it)
            name=player_name,
            type="user",
            race="Unknown",
            result="Undecided",
        )

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
            c
            for c in candidates
            if (
                c.currentStats.rating is not None
                and min_mmr <= c.currentStats.rating <= max_mmr
            )
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
            logger.info(
                f"Evaluating {self.name} candidate with MMR={match.currentStats.rating}"
            )

            for team in match.members.character.teams:
                if not team.lastPlayed:
                    continue

                dt = datetime.fromisoformat(team.lastPlayed.replace("Z", ""))

                if dt > newest:
                    newest = dt
                    best = match

        return best
