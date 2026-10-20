"""Aligulac REST client (https://aligulac.com/api/v1). Needs a free API key.

The key is sent as a default query param: it never enters cache keys or logs.
"""

from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter, ValidationError

from smurfsniper.api.aligulac.models import (
    AligulacMatch,
    AligulacPlayer,
    AligulacPrediction,
    AligulacRatingPoint,
)
from smurfsniper.api.cache import CachePolicy
from smurfsniper.api.errors import AuthError, BadResponse, NotFound
from smurfsniper.api.params import build_params
from smurfsniper.api.transport import HttpTransport, TokenBucket

BASE_URL = "https://aligulac.com/api/v1"
SERVICE = "aligulac"
KEY_URL = "https://aligulac.com/about/api/"

_DAY = CachePolicy(86400)


def make_limiter() -> TokenBucket:
    return TokenBucket(rate_per_s=2, burst=4)


def default_params(api_key: str) -> dict[str, str]:
    return {"format": "json", "apikey": api_key}


def _objects(data: Any) -> list[Any]:
    """Unwrap Tastypie ``{"meta": ..., "objects": [...]}``."""
    if isinstance(data, dict):
        return list(data.get("objects") or [])
    return list(data or [])


class AligulacClient:
    def __init__(self, transport: HttpTransport):
        self.transport = transport

    def _parse(self, tp: Any, data: Any, path: str) -> Any:
        try:
            return TypeAdapter(tp).validate_python(data)
        except ValidationError as e:
            raise BadResponse(SERVICE, f"{path}: {e.error_count()} validation error(s)") from e

    def player(self, aligulac_id: int, *, force_refresh: bool = False) -> AligulacPlayer:
        path = f"/player/{int(aligulac_id)}/"
        data = self.transport.get_json(path, [], policy=_DAY, force_refresh=force_refresh)
        return self._parse(AligulacPlayer, data, path)

    def players_by_tag(self, tag: str, *, force_refresh: bool = False) -> list[AligulacPlayer]:
        params = build_params(tag__iexact=tag.split("#")[0].strip())
        data = self.transport.get_json("/player/", params, policy=_DAY, force_refresh=force_refresh)
        return self._parse(list[AligulacPlayer], _objects(data), "/player/")

    def player_ratings(
        self, aligulac_id: int, limit: int = 20, *, force_refresh: bool = False
    ) -> list[AligulacRatingPoint]:
        params = build_params(player=int(aligulac_id), limit=limit, order_by="-period")
        data = self.transport.get_json("/rating/", params, policy=_DAY, force_refresh=force_refresh)
        return self._parse(list[AligulacRatingPoint], _objects(data), "/rating/")

    def player_matches(
        self, aligulac_id: int, limit: int = 20, *, force_refresh: bool = False
    ) -> list[AligulacMatch]:
        """Matches where the player is on either side, newest first."""
        merged: dict[int, AligulacMatch] = {}
        for side in ("pla", "plb"):
            params = build_params(**{side: int(aligulac_id)}, limit=limit, order_by="-date")
            data = self.transport.get_json(
                "/match/", params, policy=_DAY, force_refresh=force_refresh
            )
            for m in self._parse(list[AligulacMatch], _objects(data), "/match/"):
                merged[m.id] = m
        ordered = sorted(merged.values(), key=lambda m: (m.date, m.id), reverse=True)
        return ordered[:limit]

    def predict(
        self, id_a: int, id_b: int, bo: int = 3, *, force_refresh: bool = False
    ) -> AligulacPrediction:
        path = f"/predictmatch/{int(id_a)},{int(id_b)}/"
        data = self.transport.get_json(
            path, build_params(bo=bo), policy=_DAY, force_refresh=force_refresh
        )
        return self._parse(AligulacPrediction, data or {}, path)

    def validate_key(self) -> bool:
        """True if the configured key is accepted. Never cached."""
        try:
            self.transport.get_json("/player/", build_params(limit=1))
        except (AuthError, NotFound):
            return False
        return True
