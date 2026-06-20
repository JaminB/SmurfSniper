from typing import Dict, List, Optional, Set

from pydantic import BaseModel, ValidationError

from smurfsniper.api import sc2pulse
from smurfsniper.enums import League, RaceCode, Region, TeamFormat, TeamType
from smurfsniper.logger import logger
from smurfsniper.models.character import Character
from smurfsniper.models.match import RecentMatch
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

    # Pro/streamer reveal — embedded in the /characters response by SC2Pulse.
    proId: Optional[int] = None
    proNickname: Optional[str] = None
    proTeam: Optional[str] = None
    proPlayer: Optional[Dict] = None


class PlayerStats(BaseModel):
    leagueMax: int
    ratingMax: int
    totalGamesPlayed: int

    previousStats: PreviousStats
    currentStats: CurrentStats
    members: Members

    _match_history_cache: Optional[TeamHistory] = None
    _social_links_cache: Optional[Dict[str, str]] = None
    _recent_matches_cache: Optional[Dict[int, List[RecentMatch]]] = None
    _pro_details_cache: Optional[Dict] = None

    @property
    def is_pro(self) -> bool:
        return self.members.proNickname is not None

    @property
    def aligulac_id(self) -> Optional[int]:
        details = self.pro_details()
        if details:
            aid = (details.get("proPlayer") or {}).get("aligulacId")
            if aid is not None:
                return aid
        pp = self.members.proPlayer
        if not pp:
            return None
        return (pp.get("proPlayer") or {}).get("aligulacId")

    def pro_details(self) -> Optional[dict]:
        """Full pro bio + external links (country, earnings, Aligulac, Twitch...).

        Lazily fetched from SC2Pulse /entities for revealed pros only; cached.
        The embedded /characters proPlayer is stripped of bio, so this is the
        source for country/earnings/real name/links.
        """
        pro_id = self.members.proId
        if pro_id is None:
            return None
        if self._pro_details_cache is not None:
            return self._pro_details_cache or None
        try:
            entry = sc2pulse.pro_player(pro_id)
        except sc2pulse.SC2PulseError:
            entry = None
        self._pro_details_cache = entry or {}
        return entry

    def social_links(self) -> Dict[str, str]:
        """External links (Twitch, sc2replaystats, battle.net) for this player.

        Lazily fetched from SC2Pulse /character-links. Only worth calling for
        revealed pros/streamers; cached after the first call.
        """
        if self._social_links_cache is not None:
            return self._social_links_cache

        links: Dict[str, str] = {}
        try:
            data = sc2pulse.character_links(self.members.character.id)
        except sc2pulse.SC2PulseError as exc:
            logger.warning(f"Failed to fetch character-links: {exc}")
            data = []

        for entry in data:
            for link in entry.get("links", []):
                link_type = link.get("type")
                url_value = link.get("absoluteUrl")
                if link_type and url_value:
                    links[link_type] = url_value

        self._social_links_cache = links
        return links

    def recent_matches(self, limit: int = 25) -> List[RecentMatch]:
        """Real recent matches (map, duration, decision, opponent) for this player.

        Lazily fetched from SC2Pulse /character-matches and cached. SC2Pulse only
        retains match history for tracked characters, so this is often empty.
        """
        if self._recent_matches_cache is None:
            self._recent_matches_cache = {}
        if limit in self._recent_matches_cache:
            return self._recent_matches_cache[limit]

        char_id = self.members.character.id
        try:
            data = sc2pulse.character_matches(char_id, limit=limit)
        except sc2pulse.SC2PulseError as exc:
            logger.warning(f"Failed to fetch character-matches: {exc}")
            data = []

        matches: List[RecentMatch] = []
        for entry in data:
            parsed = RecentMatch.from_raw(entry, char_id)
            if parsed is not None:
                matches.append(parsed)

        self._recent_matches_cache[limit] = matches
        return matches

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
                # SC2Pulse returns some candidates with null core stats
                # (e.g. leagueMax/ratingMax). Skip rather than crash.
                skipped += 1
        if skipped:
            logger.debug(f"Skipped {skipped} unparseable candidate(s) for {self.name}")
        return results

    def get_player_stats(
        self,
        min_mmr: int = 0,
        max_mmr: int = 5000,
        region: Optional[str] = None,
    ) -> PlayerStats:
        """Pick the SC2Pulse candidate most likely to be this in-game player.

        A name query (especially for barcodes) returns many accounts across
        regions/skill levels. Candidates are scored on signals already present
        in the query response — exact name, race, MMR window, region, activity —
        so the right account is chosen without an extra team fetch per candidate.
        """
        candidates = self.matches()
        if not candidates:
            raise sc2pulse.SC2PulseNotFound(f"No SC2Pulse records for {self.name}")

        # In-game name has no discriminator; SC2Pulse names are "name#1234".
        query_name = self.name.split("#")[0].strip().casefold()

        want_race: Optional[str] = None
        if self.race and self.race != "Unknown":
            try:
                want_race = RaceCode.from_alias(self.race).name
            except (KeyError, ValueError):
                want_race = None

        def score(c: PlayerStats) -> float:
            s = 0.0
            char = c.members.character
            rating = c.currentStats.rating

            if char.name.split("#")[0].casefold() == query_name:
                s += 4  # exact account name (ignoring discriminator)
            if region and char.region == region:
                s += 3  # same server as the live match
            if rating is not None and min_mmr <= rating <= max_mmr:
                s += 3  # within the expected skill window
            if want_race and c.members.raceGames.get(want_race, 0) > 0:
                s += 1  # has played the race seen in-game
            if c.currentStats.gamesPlayed:
                s += 1  # active this season
            if rating is not None:
                s += rating / 100_000  # tiny tie-break toward higher MMR
            return s

        best = max(candidates, key=score)
        logger.info(
            f"Chose {best.members.character.name} "
            f"(MMR={best.currentStats.rating}, region={best.members.character.region}) "
            f"for {self.name} from {len(candidates)} candidate(s)"
        )
        return best
