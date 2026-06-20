"""Central client for the SC2Pulse API (https://sc2pulse.nephest.com).

One pooled ``httpx.Client`` is shared across the process instead of opening a
new connection per request. All calls go through ``_get`` which encodes query
params, checks status, and retries transient failures (429 / 5xx / network
errors) with exponential backoff. Errors surface as ``SC2PulseError`` so callers
never have to know about httpx internals.
"""

from __future__ import annotations

import random
import time
from functools import lru_cache
from typing import Dict, List, Optional, Sequence

import httpx

from smurfsniper.logger import logger
from smurfsniper.models.team_history import (
    TeamHistory,
    TeamHistoryData,
    TeamHistoryPoint,
)

BASE_URL = "https://sc2pulse.nephest.com/sc2/api"
TIMEOUT = 25.0
MAX_RETRIES = 3
BACKOFF_BASE = 0.5  # seconds; doubled each retry, plus jitter
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_UID_BATCH = 10  # max team legacy UIDs per /team-histories request

# Fixed params shared by every team-histories request.
_HISTORY_PARAMS = [
    ("groupBy", "LEGACY_UID"),
    ("static", "LEGACY_ID"),
    ("history", "TIMESTAMP"),
    ("history", "RATING"),
]


class SC2PulseError(Exception):
    """Any failure talking to the SC2Pulse API."""


class SC2PulseNotFound(SC2PulseError):
    """The API responded but no matching record was found."""


_client: Optional[httpx.Client] = None


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(base_url=BASE_URL, timeout=TIMEOUT)
    return _client


def close() -> None:
    """Close the shared client (e.g. on shutdown). Safe to call repeatedly."""
    global _client
    if _client is not None:
        _client.close()
        _client = None


def _get(path: str, params) -> list:
    """GET ``path`` and return parsed JSON, retrying transient failures.

    ``params`` is passed straight to httpx (dict or list of pairs) so values are
    URL-encoded. Raises ``SC2PulseError`` on non-retryable or exhausted failures.
    """
    client = _get_client()
    last_exc: Optional[Exception] = None

    for attempt in range(MAX_RETRIES):
        try:
            resp = client.get(path, params=params)
        except httpx.TransportError as exc:  # timeout, connection, DNS, etc.
            last_exc = exc
        else:
            if resp.status_code in RETRYABLE_STATUS:
                last_exc = httpx.HTTPStatusError(
                    f"{resp.status_code} from {resp.url}",
                    request=resp.request,
                    response=resp,
                )
            else:
                try:
                    resp.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise SC2PulseError(str(exc)) from exc
                try:
                    return resp.json()
                except ValueError as exc:
                    raise SC2PulseError(f"Invalid JSON from {resp.url}") from exc

        if attempt < MAX_RETRIES - 1:
            delay = BACKOFF_BASE * (2 ** attempt) + random.uniform(0, BACKOFF_BASE)
            logger.warning(
                f"SC2Pulse {path} failed ({last_exc}); retry {attempt + 1}/"
                f"{MAX_RETRIES - 1} in {delay:.1f}s"
            )
            time.sleep(delay)

    raise SC2PulseError(f"SC2Pulse {path} failed after retries: {last_exc}")


def search_characters(name: str) -> list:
    """GET /characters?query=<name>. Returns raw character entries."""
    return _get("/characters", {"query": name})


def character_teams(character_id: int) -> list:
    """GET /character-teams?characterId=<id>. Returns raw team entries."""
    return _get("/character-teams", {"characterId": character_id})


def character_links(character_id: int) -> list:
    """GET /character-links?characterId=<id>. Returns raw link-group entries."""
    return _get("/character-links", {"characterId": character_id})


def character_matches(character_id: int, limit: int = 25) -> list:
    """GET /character-matches?characterId=<id>. Returns the ``result`` list.

    The endpoint wraps matches in ``{"result": [...], "navigation": {...}}``;
    this unwraps to the result list (empty when the player has no tracked games).
    """
    data = _get("/character-matches", {"characterId": character_id, "limit": limit})
    if isinstance(data, dict):
        return data.get("result", [])
    return data


@lru_cache(maxsize=1)
def current_season() -> int:
    """Latest season battlenetId. Cached for the process (changes ~quarterly)."""
    data = _get("/season/list/all", None)
    return data[0]["battlenetId"]


@lru_cache(maxsize=32)
def tier_thresholds(queue: str, team_type: str, season: int, region: str) -> dict:
    """MMR bounds per league/tier: {region: {leagueType: {tier: [lo, hi]}}}.

    Cached per (queue, team_type, season, region) since bounds are stable
    within a season.
    """
    return _get(
        "/tier-thresholds",
        {"queue": queue, "teamType": team_type, "season": season, "region": region},
    )


_STREAMS_TTL = 30.0  # seconds; live-stream list changes slowly
_streams_cache: Optional[list] = None
_streams_fetched_at = 0.0


@lru_cache(maxsize=256)
def pro_player(pro_player_id: int) -> Optional[dict]:
    """Full pro bio + external links via /entities?proPlayerId.

    Returns the first ``proPlayers`` entry ({proPlayer, proTeam, links}) or
    None. Cached per id (bio changes rarely).
    """
    data = _get("/entities", {"proPlayerId": pro_player_id})
    entries = data.get("proPlayers") if isinstance(data, dict) else None
    return entries[0] if entries else None


def streams(limit: int = 100) -> list:
    """Currently-live identified SC2 streams. Returns the ``streams`` list.

    Cached for ``_STREAMS_TTL`` so multiple opponents in one game share a
    single request.
    """
    global _streams_cache, _streams_fetched_at
    now = time.monotonic()
    if _streams_cache is not None and now - _streams_fetched_at < _STREAMS_TTL:
        return _streams_cache

    data = _get("/streams", {"limit": limit})
    _streams_cache = data.get("streams", []) if isinstance(data, dict) else data
    _streams_fetched_at = now
    return _streams_cache


def team_histories(legacy_uids: Sequence[str]) -> list:
    """GET /team-histories for the given team legacy UIDs.

    The API caps UIDs per request, so callers passing more than ``_UID_BATCH``
    are split across multiple requests and the results concatenated.
    """
    uids = [u for u in legacy_uids if u]
    if not uids:
        return []

    merged: list = []
    for i in range(0, len(uids), _UID_BATCH):
        batch = uids[i : i + _UID_BATCH]
        params = [("teamLegacyUid", uid) for uid in batch] + _HISTORY_PARAMS
        merged.extend(_get("/team-histories", params))
    return merged


def parse_team_history(data, legacy_uid: str) -> Optional[TeamHistory]:
    """Merge a /team-histories response into a single deduped ``TeamHistory``.

    Reuses ``TeamHistoryData`` for parsing + TIMESTAMP/RATING length validation.
    Returns ``None`` when there are no points.
    """
    merged_points: List[TeamHistoryPoint] = []

    for entry in data:
        history = entry.get("history") if isinstance(entry, dict) else None
        if not history:
            continue
        try:
            merged_points.extend(TeamHistoryData.model_validate(history).to_points())
        except (ValueError, TypeError) as exc:
            logger.warning(f"Skipping malformed team-history entry: {exc}")

    if not merged_points:
        return None

    merged_points.sort(key=lambda p: p.timestamp)

    deduped: List[TeamHistoryPoint] = []
    last_ts = None
    for p in merged_points:
        if p.timestamp != last_ts:
            deduped.append(p)
            last_ts = p.timestamp

    return TeamHistory(
        legacy_uid=legacy_uid,
        timestamps=[p.timestamp for p in deduped],
        ratings=[p.rating for p in deduped],
    )
