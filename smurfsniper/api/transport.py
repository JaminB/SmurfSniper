"""Shared HTTP transport: retries, backoff, header-aware rate limiting and caching.

This is the only module (together with ``api/sc2client``) that imports httpx.
"""

from __future__ import annotations

import json
import random
import sys
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from smurfsniper._version import __version__
from smurfsniper.api.cache import CacheEntry, CachePolicy, SingleFlight, TieredCache, cache_key
from smurfsniper.api.errors import (
    ApiError,
    AuthError,
    BadResponse,
    NotFound,
    RateLimited,
    Unavailable,
)
from smurfsniper.logger import logger

USER_AGENT = f"smurfsniper/{__version__} (+https://github.com/JaminB/SmurfSniper)"


def _sleep(seconds: float) -> None:
    """Indirection so tests can skip real waits."""
    if seconds > 0:
        time.sleep(seconds)


def _warn_gui_thread(path: str) -> None:
    logger.warning(f"network on GUI thread: {path}")


# Called with the request path when network I/O happens on the Qt GUI thread.
# Tests replace it with a function that raises.
gui_thread_hook: Callable[[str], None] = _warn_gui_thread
_gui_warned: set[str] = set()


def _check_gui_thread(path: str) -> None:
    if threading.current_thread() is not threading.main_thread():
        return
    qtcore = sys.modules.get("PySide6.QtCore")
    if qtcore is None or qtcore.QCoreApplication.instance() is None:
        return
    if gui_thread_hook is _warn_gui_thread:
        if path in _gui_warned:
            return
        _gui_warned.add(path)
    gui_thread_hook(path)


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3  # total tries
    backoff_base: float = 0.5  # 0.5, 1, 2 (+ jitter 0..0.25)
    backoff_max: float = 8.0
    retry_statuses: frozenset[int] = field(
        default_factory=lambda: frozenset({429, 500, 502, 503, 504})
    )

    def backoff(self, attempt: int) -> float:
        return min(self.backoff_max, self.backoff_base * (2**attempt)) + random.uniform(0, 0.25)


class TokenBucket:
    """Thread-safe token bucket. ``acquire`` blocks the calling worker thread."""

    def __init__(
        self,
        rate_per_s: float,
        burst: int,
        *,
        time_fn: Callable[[], float] = time.monotonic,
    ):
        self.rate = float(rate_per_s)
        self.burst = max(1, int(burst))
        self._time = time_fn
        self._tokens = float(self.burst)
        self._updated = time_fn()
        self._blocked_until = 0.0
        self._lock = threading.Lock()

    @property
    def tokens(self) -> float:
        with self._lock:
            self._refill(self._time())
            return self._tokens

    def _refill(self, now: float) -> None:
        elapsed = max(0.0, now - self._updated)
        self._tokens = min(float(self.burst), self._tokens + elapsed * self.rate)
        self._updated = now

    def try_acquire(self) -> float:
        """Take a token if possible. Returns 0 on success, else seconds to wait."""
        with self._lock:
            now = self._time()
            if now < self._blocked_until:
                return self._blocked_until - now
            self._refill(now)
            if self._tokens >= 1:
                self._tokens -= 1
                return 0.0
            return (1 - self._tokens) / self.rate

    def acquire(self) -> None:
        while True:
            wait = self.try_acquire()
            if wait <= 0:
                return
            _sleep(wait)

    def update_from_headers(self, headers: Mapping[str, str]) -> None:
        """Adapt to ``RateLimit-*`` response headers."""

        def num(name: str) -> float | None:
            raw = headers.get(name)
            if raw is None:
                return None
            try:
                return float(str(raw).split(",")[0].strip())
            except ValueError:
                return None

        limit = num("RateLimit-Limit")
        burst = num("RateLimit-Burst")
        remaining = num("RateLimit-Remaining")
        reset = num("RateLimit-Reset")
        with self._lock:
            now = self._time()
            self._refill(now)
            if limit and limit > 0:
                self.rate = limit
            if burst and burst > 0:
                self.burst = max(1, int(burst) - 2)
                self._tokens = min(self._tokens, float(self.burst))
            if remaining is not None and remaining <= 0:
                self._tokens = 0.0
                self._blocked_until = max(self._blocked_until, now + (reset or 1.0))

    def penalize(self, seconds: float) -> None:
        """After a 429: hand out no tokens until ``now + seconds``."""
        with self._lock:
            now = self._time()
            self._tokens = 0.0
            self._updated = now
            self._blocked_until = max(self._blocked_until, now + max(0.0, seconds))


def _retry_after(headers: Mapping[str, str]) -> float | None:
    raw = headers.get("Retry-After")
    if raw:
        try:
            return max(0.0, float(raw))
        except ValueError:
            try:
                when = parsedate_to_datetime(raw)
                if when.tzinfo is None:
                    when = when.replace(tzinfo=UTC)
                return max(0.0, (when - datetime.now(UTC)).total_seconds())
            except (TypeError, ValueError):
                pass
    reset = headers.get("RateLimit-Reset")
    if reset:
        try:
            return max(0.0, float(reset))
        except ValueError:
            return None
    return None


def _is_empty(data: Any) -> bool:
    if data in ([], {}, None):
        return True
    return (
        isinstance(data, dict)
        and set(data) <= {"result", "navigation"}
        and data.get("result") in ([], None)
    )


class HttpTransport:
    def __init__(
        self,
        *,
        service: str,
        base_url: str,
        cache: TieredCache | None,
        limiter: TokenBucket | None,
        retry: RetryPolicy | None = None,
        timeout: httpx.Timeout | None = None,
        headers: Mapping[str, str] | None = None,
        default_params: Mapping[str, str] | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self.service = service
        self.base_url = base_url.rstrip("/")
        self.cache = cache
        self.limiter = limiter
        self.retry = retry or RetryPolicy()
        self._time = time_fn
        self._default_params = [(k, v) for k, v in (default_params or {}).items()]
        self._secret_values = {v for v in (default_params or {}).values() if v}
        self._flight = SingleFlight()
        self._client = httpx.Client(
            base_url=self.base_url,
            http2=False,
            follow_redirects=True,
            timeout=timeout or httpx.Timeout(10.0, connect=5.0),
            headers={"User-Agent": USER_AGENT, **(headers or {})},
        )

    # ----------------------------------------------------------------- public
    def get_json(
        self,
        path: str,
        params: list[tuple[str, str]] | None = None,
        *,
        policy: CachePolicy = CachePolicy.NONE,
        force_refresh: bool = False,
    ) -> Any:
        params = list(params or [])
        key = cache_key(self.service, path, params)
        use_cache = self.cache is not None and policy.enabled
        if use_cache and not force_refresh:
            entry = self.cache.get(key, policy)
            if entry is not None:
                logger.debug(f"{self.service} {path} {entry.status} 0ms cache=hit")
                return self._decode(entry, path)

        flight_key = key + ("|refresh" if force_refresh else "")
        result, coalesced = self._flight.do_ex(
            flight_key, lambda: self._fetch(path, params, key, policy if use_cache else None)
        )
        if coalesced:
            logger.debug(f"{self.service} {path} cache=coalesced")
        return result

    def close(self) -> None:
        self._client.close()

    # ---------------------------------------------------------------- private
    def _decode(self, entry: CacheEntry, path: str) -> Any:
        if entry.status == 404:
            raise NotFound(self.service, f"{path} not found (cached)", status=404, url=path)
        return json.loads(entry.body)

    def _store(self, key: str, policy: CachePolicy, body: bytes, status: int, ttl: float) -> None:
        if self.cache is None or ttl <= 0:
            return
        now = self._time()
        self.cache.set(
            key, CacheEntry(body=body, status=status, stored_at=now, expires_at=now + ttl), policy
        )

    def _redact(self, text: str) -> str:
        for secret in self._secret_values:
            text = text.replace(secret, "****")
        return text

    def _fetch(
        self,
        path: str,
        params: list[tuple[str, str]],
        key: str,
        policy: CachePolicy | None,
    ) -> Any:
        _check_gui_thread(path)
        attempts = max(1, self.retry.attempts)
        last: ApiError | None = None
        for attempt in range(attempts):
            if self.limiter is not None:
                self.limiter.acquire()
            started = time.perf_counter()
            try:
                resp = self._client.get(path, params=params + self._default_params)
            except httpx.TransportError as e:
                last = Unavailable(self.service, f"{path}: {type(e).__name__}", url=path)
                delay = self.retry.backoff(attempt)
            else:
                ms = (time.perf_counter() - started) * 1000
                status = resp.status_code
                logger.debug(f"{self.service} {path} {status} {ms:.0f}ms cache=miss")
                if self.limiter is not None:
                    self.limiter.update_from_headers(resp.headers)

                if status in self.retry.retry_statuses:
                    if status == 429:
                        wait = _retry_after(resp.headers)
                        delay = wait if wait is not None else self.retry.backoff(attempt)
                        if self.limiter is not None:
                            self.limiter.penalize(delay)
                        last = RateLimited(
                            self.service,
                            f"{path} rate limited",
                            status=429,
                            url=path,
                            retry_after=wait,
                        )
                    else:
                        delay = self.retry.backoff(attempt)
                        last = Unavailable(
                            self.service, f"{path} HTTP {status}", status=status, url=path
                        )
                elif status == 404:
                    if policy is not None:
                        self._store(key, policy, b"null", 404, policy.effective_negative_ttl)
                    raise NotFound(self.service, f"{path} not found", status=404, url=path)
                elif status in (401, 403):
                    raise AuthError(self.service, f"{path} HTTP {status}", status=status, url=path)
                elif status >= 400:
                    raise ApiError(self.service, f"{path} HTTP {status}", status=status, url=path)
                else:
                    body = resp.content
                    try:
                        data = json.loads(body) if body else None
                    except ValueError as e:
                        raise BadResponse(self.service, f"{path}: invalid JSON", url=path) from e
                    if policy is not None:
                        ttl = policy.effective_negative_ttl if _is_empty(data) else policy.ttl
                        self._store(key, policy, body or b"null", status, ttl)
                    return data

            if attempt < attempts - 1:
                logger.warning(
                    self._redact(
                        f"{self.service} {path} failed ({last}); "
                        f"retry {attempt + 1}/{attempts - 1} in {delay:.1f}s"
                    )
                )
                _sleep(delay)
        assert last is not None
        raise last
