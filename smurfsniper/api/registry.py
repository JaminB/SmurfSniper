"""Builds the set of API clients the app holds for its lifetime."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from smurfsniper.api import aligulac, liquipedia, sc2pulse
from smurfsniper.api.aligulac import AligulacClient
from smurfsniper.api.cache import DiskCache, MemoryCache, TieredCache
from smurfsniper.api.liquipedia import LiquipediaClient
from smurfsniper.api.sc2client import DEFAULT_URL, LocalSc2Client
from smurfsniper.api.sc2pulse import SC2PulseClient
from smurfsniper.api.transport import HttpTransport
from smurfsniper.logger import logger

HTTP_CACHE_FILE = "http_cache.sqlite3"


@dataclass
class Clients:
    sc2pulse: SC2PulseClient
    aligulac: AligulacClient | None
    liquipedia: LiquipediaClient | None
    sc2: LocalSc2Client
    cache: TieredCache

    def close(self, *, close_cache: bool = True) -> None:
        """Close every transport. ``close_cache=False`` keeps the cache for a rebuild."""
        for c in (self.sc2pulse, self.aligulac, self.liquipedia, self.sc2):
            if c is not None:
                try:
                    c.transport.close()
                except Exception as e:  # shutdown must not raise
                    logger.debug(f"closing {type(c).__name__}: {e}")
        if close_cache:
            self.cache.close()


def make_cache(cache_dir: Path | None, *, disk_cache: bool = True) -> TieredCache:
    disk = None
    if disk_cache and cache_dir is not None:
        try:
            disk = DiskCache(Path(cache_dir) / HTTP_CACHE_FILE)
        except Exception as e:  # unwritable dir, locked file, ...
            logger.warning(f"Disk HTTP cache disabled: {e}")
    return TieredCache(MemoryCache(max_entries=2048), disk)


def _aligulac_key(config: Any) -> str:
    integrations = getattr(config, "integrations", None)
    al = getattr(integrations, "aligulac", None) if integrations else None
    key = getattr(al, "api_key", "") if al else ""
    if hasattr(key, "get_secret_value"):
        key = key.get_secret_value()
    return (key or "").strip()


def build_clients(
    config: Any,
    *,
    cache_dir: Path | None = None,
    disk_cache: bool = True,
    sc2_url: str = DEFAULT_URL,
    cache: TieredCache | None = None,
    liquipedia_contact: str | None = None,
) -> Clients:
    """Create every client. Pass ``cache`` to reuse a cache across rebuilds.

    ``cache_dir`` defaults to ``paths.cache_dir()`` when ``disk_cache`` is on.
    """
    if cache is None:
        if disk_cache and cache_dir is None:
            from smurfsniper import paths

            cache_dir = paths.cache_dir()
        cache = make_cache(cache_dir, disk_cache=disk_cache)

    pulse = SC2PulseClient(
        HttpTransport(
            service="sc2pulse",
            base_url=sc2pulse.BASE_URL,
            cache=cache,
            limiter=sc2pulse.make_limiter(),
        )
    )

    key = _aligulac_key(config)
    ali = None
    if key:
        ali = AligulacClient(
            HttpTransport(
                service="aligulac",
                base_url=aligulac.BASE_URL,
                cache=cache,
                limiter=aligulac.make_limiter(),
                default_params=aligulac.client.default_params(key),
            )
        )

    lp = LiquipediaClient(
        HttpTransport(
            service="liquipedia",
            base_url=liquipedia.BASE_URL,
            cache=cache,
            limiter=liquipedia.make_limiter(),
            headers=liquipedia.headers(liquipedia_contact),
        )
    )

    return Clients(
        sc2pulse=pulse,
        aligulac=ali,
        liquipedia=lp,
        sc2=LocalSc2Client(sc2_url),
        cache=cache,
    )
