from __future__ import annotations

import threading
import time

from smurfsniper.api.cache import (
    CacheEntry,
    CachePolicy,
    DiskCache,
    MemoryCache,
    SingleFlight,
    TieredCache,
    cache_key,
)


class Clock:
    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t


def entry(body: bytes = b"[1]", *, at: float = 1000.0, ttl: float = 60.0) -> CacheEntry:
    return CacheEntry(body=body, status=200, stored_at=at, expires_at=at + ttl)


def test_cache_key_sorted_and_hashed():
    a = cache_key("s", "/p", [("b", "2"), ("a", "1")])
    b = cache_key("s", "/p", [("a", "1"), ("b", "2")])
    assert a == b == "s|/p|a=1&b=2"
    long = cache_key("s", "/p", [("x", "y" * 600)])
    assert "sha1:" in long and len(long) < 100


def test_policy_none():
    assert not CachePolicy.NONE.enabled
    assert CachePolicy(300, 600).effective_negative_ttl == 300


def test_memory_lru_eviction():
    clock = Clock()
    m = MemoryCache(max_entries=2, time_fn=clock)
    m.set("a", entry())
    m.set("b", entry())
    assert m.get("a") is not None  # a becomes most recent
    m.set("c", entry())
    assert m.get("b") is None
    assert m.get("a") is not None and m.get("c") is not None


def test_memory_ttl_expiry():
    clock = Clock()
    m = MemoryCache(time_fn=clock)
    m.set("a", entry(ttl=10))
    clock.t += 9
    assert m.get("a") is not None
    clock.t += 2
    assert m.get("a") is None
    assert len(m) == 0


def test_disk_round_trip_and_expiry(tmp_path):
    clock = Clock()
    d = DiskCache(tmp_path / "c.sqlite3", time_fn=clock)
    d.set("k", entry(b'{"x": 1}', ttl=5))
    got = d.get("k")
    assert got is not None and got.body == b'{"x": 1}' and got.status == 200
    clock.t += 6
    assert d.get("k") is None
    assert d.stats() == (1, len(b'{"x": 1}'))
    d.clear()
    assert d.stats() == (0, 0)
    d.close()


def test_disk_prune_by_age_and_size(tmp_path):
    clock = Clock()
    d = DiskCache(tmp_path / "c.sqlite3", max_bytes=25, time_fn=clock)
    d.set("old", entry(b"x" * 10, at=0, ttl=1))  # expired long ago
    d.set("a", entry(b"a" * 10, at=900, ttl=1e9))
    d.set("b", entry(b"b" * 10, at=950, ttl=1e9))
    d.set("c", entry(b"c" * 10, at=990, ttl=1e9))
    clock.t = 8 * 24 * 3600.0 + 1  # "old" expired > 7 days ago
    d.prune()
    # old removed by age; a removed (oldest) to get under 25 bytes
    assert d.stats() == (2, 20)
    d.close()


def test_tiered_promotes_to_memory(tmp_path):
    clock = Clock()
    disk = DiskCache(tmp_path / "c.sqlite3", time_fn=clock)
    mem = MemoryCache(time_fn=clock)
    t = TieredCache(mem, disk)
    pol = CachePolicy(60)
    t.set("k", entry(), pol)
    mem.clear()
    assert t.get("k", pol) is not None
    assert mem.get("k") is not None
    # memory-only policy never touches disk
    t.set("m", entry(), CachePolicy(60, disk=False))
    assert disk.get("m") is None
    disk.close()


def test_single_flight_coalesces():
    sf = SingleFlight()
    calls = 0
    gate = threading.Event()
    lock = threading.Lock()

    def fn():
        nonlocal calls
        with lock:
            calls += 1
        gate.wait(2)
        return 42

    results: list[int] = []
    threads = [threading.Thread(target=lambda: results.append(sf.do("k", fn))) for _ in range(8)]
    for th in threads:
        th.start()
    time.sleep(0.2)
    gate.set()
    for th in threads:
        th.join()
    assert calls == 1
    assert results == [42] * 8


def test_single_flight_propagates_exception():
    sf = SingleFlight()

    def boom():
        raise ValueError("x")

    try:
        sf.do("k", boom)
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError
    assert sf.do("k", lambda: 1) == 1
