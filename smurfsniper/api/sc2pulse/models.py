"""Pydantic models for SC2Pulse responses.

Written from the recorded fixtures in ``tests/fixtures``. Every model ignores unknown
keys; fields that are not always present are optional.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

from smurfsniper.api.sc2pulse.ids import HistoryColumn
from smurfsniper.logger import logger


class _Model(BaseModel):
    model_config = ConfigDict(
        extra="ignore", populate_by_name=True, alias_generator=to_camel, frozen=True
    )


def _none_to_zero(v: Any) -> Any:
    return 0 if v is None else v


# --------------------------------------------------------------------- identity
class Character(_Model):
    id: int
    account_id: int
    region: str
    realm: int
    battlenet_id: int
    name: str
    tag: str | None = None
    discriminator: int | None = None

    @property
    def base_name(self) -> str:
        return self.name.split("#")[0]


class Account(_Model):
    id: int
    battle_tag: str | None = None
    tag: str | None = None
    discriminator: int | None = None
    partition: str | None = None


class Clan(_Model):
    id: int
    tag: str
    name: str | None = None
    region: str | None = None
    members: int | None = None
    active_members: int | None = None
    avg_rating: int | None = None
    avg_league_type: int | None = None
    games: int | None = None


class ProPlayer(_Model):
    id: int
    aligulac_id: int | None = None
    nickname: str | None = None
    name: str | None = None
    country: str | None = None
    birthday: date | None = None
    earnings: int | None = None


class ProTeam(_Model):
    id: int | None = None
    name: str | None = None
    short_name: str | None = None
    aligulac_id: int | None = None


class SocialLink(_Model):
    """A link from ``proPlayer.links`` (``url``) or ``/character-links`` (``absoluteUrl``)."""

    type: str
    url: str
    relative_url: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _absolute(cls, data: Any) -> Any:
        if isinstance(data, dict) and not data.get("url") and data.get("absoluteUrl"):
            data = {**data, "url": data["absoluteUrl"]}
        return data


class ProPlayerEntry(_Model):
    pro_player: ProPlayer
    pro_team: ProTeam | None = None
    links: list[SocialLink] = Field(default_factory=list)


class Member(_Model):
    character: Character
    account: Account | None = None
    clan: Clan | None = None
    pro_id: int | None = None
    pro_nickname: str | None = None
    pro_team: str | None = None
    pro_player: ProPlayerEntry | None = None
    terran_games_played: int = 0
    protoss_games_played: int = 0
    zerg_games_played: int = 0
    random_games_played: int = 0
    race_games: dict[str, int] = Field(default_factory=dict)

    _zero = field_validator(
        "terran_games_played",
        "protoss_games_played",
        "zerg_games_played",
        "random_games_played",
        mode="before",
    )(_none_to_zero)

    @field_validator("race_games", mode="before")
    @classmethod
    def _race_games(cls, v: Any) -> Any:
        return v or {}

    @property
    def main_race(self) -> str | None:
        if not self.race_games:
            return None
        return max(self.race_games, key=lambda r: self.race_games[r])


class SeasonStats(_Model):
    rating: int | None = None
    games_played: int | None = None
    rank: int | None = None


class LadderDistinctCharacter(_Model):
    league_max: int | None = None
    rating_max: int | None = None
    total_games_played: int | None = None
    previous_stats: SeasonStats = Field(default_factory=SeasonStats)
    current_stats: SeasonStats = Field(default_factory=SeasonStats)
    members: Member

    @field_validator("previous_stats", "current_stats", mode="before")
    @classmethod
    def _stats(cls, v: Any) -> Any:
        return v or {}

    @property
    def character(self) -> Character:
        return self.members.character

    @property
    def rating(self) -> int | None:
        """Current season rating, falling back to the previous season."""
        return self.current_stats.rating or self.previous_stats.rating


# ------------------------------------------------------------------------ teams
class LeagueRef(_Model):
    type: int | None = None
    queue_type: int | None = None
    team_type: int | None = None


class LadderTeam(_Model):
    id: int
    rating: int | None = None
    wins: int = 0
    losses: int = 0
    ties: int = 0
    season: int
    region: str
    league: LeagueRef | None = None
    league_type: int | None = None
    tier_type: int | None = None
    global_rank: int | None = None
    region_rank: int | None = None
    league_rank: int | None = None
    global_team_count: int | None = None
    region_team_count: int | None = None
    league_team_count: int | None = None
    last_played: datetime | None = None
    joined: datetime | None = None
    legacy_id: str | None = None
    legacy_uid: str | None = None
    queue_type: int | None = None
    team_type: int | None = None
    members: list[Member] = Field(default_factory=list)

    _zero = field_validator("wins", "losses", "ties", mode="before")(_none_to_zero)

    @property
    def league_id(self) -> int | None:
        if self.league_type is not None:
            return self.league_type
        return self.league.type if self.league else None

    @property
    def region_percentile(self) -> float | None:
        """Share of the region ladder this team is above (99.9 = top 0.1%)."""
        if not self.region_rank or not self.region_team_count:
            return None
        return 100.0 * (1 - self.region_rank / self.region_team_count)

    @property
    def character_ids(self) -> set[int]:
        return {m.character.id for m in self.members}


# ---------------------------------------------------------------------- matches
class MatchInfo(_Model):
    id: int
    date: datetime
    type: str
    map_id: int | None = None
    region: str
    duration: int | None = None


class MapInfo(_Model):
    id: int
    name: str


class Participant(_Model):
    match_id: int
    player_character_id: int
    team_id: int | None = None
    decision: str | None = None
    rating_change: int | None = None


class TeamStateInner(_Model):
    rating: int | None = None
    wins: int | None = None
    games: int | None = None


class TeamState(_Model):
    team_state: TeamStateInner | None = None
    race: str | None = None
    league: LeagueRef | None = None
    tier: int | None = None
    season: int | None = None

    @field_validator("league", mode="before")
    @classmethod
    def _league(cls, v: Any) -> Any:
        if isinstance(v, int):
            return {"type": v}
        return v


class MatchParticipant(_Model):
    participant: Participant
    team: LadderTeam | None = None
    team_state: TeamState | None = None
    twitch_vod_url: str | None = None
    sub_only_twitch_vod: bool | None = None

    @property
    def race(self) -> str | None:
        """Race played in this match (team state, else the team member's only race)."""
        if self.team_state and self.team_state.race:
            return self.team_state.race
        if self.team:
            for m in self.team.members:
                if m.character.id == self.participant.player_character_id and m.race_games:
                    return m.main_race
        return None


class LadderMatch(_Model):
    match: MatchInfo
    map: MapInfo | None = None
    participants: list[MatchParticipant] = Field(default_factory=list)

    def participant_for(self, character_id: int) -> MatchParticipant | None:
        for p in self.participants:
            if p.participant.player_character_id == character_id:
                return p
        return None

    def opponents_of(self, character_id: int) -> list[MatchParticipant]:
        me = self.participant_for(character_id)
        if me is None:
            return []
        out = []
        for p in self.participants:
            if p is me:
                continue
            if (
                me.participant.team_id is not None
                and p.participant.team_id == me.participant.team_id
            ):
                continue
            out.append(p)
        return out


class Navigation(_Model):
    before: str | None = None
    after: str | None = None


class Page[T](_Model):
    result: list[T] = Field(default_factory=list)
    navigation: Navigation | None = None


class CharacterLinks(_Model):
    player_character_id: int
    links: list[SocialLink] = Field(default_factory=list)
    failed_types: list[str] = Field(default_factory=list)


class EntityGroup(_Model):
    characters: list[LadderDistinctCharacter] = Field(default_factory=list)
    clans: list[Clan] = Field(default_factory=list)
    pro_players: list[ProPlayerEntry] = Field(default_factory=list)
    accounts: list[Account] = Field(default_factory=list)


# ---------------------------------------------------------------------- history
class TeamHistorySeries(_Model):
    """Column-oriented ``/team-histories`` entry."""

    legacy_uid: str
    columns: dict[str, list] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _parse(cls, data: Any) -> Any:
        if not isinstance(data, dict) or "staticData" not in data:
            return data
        static = data.get("staticData") or {}
        uid = static.get("LEGACY_UID") or static.get("LEGACY_ID") or ""
        history = data.get("history") or {}
        cols = {k: list(v) for k, v in history.items() if isinstance(v, list)}
        if cols:
            n = min(len(v) for v in cols.values())
            if any(len(v) != n for v in cols.values()):
                logger.debug(f"team-history {uid}: unequal column lengths, truncating to {n}")
                cols = {k: v[:n] for k, v in cols.items()}
        return {"legacy_uid": str(uid), "columns": cols}

    def column(self, c: HistoryColumn | str) -> list | None:
        return self.columns.get(str(c))

    def __len__(self) -> int:
        return min((len(v) for v in self.columns.values()), default=0)


class TeamHistorySummary(_Model):
    legacy_uid: str
    games: int | None = None
    league_type_max: int | None = None
    rating_min: int | None = None
    rating_avg: float | None = None
    rating_max: int | None = None
    rating_last: int | None = None
    region_rank_last: int | None = None
    region_team_count_last: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _parse(cls, data: Any) -> Any:
        if not isinstance(data, dict) or "staticData" not in data:
            return data
        static = data.get("staticData") or {}
        summary = data.get("summary") or {}
        out = {k.lower(): v for k, v in summary.items()}
        out["legacy_uid"] = str(static.get("LEGACY_UID") or static.get("LEGACY_ID") or "")
        return out


# ---------------------------------------------------------------------- seasons
class Season(_Model):
    id: int
    battlenet_id: int
    region: str
    year: int
    number: int
    start: datetime
    end: datetime


class TierThresholds(_Model):
    """``{region: {league: {tier: (lo, hi)}}}``. Grandmaster bands are ``(0, 0)``."""

    by_region: dict[str, dict[int, dict[int, tuple[int, int]]]] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _parse(cls, data: Any) -> Any:
        if isinstance(data, dict) and "by_region" not in data and "byRegion" not in data:
            return {"by_region": data}
        return data

    def band(self, region: str, rating: int) -> tuple[int, int, int, int] | None:
        """``(league, tier, lo, hi)`` containing ``rating``; tier 0 is the top tier."""
        for league, tiers in sorted(self.by_region.get(region, {}).items()):
            for tier, (lo, hi) in sorted(tiers.items()):
                if hi and lo <= rating < hi:
                    return league, tier, lo, hi
        return None


# ---------------------------------------------------------------------- streams
class Stream(_Model):
    service: str
    user_name: str
    title: str | None = None
    url: str
    viewer_count: int | None = None
    language: str | None = None
    thumbnail_url: str | None = None


class StreamEntry(_Model):
    stream: Stream
    pro_player: ProPlayerEntry | None = None
    team: LadderTeam | None = None


class StreamsResponse(_Model):
    streams: list[StreamEntry] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------ misc / stats
class PatchInfo(_Model):
    id: int
    build: int
    version: str
    versus: bool | None = None


class PatchEntry(_Model):
    patch: PatchInfo
    releases: dict[str, datetime] = Field(default_factory=dict)


class QueueStats(_Model):
    """``/stats/player-base`` row (one per season)."""

    id: int | None = None
    season: int
    queue_type: int | None = None
    team_type: int | None = None
    player_base: int | None = None
    player_count: int | None = None
    low_activity_player_count: int | None = None
    medium_activity_player_count: int | None = None
    high_activity_player_count: int | None = None


class SeasonActivity(_Model):
    """Per-season activity counters. Keys: region codes, league ids or race names."""

    region_team_count: dict[str, int] = Field(default_factory=dict)
    league_team_count: dict[str, int] = Field(default_factory=dict)
    race_team_count: dict[str, int] = Field(default_factory=dict)
    region_games_played: dict[str, int] = Field(default_factory=dict)
    league_games_played: dict[str, int] = Field(default_factory=dict)
    race_games_played: dict[str, int] = Field(default_factory=dict)


class ActivityStats(_Model):
    """``/stats/activity``: ``{season: SeasonActivity}``."""

    by_season: dict[int, SeasonActivity] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _parse(cls, data: Any) -> Any:
        if isinstance(data, dict) and "by_season" not in data and "bySeason" not in data:
            return {"by_season": data}
        return data


class BalanceFrame(_Model):
    map_stats_film_id: int
    number: int | None = None  # game minute; None = whole game
    wins: int = 0
    games: int = 0


class BalanceReport(_Model):
    """``/stats/balance-reports``. Lookup tables are kept as loosely typed dicts.

    Keys: ``maps`` (id -> {id, name}), ``seasons``, ``leagues``, ``tiers``,
    ``specs`` (id -> {race, versusRace, frameDuration}), ``films``
    (id -> {mapId, leagueTierId, mapStatsFilmSpecId, crossTier}) and ``frames``.
    """

    maps: dict[str, MapInfo] = Field(default_factory=dict)
    seasons: dict[str, dict[str, Any]] = Field(default_factory=dict)
    leagues: dict[str, dict[str, Any]] = Field(default_factory=dict)
    tiers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    specs: dict[str, dict[str, Any]] = Field(default_factory=dict)
    films: dict[str, dict[str, Any]] = Field(default_factory=dict)
    frames: list[BalanceFrame] = Field(default_factory=list)


class ClanEvent(_Model):
    player_character_id: int
    clan_id: int
    type: str
    created: datetime
    seconds_since_previous: int | None = None


class ClanHistory(_Model):
    characters: list[LadderDistinctCharacter] = Field(default_factory=list)
    clans: list[Clan] = Field(default_factory=list)
    events: list[ClanEvent] = Field(default_factory=list)
