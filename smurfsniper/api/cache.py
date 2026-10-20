"""Two-tier HTTP response cache (memory LRU + SQLite) and in-flight coalescing."""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, TypeVar
from urllib.parse import urlencode

T = TypeVar("T")

_PRUNE_AGE = 7 * 24 * 3600.0


@dataclass(frozen=True)
class CachePolicy:
    ttl: float  # seconds for a non-empty success
    negative_ttl: float = 600.0  # 404 / empty list / {} / {"result": []}; min(ttl, negative_ttl)
    disk: bool = True  # persist to the SQLite tier
    NONE: ClassVar[CachePolicy]

    @property
    def enabled(self) -> bool:
        return self.ttl > 0

    @property
    def effective_negative_ttl(self) -> float:
        return min(self.ttl, self.negative_ttl)


CachePolicy.NONE = CachePolicy(0, 0, False)


@dataclass
class CacheEntry:
    body: bytes  # raw JSON bytes (UTF-8)
    status: int
    stored_at: float
    expires_at: float


def cache_key(service: str, path: str, params: list[tuple[str, str]]) -> str:
    key = f"{service}|{path}|" + urlencode(sorted(params))
    if len(key) > 512:
        return f"{service}|{path}|sha1:" + hashlib.sha1(key.encode("utf-8")).hexdigest()
    return key


class MemoryCache:
    """Thread-safe LRU with per-entry expiry."""

    def __init__(self, max_entries: int = 1024, *, time_fn: Callable[[], float] = time.time):
        self._max = max_entries
        self._time = time_fn
        self._data: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> CacheEntry | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            if entry.expires_at <= self._time():
                del self._data[key]
                return None
            self._data.move_to_end(key)
            return entry

    def set(self, key: str, entry: CacheEntry) -> None:
        with self._lock:
            self._data[key] = entry
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


class DiskCache:
    """SQLite tier. One connection shared across threads, serialised by a lock."""

    def __init__(
        self,
        path: Path,
        max_bytes: int = 64 * 1024 * 1024,
        *,
        time_fn: Callable[[], float] = time.time,
    ):
        self.path = Path(path)
        self._max_bytes = max_bytes
        self._time = time_fn
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False, timeout=10)
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS http_cache ("
                "key TEXT PRIMARY KEY, body BLOB, status INTEGER, "
                "stored_at REAL, expires_at REAL, size INTEGER)"
            )
            self._conn.commit()

    def get(self, key: str) -> CacheEntry | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT body, status, stored_at, expires_at FROM http_cache WHERE key = ?",
                (key,),
            ).fetchone()
        if row is None or row[3] <= self._time():
            return None
        return CacheEntry(body=bytes(row[0]), status=row[1], stored_at=row[2], expires_at=row[3])

    def set(self, key: str, entry: CacheEntry) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO http_cache VALUES (?, ?, ?, ?, ?, ?)",
                (
                    key,
                    entry.body,
                    entry.status,
                    entry.stored_at,
                    entry.expires_at,
                    len(entry.body),
                ),
            )
            self._conn.commit()

    def prune(self) -> None:
        """Drop entries expired for over 7 days, then the oldest until under ``max_bytes``."""
        with self._lock:
            self._conn.execute(
                "DELETE FROM http_cache WHERE expires_at < ?", (self._time() - _PRUNE_AGE,)
            )
            total = self._conn.execute("SELECT COALESCE(SUM(size), 0) FROM http_cache").fetchone()[
                0
            ]
            if total > self._max_bytes:
                rows = self._conn.execute(
                    "SELECT key, size FROM http_cache ORDER BY stored_at ASC"
                ).fetchall()
                doomed = []
                for key, size in rows:
                    if total <= self._max_bytes:
                        break
                    doomed.append((key,))
                    total -= size
                self._conn.executemany("DELETE FROM http_cache WHERE key = ?", doomed)
            self._conn.commit()

    def clear(self) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM http_cache")
            self._conn.commit()

    def stats(self) -> tuple[int, int]:
        with self._lock:
            n, size = self._conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(size), 0) FROM http_cache"
            ).fetchone()
        return int(n), int(size)

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class TieredCache:
    def __init__(self, memory: MemoryCache, disk: DiskCache | None):
        self.memory = memory
        self.disk = disk

    def get(self, key: str, policy: CachePolicy) -> CacheEntry | None:
        entry = self.memory.get(key)
        if entry is not None:
            return entry
        if policy.disk and self.disk is not None:
            entry = self.disk.get(key)
            if entry is not None:
                self.memory.set(key, entry)
        return entry

    def set(self, key: str, entry: CacheEntry, policy: CachePolicy) -> None:
        self.memory.set(key, entry)
        if policy.disk and self.disk is not None:
            self.disk.set(key, entry)

    def clear(self) -> None:
        self.memory.clear()
        if self.disk is not None:
            self.disk.clear()

    def close(self) -> None:
        if self.disk is not None:
            self.disk.close()


class SingleFlight:
    """Coalesce concurrent calls with the same key into one execution."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._inflight: dict[str, Future] = {}

    def do(self, key: str, fn: Callable[[], T]) -> T:
        return self.do_ex(key, fn)[0]

    def do_ex(self, key: str, fn: Callable[[], T]) -> tuple[T, bool]:
        """Like ``do`` but also returns whether this caller was coalesced onto another."""
        with self._lock:
            fut = self._inflight.get(key)
            leader = fut is None
            if leader:
                fut = Future()
                self._inflight[key] = fut
        if not leader:
            return fut.result(), True
        try:
            result = fn()
        except BaseException as e:
            fut.set_exception(e)
            raise
        else:
            fut.set_result(result)
            return result, False
        finally:
            with self._lock:
                self._inflight.pop(key, None)
