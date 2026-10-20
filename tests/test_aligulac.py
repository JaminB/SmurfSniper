from __future__ import annotations

import httpx
import pytest
import respx
from loguru import logger

from smurfsniper.api import transport as tr
from smurfsniper.api.aligulac import BASE_URL, AligulacClient
from smurfsniper.api.aligulac.client import default_params
from smurfsniper.api.cache import MemoryCache, TieredCache
from smurfsniper.api.errors import Unavailable
from smurfsniper.api.transport import HttpTransport, RetryPolicy

KEY = "TESTKEY123"


@pytest.fixture
def cache() -> TieredCache:
    return TieredCache(MemoryCache(), None)


@pytest.fixture
def client(cache) -> AligulacClient:
    t = HttpTransport(
        service="aligulac",
        base_url=BASE_URL,
        cache=cache,
        limiter=None,
        default_params=default_params(KEY),
        retry=RetryPolicy(attempts=2),
    )
    yield AligulacClient(t)
    t.close()


@respx.mock
def test_players_by_tag_unwraps_and_sends_key(client, cache, fixture_json):
    route = respx.get(f"{BASE_URL}/player/").mock(
        return_value=httpx.Response(200, json=fixture_json("aligulac_player"))
    )
    players = client.players_by_tag("Serral#123")
    p = players[0]
    assert p.id == 485 and p.team == "BASILISK" and p.current_rating.position == 1
    assert p.profile_url.endswith("/players/485/")
    params = route.calls.last.request.url.params
    assert params["tag__iexact"] == "Serral"
    assert params["apikey"] == KEY and params["format"] == "json"
    assert all(KEY not in k for k in cache.memory._data)


@respx.mock
def test_player_by_id(client, fixture_json):
    obj = fixture_json("aligulac_player")["objects"][0]
    respx.get(f"{BASE_URL}/player/485/").mock(return_value=httpx.Response(200, json=obj))
    assert client.player(485).tag == "Serral"


@respx.mock
def test_player_matches_merges_both_sides(client):
    route = respx.get(f"{BASE_URL}/match/").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "objects": [
                        {
                            "id": 1,
                            "date": "2026-01-01",
                            "pla": "/api/v1/player/485/",
                            "plb": {"id": 9},
                        },
                        {"id": 3, "date": "2026-03-01", "pla": {"id": 485}, "plb": {"id": 7}},
                    ]
                },
            ),
            httpx.Response(
                200,
                json={
                    "objects": [
                        {"id": 2, "date": "2026-02-01", "pla": {"id": 5}, "plb": {"id": 485}}
                    ]
                },
            ),
        ]
    )
    matches = client.player_matches(485, limit=10)
    assert [m.id for m in matches] == [3, 2, 1]
    assert matches[2].pla_id == 485 and matches[2].plb_id == 9
    sides = [set(c.request.url.params) & {"pla", "plb"} for c in route.calls]
    assert sides == [{"pla"}, {"plb"}]


@respx.mock
def test_ratings_and_predict(client):
    respx.get(f"{BASE_URL}/rating/").mock(
        return_value=httpx.Response(
            200, json={"objects": [{"id": 1, "period": "/api/v1/period/300/", "rating": 2.1}]}
        )
    )
    respx.get(f"{BASE_URL}/predictmatch/485,49/").mock(
        return_value=httpx.Response(200, json={"proba": 0.6, "probb": 0.4, "bo": 3})
    )
    assert client.player_ratings(485)[0].period == 300
    assert client.predict(485, 49).proba == 0.6


@respx.mock
def test_validate_key(client, monkeypatch):
    monkeypatch.setattr(tr, "_sleep", lambda s: None)
    route = respx.get(f"{BASE_URL}/player/").mock(
        side_effect=[httpx.Response(401), httpx.Response(200, json={"objects": []})]
    )
    assert client.validate_key() is False
    assert client.validate_key() is True  # never cached
    assert route.call_count == 2


@respx.mock
def test_key_never_logged(client, monkeypatch):
    monkeypatch.setattr(tr, "_sleep", lambda s: None)
    messages: list[str] = []
    sink = logger.add(lambda m: messages.append(str(m)), level="DEBUG")
    try:
        respx.get(f"{BASE_URL}/player/").mock(return_value=httpx.Response(503))
        with pytest.raises(Unavailable):
            client.players_by_tag("x")
    finally:
        logger.remove(sink)
    assert messages and not any(KEY in m for m in messages)


def test_registry_only_builds_aligulac_with_key():
    from smurfsniper.api.registry import build_clients
    from smurfsniper.models.config import Config, IntegrationsConfig

    cfg = Config()
    clients = build_clients(cfg, disk_cache=False)
    assert clients.aligulac is None and clients.liquipedia is not None
    clients.close()
    cfg.integrations = IntegrationsConfig(aligulac_api_key="k")
    clients = build_clients(cfg, disk_cache=False)
    assert clients.aligulac is not None
    clients.close()
