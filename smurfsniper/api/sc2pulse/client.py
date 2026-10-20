"""Typed client for the SC2Pulse API (https://sc2pulse.nephest.com/sc2/api).

Data: SC2Pulse (sc2pulse.nephest.com), non-commercial use.

Every method accepts ``force_refresh`` (bypass the cache, still store the result).
Selector lists are chunked to the API maximums and the results concatenated.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import datetime
from typing import Any, TypeVar

from pydantic import TypeAdapter, ValidationError

from smurfsniper.api.cache import CachePolicy
from smurfsniper.api.errors import BadResponse, NotFound
from smurfsniper.api.params import build_params
from smurfsniper.api.sc2pulse.ids import (
    HistoryColumn,
    League,
    LinkType,
    MatchType,
    Queue,
    SummaryColumn,
    TeamType,
)
from smurfsniper.api.sc2pulse.models import (
    ActivityStats,
    BalanceReport,
    CharacterLinks,
    Clan,
    ClanHistory,
    EntityGroup,
    LadderDistinctCharacter,
    LadderMatch,
    LadderTeam,
    Page,
    PatchEntry,
    ProPlayerEntry,
    QueueStats,
    Season,
    StreamsResponse,
    TeamHistorySeries,
    TeamHistorySummary,
    TierThresholds,
)
from smurfsniper.api.transport import HttpTransport, TokenBucket
from smurfsniper.logger import logger

BASE_URL = "https://sc2pulse.nephest.com/sc2/api"
SERVICE = "sc2pulse"
ATTRIBUTION = "Data: SC2Pulse (sc2pulse.nephest.com), non-commercial use"

DEFAULT_HISTORY_COLUMNS: tuple[HistoryColumn, ...] = (
    HistoryColumn.TIMESTAMP,
    HistoryColumn.RATING,
    HistoryColumn.GAMES,
    HistoryColumn.WINS,
    HistoryColumn.SEASON,
    HistoryColumn.LEAGUE_TYPE,
    HistoryColumn.TIER_TYPE,
    HistoryColumn.REGION_RANK,
    HistoryColumn.REGION_TEAM_COUNT,
)

# API maximums per selector.
MAX_CHARACTER_IDS = 500
MAX_ACCOUNT_IDS = 500
MAX_TOON_HANDLES = 500
MAX_CLAN_IDS = 20
MAX_PRO_PLAYER_IDS = 50
MAX_HISTORY_UIDS = 10
MAX_LAST_UIDS = 100
MAX_TEAM_IDS = 1500
MAX_SEASONS = 10

_SEARCH = CachePolicy(600, 600)
_CHARS = CachePolicy(600)
_ACCOUNT = CachePolicy(3600)
_TEAMS = CachePolicy(300)
_MATCHES = CachePolicy(300)
_LINKS = CachePolicy(86400)
_ENTITIES = CachePolicy(86400)
_TEAMS_UID = CachePolicy(1800)
_LADDER = CachePolicy(600)
_RECENT = CachePolicy(120)
_SUMMARIES = CachePolicy(1800)
_SEASONS = CachePolicy(43200)
_THRESHOLDS = CachePolicy(43200)
_STREAMS = CachePolicy(60, disk=False)
_STATS = CachePolicy(86400)
_VOD = CachePolicy(600)
_CLANS = CachePolicy(3600)

M = TypeVar("M")


def make_limiter() -> TokenBucket:
    return TokenBucket(rate_per_s=4, burst=10)


def _chunks(items: Sequence[Any], size: int) -> Iterator[list[Any]]:
    items = list(items)
    for i in range(0, len(items), size):
        yield items[i : i + size]


def _base_name(name: str) -> str:
    return name.split("#")[0].strip()


class SC2PulseClient:
    def __init__(self, transport: HttpTransport):
        self.transport = transport

    # ------------------------------------------------------------- plumbing
    def _get(
        self,
        path: str,
        params: list[tuple[str, str]],
        policy: CachePolicy,
        force_refresh: bool,
    ) -> Any:
        return self.transport.get_json(path, params, policy=policy, force_refresh=force_refresh)

    @staticmethod
    def _parse(adapter_type: Any, data: Any, path: str) -> Any:
        try:
            return TypeAdapter(adapter_type).validate_python(data)
        except ValidationError as e:
            raise BadResponse(SERVICE, f"{path}: {e.error_count()} validation error(s)") from e

    @staticmethod
    def _parse_many(model: type[M], data: Any, path: str) -> list[M]:
        """Validate a list, skipping entries that fail (logged at WARNING)."""
        if not isinstance(data, list):
            raise BadResponse(SERVICE, f"{path}: expected a list")
        out: list[M] = []
        skipped = 0
        for item in data:
            try:
                out.append(model.model_validate(item))
            except ValidationError:
                skipped += 1
        if skipped:
            logger.warning(f"sc2pulse {path}: skipped {skipped} invalid entr(y/ies)")
        return out

    @staticmethod
    def _page(model: Any, data: Any, path: str) -> Page:
        if isinstance(data, list):
            data = {"result": data, "navigation": None}
        return SC2PulseClient._parse(Page[model], data, path)

    def _selector_calls(
        self,
        path: str,
        selectors: Sequence[tuple[str, Sequence[Any], int]],
        extra: list[tuple[str, str]],
        policy: CachePolicy,
        force_refresh: bool,
    ) -> list[Any]:
        """One request per selector chunk; returns the raw JSON payloads."""
        payloads = []
        for name, values, size in selectors:
            for chunk in _chunks(values, size):
                params = build_params(**{name: chunk}) + extra
                payloads.append(self._get(path, params, policy, force_refresh))
        return payloads

    # ----------------------------------------------------------- characters
    def search_characters(
        self, query: str, *, force_refresh: bool = False
    ) -> list[LadderDistinctCharacter]:
        """``/characters?query=``. The ``#discriminator`` is stripped from ``query``."""
        q = _base_name(query)
        if not q:
            return []
        data = self._get("/characters", build_params(query=q), _SEARCH, force_refresh)
        return self._parse_many(LadderDistinctCharacter, data, "/characters?query")

    def find_character_ids(
        self,
        name: str,
        *,
        region: str | None = None,
        queues: Sequence[Queue] = (),
        seasons: Sequence[int] = (),
        case_sensitive: bool = False,
        force_refresh: bool = False,
    ) -> list[int]:
        """Cheap id-only advanced search (``/characters?field=id&name=``).

        Allowed: 0 or 1 season with many queues, or many seasons (max 10) with 0 or 1
        queue.
        """
        if len(seasons) > MAX_SEASONS:
            raise ValueError(f"at most {MAX_SEASONS} seasons")
        if len(seasons) > 1 and len(queues) > 1:
            raise ValueError("use either many seasons or many queues, not both")
        params = build_params(
            field="id",
            name=_base_name(name),
            region=region,
            queue=list(queues),
            season=list(seasons),
            caseSensitive=case_sensitive,
        )
        data = self._get("/characters", params, _CHARS, force_refresh)
        out: list[int] = []
        for item in data or []:
            if isinstance(item, int):
                out.append(item)
            elif isinstance(item, dict) and "id" in item:
                out.append(int(item["id"]))
        return out

    def _characters(
        self,
        policy: CachePolicy,
        *,
        character_ids: Sequence[int] = (),
        account_ids: Sequence[int] = (),
        toon_handles: Sequence[str] = (),
        clan_ids: Sequence[int] = (),
        pro_player_ids: Sequence[int] = (),
        force_refresh: bool = False,
    ) -> list[LadderDistinctCharacter]:
        payloads = self._selector_calls(
            "/characters",
            [
                ("characterId", character_ids, MAX_CHARACTER_IDS),
                ("accountId", account_ids, MAX_ACCOUNT_IDS),
                ("toonHandle", toon_handles, MAX_TOON_HANDLES),
                ("clanId", clan_ids, MAX_CLAN_IDS),
                ("proPlayerId", pro_player_ids, MAX_PRO_PLAYER_IDS),
            ],
            [],
            policy,
            force_refresh,
        )
        out: list[LadderDistinctCharacter] = []
        for data in payloads:
            out.extend(self._parse_many(LadderDistinctCharacter, data, "/characters"))
        return out

    def characters(
        self,
        *,
        character_ids: Sequence[int] = (),
        account_ids: Sequence[int] = (),
        toon_handles: Sequence[str] = (),
        clan_ids: Sequence[int] = (),
        pro_player_ids: Sequence[int] = (),
        force_refresh: bool = False,
    ) -> list[LadderDistinctCharacter]:
        return self._characters(
            _CHARS,
            character_ids=character_ids,
            account_ids=account_ids,
            toon_handles=toon_handles,
            clan_ids=clan_ids,
            pro_player_ids=pro_player_ids,
            force_refresh=force_refresh,
        )

    def account_characters(
        self, account_id: int, *, force_refresh: bool = False
    ) -> list[LadderDistinctCharacter]:
        """Every character of a Battle.net account (alts across regions/realms)."""
        return self._characters(_ACCOUNT, account_ids=[account_id], force_refresh=force_refresh)

    # ---------------------------------------------------------- per player
    def character_teams(
        self,
        character_ids: Sequence[int],
        *,
        queues: Sequence[Queue] = (),
        seasons: Sequence[int] = (),
        races: Sequence[str] = (),
        limit: int | None = None,
        force_refresh: bool = False,
    ) -> list[LadderTeam]:
        """``/character-teams``. More than one id requires exactly one queue and season."""
        ids = list(character_ids)
        if len(ids) > 1 and (len(queues) != 1 or len(seasons) != 1):
            raise ValueError("multiple characters require exactly one queue and one season")
        extra = build_params(
            queue=list(queues), season=list(seasons), race=list(races), limit=limit
        )
        out: list[LadderTeam] = []
        for data in self._selector_calls(
            "/character-teams",
            [("characterId", ids, MAX_CHARACTER_IDS)],
            extra,
            _TEAMS,
            force_refresh,
        ):
            out.extend(self._parse_many(LadderTeam, data, "/character-teams"))
        return out

    def character_matches(
        self,
        character_ids: Sequence[int],
        *,
        types: Sequence[MatchType] = (),
        limit: int = 25,
        before: str | None = None,
        after: str | None = None,
        force_refresh: bool = False,
    ) -> Page[LadderMatch]:
        params = build_params(
            characterId=list(character_ids),
            type=list(types),
            limit=limit,
            before=before,
            after=after,
        )
        data = self._get("/character-matches", params, _MATCHES, force_refresh)
        return self._page(LadderMatch, data, "/character-matches")

    def iter_character_matches(
        self,
        character_ids: Sequence[int],
        *,
        types: Sequence[MatchType] = (),
        page_size: int = 50,
        max_items: int = 100,
        force_refresh: bool = False,
    ) -> Iterator[LadderMatch]:
        """Follow ``navigation.after`` cursors until ``max_items`` matches are yielded."""
        cursor: str | None = None
        seen = 0
        while seen < max_items:
            page = self.character_matches(
                character_ids,
                types=types,
                limit=min(page_size, max_items - seen),
                after=cursor,
                force_refresh=force_refresh,
            )
            for m in page.result:
                yield m
                seen += 1
                if seen >= max_items:
                    return
            cursor = page.navigation.after if page.navigation else None
            if not page.result or not cursor:
                return

    def character_links(
        self,
        character_ids: Sequence[int],
        *,
        types: Sequence[LinkType] = (),
        force_refresh: bool = False,
    ) -> list[CharacterLinks]:
        out: list[CharacterLinks] = []
        for data in self._selector_calls(
            "/character-links",
            [("characterId", list(character_ids), MAX_CHARACTER_IDS)],
            build_params(type=list(types)),
            _LINKS,
            force_refresh,
        ):
            out.extend(self._parse_many(CharacterLinks, data, "/character-links"))
        return out

    def entities(
        self,
        *,
        character_ids: Sequence[int] = (),
        clan_ids: Sequence[int] = (),
        pro_player_ids: Sequence[int] = (),
        account_ids: Sequence[int] = (),
        toon_handles: Sequence[str] = (),
        force_refresh: bool = False,
    ) -> EntityGroup:
        """Mixed-kind batch lookup in one call."""
        params = build_params(
            characterId=list(character_ids),
            clanId=list(clan_ids),
            proPlayerId=list(pro_player_ids),
            accountId=list(account_ids),
            toonHandle=list(toon_handles),
        )
        data = self._get("/entities", params, _ENTITIES, force_refresh)
        return self._parse(EntityGroup, data or {}, "/entities")

    def pro_player(
        self, pro_player_id: int, *, force_refresh: bool = False
    ) -> ProPlayerEntry | None:
        group = self.entities(pro_player_ids=[pro_player_id], force_refresh=force_refresh)
        return group.pro_players[0] if group.pro_players else None

    # ---------------------------------------------------------------- teams
    def teams_last(
        self, legacy_uids: Sequence[str], *, force_refresh: bool = False
    ) -> list[LadderTeam]:
        """Newest team per legacy uid (even from past seasons)."""
        out: list[LadderTeam] = []
        for data in self._selector_calls(
            "/teams",
            [("teamLegacyUid", list(legacy_uids), MAX_LAST_UIDS)],
            build_params(last=True),
            _TEAMS,
            force_refresh,
        ):
            out.extend(self._parse_many(LadderTeam, data, "/teams?last"))
        return out

    def teams_by_legacy_uid(
        self,
        legacy_uids: Sequence[str],
        *,
        season_min: int | None = None,
        season_max: int | None = None,
        force_refresh: bool = False,
    ) -> list[LadderTeam]:
        """Per-season teams for each legacy uid (final MMR/league per season)."""
        out: list[LadderTeam] = []
        for data in self._selector_calls(
            "/teams",
            [("teamLegacyUid", list(legacy_uids), MAX_HISTORY_UIDS)],
            build_params(seasonMin=season_min, seasonMax=season_max),
            _TEAMS_UID,
            force_refresh,
        ):
            out.extend(self._parse_many(LadderTeam, data, "/teams?teamLegacyUid"))
        return out

    def teams_by_id(
        self, team_ids: Sequence[int], *, force_refresh: bool = False
    ) -> list[LadderTeam]:
        out: list[LadderTeam] = []
        for data in self._selector_calls(
            "/teams",
            [("teamId", list(team_ids), MAX_TEAM_IDS)],
            [],
            _TEAMS,
            force_refresh,
        ):
            out.extend(self._parse_many(LadderTeam, data, "/teams?teamId"))
        return out

    def ladder(
        self,
        queue: Queue,
        team_type: TeamType,
        season: int,
        *,
        regions: Sequence[str] = (),
        leagues: Sequence[League] = (),
        sort: str = "-rating",
        before: str | None = None,
        after: str | None = None,
        force_refresh: bool = False,
    ) -> Page[LadderTeam]:
        """Ladder browser, 100 teams per page."""
        params = build_params(
            queue=queue,
            teamType=team_type,
            season=season,
            region=list(regions),
            league=list(leagues),
            sort=sort,
            before=before,
            after=after,
        )
        data = self._get("/teams", params, _LADDER, force_refresh)
        return self._page(LadderTeam, data, "/teams?queue&season")

    def recent_teams(
        self,
        queue: Queue,
        *,
        league: League | None = None,
        region: str | None = None,
        race: str | None = None,
        wins_min: int | None = None,
        wins_max: int | None = None,
        rating_min: int | None = None,
        rating_max: int | None = None,
        limit: int = 50,
        force_refresh: bool = False,
    ) -> list[LadderTeam]:
        """Recently played teams (activity feed)."""
        params = build_params(
            recent=True,
            queue=queue,
            league=league,
            region=region,
            race=race,
            winsMin=wins_min,
            winsMax=wins_max,
            ratingMin=rating_min,
            ratingMax=rating_max,
            limit=limit,
        )
        data = self._get("/teams", params, _RECENT, force_refresh)
        return self._parse_many(LadderTeam, data, "/teams?recent")

    # -------------------------------------------------------------- history
    def team_histories(
        self,
        legacy_uids: Sequence[str],
        *,
        columns: Sequence[HistoryColumn] = DEFAULT_HISTORY_COLUMNS,
        from_: datetime | None = None,
        to: datetime | None = None,
        force_refresh: bool = False,
    ) -> list[TeamHistorySeries]:
        extra = build_params(
            groupBy="LEGACY_UID",
            static="LEGACY_ID",
            history=list(columns),
            from_=from_,
            to=to,
        )
        out: list[TeamHistorySeries] = []
        for data in self._selector_calls(
            "/team-histories",
            [("teamLegacyUid", [u for u in legacy_uids if u], MAX_HISTORY_UIDS)],
            extra,
            _TEAMS,
            force_refresh,
        ):
            out.extend(self._parse_many(TeamHistorySeries, data, "/team-histories"))
        return out

    def team_history_summaries(
        self,
        legacy_uids: Sequence[str],
        *,
        columns: Sequence[SummaryColumn] = tuple(SummaryColumn),
        from_: datetime | None = None,
        to: datetime | None = None,
        force_refresh: bool = False,
    ) -> list[TeamHistorySummary]:
        """Tiny aggregates per team: peak rating, total games, max league."""
        extra = build_params(
            groupBy="LEGACY_UID",
            static="LEGACY_ID",
            summary=list(columns),
            from_=from_,
            to=to,
        )
        out: list[TeamHistorySummary] = []
        for data in self._selector_calls(
            "/team-history-summaries",
            [("teamLegacyUid", [u for u in legacy_uids if u], MAX_HISTORY_UIDS)],
            extra,
            _SUMMARIES,
            force_refresh,
        ):
            out.extend(self._parse_many(TeamHistorySummary, data, "/team-history-summaries"))
        return out

    # -------------------------------------------------------------- seasons
    def seasons(
        self, battlenet_id: int | None = None, *, force_refresh: bool = False
    ) -> list[Season]:
        data = self._get("/seasons", build_params(season=battlenet_id), _SEASONS, force_refresh)
        return self._parse_many(Season, data, "/seasons")

    def current_season(self, region: str = "EU", *, force_refresh: bool = False) -> Season:
        """Newest season by ``start`` for ``region`` (any region if it has none)."""
        seasons = self.seasons(force_refresh=force_refresh)
        if not seasons:
            raise NotFound(SERVICE, "/seasons returned no seasons")
        mine = [s for s in seasons if s.region == region] or seasons
        return max(mine, key=lambda s: s.start)

    def tier_thresholds(
        self,
        queue: Queue,
        team_type: TeamType,
        season: int,
        *,
        regions: Sequence[str] = (),
        leagues: Sequence[League] = (),
        force_refresh: bool = False,
    ) -> TierThresholds:
        params = build_params(
            queue=queue,
            teamType=team_type,
            season=season,
            region=list(regions),
            league=list(leagues),
        )
        data = self._get("/tier-thresholds", params, _THRESHOLDS, force_refresh)
        return self._parse(TierThresholds, data or {}, "/tier-thresholds")

    # -------------------------------------------------------------- streams
    def streams(
        self,
        *,
        services: Sequence[str] = (),
        identified_only: bool | None = None,
        lax: bool | None = None,
        team_formats: Sequence[str] = (),
        races: Sequence[str] = (),
        languages: Sequence[str] = (),
        rating_min: int | None = None,
        rating_max: int | None = None,
        sort: str | None = None,
        limit: int | None = None,
        limit_player: int | None = None,
        force_refresh: bool = False,
    ) -> StreamsResponse:
        params = build_params(
            service=list(services),
            identifiedOnly=identified_only,
            lax=lax,
            teamFormat=list(team_formats),
            race=list(races),
            language=list(languages),
            ratingMin=rating_min,
            ratingMax=rating_max,
            sort=sort,
            limit=limit,
            limitPlayer=limit_player,
        )
        data = self._get("/streams", params, _STREAMS, force_refresh)
        return self._parse(StreamsResponse, data or {}, "/streams")

    # ---------------------------------------------------------------- stats
    def player_base_stats(
        self, queue: Queue, team_type: TeamType, *, force_refresh: bool = False
    ) -> list[QueueStats]:
        params = build_params(queue=queue, teamType=team_type)
        data = self._get("/stats/player-base", params, _STATS, force_refresh)
        return self._parse_many(QueueStats, data, "/stats/player-base")

    def activity_stats(
        self,
        queue: Queue,
        team_type: TeamType,
        *,
        regions: Sequence[str] = (),
        leagues: Sequence[League] = (),
        force_refresh: bool = False,
    ) -> ActivityStats:
        params = build_params(
            queue=queue, teamType=team_type, region=list(regions), league=list(leagues)
        )
        data = self._get("/stats/activity", params, _STATS, force_refresh)
        return self._parse(ActivityStats, data or {}, "/stats/activity")

    def balance_report(
        self,
        queue: Queue,
        team_type: TeamType,
        league: League,
        tier: int,
        season: int,
        *,
        regions: Sequence[str] = (),
        races: Sequence[str] = (),
        cross_tiers: Sequence[bool] = (),
        frame_number_max: int | None = None,
        force_refresh: bool = False,
    ) -> BalanceReport:
        """Matchup win rates by game minute and map.

        Warning: unfiltered payloads exceed 350 KB. Narrow with ``regions``/``races``.
        ``tier`` is 0-based (0 = tier 1); sent as FIRST/SECOND/THIRD.
        """
        params = build_params(
            queue=queue,
            teamType=team_type,
            league=league,
            tier=("FIRST", "SECOND", "THIRD")[tier],
            season=season,
            region=list(regions),
            race=list(races),
            crossTier=list(cross_tiers),
            frameNumberMax=frame_number_max,
        )
        data = self._get("/stats/balance-reports", params, _STATS, force_refresh)
        return self._parse(BalanceReport, data or {}, "/stats/balance-reports")

    def patches(
        self, build_min: int | None = None, *, force_refresh: bool = False
    ) -> list[PatchEntry]:
        data = self._get("/patches", build_params(buildMin=build_min), _STATS, force_refresh)
        return self._parse_many(PatchEntry, data, "/patches")

    # ------------------------------------------------------------ vods/clans
    def vod_matches(
        self,
        *,
        race: str | None = None,
        race_versus: str | None = None,
        rating_min: int | None = None,
        rating_max: int | None = None,
        duration_min: int | None = None,
        duration_max: int | None = None,
        include_sub_only: bool | None = None,
        map_id: int | None = None,
        before: str | None = None,
        after: str | None = None,
        force_refresh: bool = False,
    ) -> Page[LadderMatch]:
        params = build_params(
            vod=True,
            race=race,
            raceVersus=race_versus,
            ratingMin=rating_min,
            ratingMax=rating_max,
            durationMin=duration_min,
            durationMax=duration_max,
            includeSubOnly=include_sub_only,
            mapId=map_id,
            before=before,
            after=after,
        )
        data = self._get("/matches", params, _VOD, force_refresh)
        return self._page(LadderMatch, data, "/matches?vod")

    def clans(
        self,
        *,
        region: str | None = None,
        active_members_min: int | None = None,
        active_members_max: int | None = None,
        games_per_active_member_per_day_min: float | None = None,
        games_per_active_member_per_day_max: float | None = None,
        avg_rating_min: int | None = None,
        avg_rating_max: int | None = None,
        sort: str | None = None,
        before: str | None = None,
        after: str | None = None,
        force_refresh: bool = False,
    ) -> Page[Clan]:
        params = build_params(
            region=region,
            activeMembersMin=active_members_min,
            activeMembersMax=active_members_max,
            gamesPerActiveMemberPerDayMin=games_per_active_member_per_day_min,
            gamesPerActiveMemberPerDayMax=games_per_active_member_per_day_max,
            avgRatingMin=avg_rating_min,
            avgRatingMax=avg_rating_max,
            sort=sort,
            before=before,
            after=after,
        )
        data = self._get("/clans", params, _CLANS, force_refresh)
        return self._page(Clan, data, "/clans")

    def search_clans(
        self, query: str, *, limit: int = 20, force_refresh: bool = False
    ) -> list[Clan]:
        """Clan search by tag or name; capped client-side (the API is unbounded)."""
        data = self._get("/clans", build_params(query=query), _CLANS, force_refresh)
        return self._parse_many(Clan, data, "/clans?query")[:limit]

    def clan_histories(
        self,
        *,
        character_ids: Sequence[int] = (),
        clan_ids: Sequence[int] = (),
        pro_player_ids: Sequence[int] = (),
        account_ids: Sequence[int] = (),
        toon_handles: Sequence[str] = (),
        before: str | None = None,
        after: str | None = None,
        limit: int = 50,
        force_refresh: bool = False,
    ) -> ClanHistory:
        """Clan join/leave history."""
        params = build_params(
            characterId=list(character_ids),
            clanId=list(clan_ids),
            proPlayerId=list(pro_player_ids),
            accountId=list(account_ids),
            toonHandle=list(toon_handles),
            before=before,
            after=after,
            limit=limit,
        )
        data = self._get("/clan-histories", params, _CLANS, force_refresh)
        if isinstance(data, dict) and "result" in data:
            data = data["result"]
        return self._parse(ClanHistory, data or {}, "/clan-histories")
