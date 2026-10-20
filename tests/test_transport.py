from __future__ import annotations

import httpx
import pytest
import respx

from smurfsniper.api import transport as tr
from smurfsniper.api.cache import CachePolicy, MemoryCache, TieredCache
from smurfsniper.api.errors import AuthError, BadResponse, NotFound, Unavailable
from smurfsniper.api.transport import HttpTransport, RetryPolicy, TokenBucket

BASE = "https://example.test/api"


@pytest.fixture
def sleeps(monkeypatch) -> list[float]:
    calls: list[float] = []
    monkeypatch.setattr(tr, "_sleep", lambda s: calls.append(s))
    return calls


def make(cache: bool = True, **kw) -> HttpTransport:
    return HttpTransport(
        service="test",
        base_url=BASE,
        cache=TieredCache(MemoryCache(), None) if cache else None,
        limiter=kw.pop("limiter", None),
        **kw,
    )


@respx.mock
def test_429_retry_after_then_success(sleeps):
    route = respx.get(f"{BASE}/x").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "1"}),
            httpx.Response(200, json=[1]),
        ]
    )
    t = make()
    assert t.get_json("/x") == [1]
    assert route.call_count == 2
    assert 1.0 in sleeps


@respx.mock
def test_503_three_times_unavailable(sleeps):
    route = respx.get(f"{BASE}/x").mock(return_value=httpx.Response(503))
    with pytest.raises(Unavailable):
        make().get_json("/x")
    assert route.call_count == 3
    assert len(sleeps) == 2


@respx.mock
def test_connect_error_unavailable(sleeps):
    respx.get(f"{BASE}/x").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unavailable):
        make(retry=RetryPolicy(attempts=1)).get_json("/x")
    assert sleeps == []


@respx.mock
def test_401_auth_error_not_cached(sleeps):
    route = respx.get(f"{BASE}/x").mock(return_value=httpx.Response(401))
    t = make()
    pol = CachePolicy(300)
    for _ in range(2):
        with pytest.raises(AuthError):
            t.get_json("/x", policy=pol)
    assert route.call_count == 2


@respx.mock
def test_404_cached_as_not_found(sleeps):
    route = respx.get(f"{BASE}/x").mock(return_value=httpx.Response(404))
    t = make()
    pol = CachePolicy(300)
    for _ in range(2):
        with pytest.raises(NotFound):
            t.get_json("/x", policy=pol)
    assert route.call_count == 1


@respx.mock
def test_bad_json(sleeps):
    respx.get(f"{BASE}/x").mock(return_value=httpx.Response(200, content=b"{nope"))
    with pytest.raises(BadResponse):
        make().get_json("/x")


@respx.mock
def test_empty_list_cached_with_negative_ttl(sleeps):
    clock = [1000.0]
    mem = MemoryCache(time_fn=lambda: clock[0])
    t = HttpTransport(
        service="test",
        base_url=BASE,
        cache=TieredCache(mem, None),
        limiter=None,
        time_fn=lambda: clock[0],
    )
    route = respx.get(f"{BASE}/x").mock(return_value=httpx.Response(200, json=[]))
    pol = CachePolicy(ttl=3600, negative_ttl=60)
    assert t.get_json("/x", policy=pol) == []
    assert t.get_json("/x", policy=pol) == []
    assert route.call_count == 1
    clock[0] += 61
    t.get_json("/x", policy=pol)
    assert route.call_count == 2
    # {"result": []} also counts as empty
    route2 = respx.get(f"{BASE}/y").mock(
        return_value=httpx.Response(200, json={"result": [], "navigation": {}})
    )
    t.get_json("/y", policy=pol)
    clock[0] += 61
    t.get_json("/y", policy=pol)
    assert route2.call_count == 2


@respx.mock
def test_hit_and_force_refresh(sleeps):
    route = respx.get(f"{BASE}/x").mock(return_value=httpx.Response(200, json=[1]))
    t = make()
    pol = CachePolicy(300)
    t.get_json("/x", [("a", "1")], policy=pol)
    t.get_json("/x", [("a", "1")], policy=pol)
    assert route.call_count == 1
    t.get_json("/x", [("a", "1")], policy=pol, force_refresh=True)
    assert route.call_count == 2


@respx.mock
def test_no_policy_never_caches(sleeps):
    route = respx.get(f"{BASE}/x").mock(return_value=httpx.Response(200, json=[1]))
    t = make()
    t.get_json("/x")
    t.get_json("/x")
    assert route.call_count == 2


@respx.mock
def test_apikey_not_in_cache_key_but_sent(sleeps):
    route = respx.get(f"{BASE}/x").mock(return_value=httpx.Response(200, json=[1]))
    cache = TieredCache(MemoryCache(), None)
    t = HttpTransport(
        service="test",
        base_url=BASE,
        cache=cache,
        limiter=None,
        default_params={"apikey": "SECRET123"},
    )
    t.get_json("/x", [("a", "1")], policy=CachePolicy(300))
    assert route.calls.last.request.url.params["apikey"] == "SECRET123"
    keys = list(cache.memory._data)
    assert keys and all("SECRET123" not in k for k in keys)


@respx.mock
def test_user_agent_header(sleeps):
    route = respx.get(f"{BASE}/x").mock(return_value=httpx.Response(200, json=[]))
    make().get_json("/x")
    assert route.calls.last.request.headers["User-Agent"].startswith("smurfsniper/")


@respx.mock
def test_ratelimit_headers_update_bucket(sleeps):
    bucket = TokenBucket(4, 10)
    respx.get(f"{BASE}/x").mock(
        return_value=httpx.Response(
            200,
            json=[1],
            headers={
                "RateLimit-Limit": "2",
                "RateLimit-Burst": "6",
                "RateLimit-Remaining": "0",
                "RateLimit-Reset": "3",
            },
        )
    )
    make(limiter=bucket).get_json("/x")
    assert bucket.rate == 2
    assert bucket.burst == 4
    assert bucket.try_acquire() > 2.0


def test_token_bucket_refill_and_penalize():
    now = [0.0]
    b = TokenBucket(2, 2, time_fn=lambda: now[0])
    assert b.try_acquire() == 0
    assert b.try_acquire() == 0
    assert b.try_acquire() == pytest.approx(0.5)
    now[0] += 0.5
    assert b.try_acquire() == 0
    b.penalize(5)
    assert b.try_acquire() == pytest.approx(5)
    now[0] += 5.6
    assert b.try_acquire() == 0


def test_retry_after_http_date():
    from datetime import UTC, datetime, timedelta
    from email.utils import format_datetime

    when = datetime.now(UTC) + timedelta(seconds=30)
    got = tr._retry_after(httpx.Headers({"Retry-After": format_datetime(when, usegmt=True)}))
    assert got is not None and 25 < got <= 31
    assert tr._retry_after(httpx.Headers({"RateLimit-Reset": "2"})) == 2.0
    assert tr._retry_after(httpx.Headers({})) is None
