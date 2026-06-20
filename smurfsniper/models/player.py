from datetime import datetime
from typing import Dict, List, Optional, Set

from pydantic import BaseModel, ValidationError

from smurfsniper.api import sc2pulse
from smurfsniper.enums import League, Region, TeamFormat, TeamType
from smurfsniper.logger import logger
from smurfsniper.models.character import Character
from smurfsniper.models.shared import CurrentStats, PreviousStats
from smurfsniper.models.team_history import TeamHistory
from smurfsniper.utils import create_team_legacy_uid


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

    _match_history_cache: Optional[TeamHistory] = None

    @property
    def max_league(self) -> str:
        """Return the string league name from leagueMax integer."""
        return League.from_int(self.leagueMax).name

    @property
    def match_history(self) -> Optional[TeamHistory]:

        if self._match_history_cache is not None:
            return self._match_history_cache

        uids: Set[str] = {
            team.legacyUid
            for team in self.members.character.teams
            if team.legacyUid
        }
        if not uids:
            return None

        data = sc2pulse.team_histories(sorted(uids))
        history = sc2pulse.parse_team_history(data, legacy_uid="merged")

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
        data = sc2pulse.search_characters(self.name)

        results: List[PlayerStats] = []
        skipped = 0
        for entry in data:
            try:
                results.append(PlayerStats.model_validate(entry))
            except ValidationError:
                skipped += 1
        if skipped:
            logger.debug(f"Skipped {skipped} unparseable candidate(s) for {self.name}")
        return results

    def get_player_stats(self, min_mmr: int = 0, max_mmr: int = 5000) -> PlayerStats:
        candidates = self.matches()
        if not candidates:
            raise sc2pulse.SC2PulseNotFound(f"No SC2Pulse records for {self.name}")

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
