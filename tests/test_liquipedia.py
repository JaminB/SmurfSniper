from __future__ import annotations

import httpx
import pytest
import respx

from smurfsniper.api.cache import MemoryCache, TieredCache
from smurfsniper.api.liquipedia import BASE_URL, LiquipediaClient, headers
from smurfsniper.api.liquipedia.client import user_agent
from smurfsniper.api.transport import HttpTransport

API = f"{BASE_URL}/api.php"


@pytest.fixture
def client() -> LiquipediaClient:
    t = HttpTransport(
        service="liquipedia",
        base_url=BASE_URL,
        cache=TieredCache(MemoryCache(), None),
        limiter=None,
        headers=headers("me@example.invalid"),
    )
    yield LiquipediaClient(t)
    t.close()


def test_user_agent():
    assert user_agent().endswith("(+https://github.com/JaminB/SmurfSniper)")
    assert user_agent("contact").endswith("SmurfSniper; contact)")
    assert headers()["Accept-Encoding"] == "gzip"


@respx.mock
def test_opensearch(client, fixture_json):
    route = respx.get(API).mock(
        return_value=httpx.Response(200, json=fixture_json("liquipedia_opensearch"))
    )
    hits = client.opensearch("Serral")
    assert hits[0].title == "Serral" and hits[0].url.endswith("/Serral")
    assert hits[0].description is None
    req = route.calls.last.request
    assert req.url.params["action"] == "opensearch"
    assert req.headers["User-Agent"].startswith("smurfsniper/")
    assert "me@example.invalid" in req.headers["User-Agent"]


@respx.mock
def test_page_summaries_and_redirects(client, fixture_json):
    data = fixture_json("liquipedia_query_extract")
    data["query"]["redirects"] = [{"from": "serral", "to": "Serral"}]
    route = respx.get(API).mock(return_value=httpx.Response(200, json=data))
    out = client.page_summaries(["serral", "Nobody"])
    assert set(out) == {"serral"}
    s = out["serral"]
    assert s.pageid == 32557 and "Finnish" in s.extract and s.full_url.endswith("/Serral")
    p = route.calls.last.request.url.params
    assert p["prop"] == "extracts|pageprops|info" and p["redirects"] == "1"
    assert p["titles"] == "serral|Nobody"
    assert "parse" not in p.get("action", "")


@respx.mock
def test_page_summaries_batches_50(client):
    route = respx.get(API).mock(
        return_value=httpx.Response(200, json={"query": {"pages": {"-1": {"missing": ""}}}})
    )
    client.page_summaries([f"T{i}" for i in range(120)])
    assert route.call_count == 3
    sizes = [len(c.request.url.params["titles"].split("|")) for c in route.calls]
    assert sizes == [50, 50, 20]


@respx.mock
def test_search(client):
    respx.get(API).mock(
        return_value=httpx.Response(
            200,
            json={
                "query": {"search": [{"title": "Serral", "pageid": 1, "snippet": "<b>Ser</b>ral"}]}
            },
        )
    )
    hits = client.search("ser")
    assert hits[0].snippet == "Serral"
