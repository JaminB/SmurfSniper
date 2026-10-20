from __future__ import annotations

import httpx
import pytest
import respx

from smurfsniper.api.cache import MemoryCache, TieredCache
from smurfsniper.api.sc2pulse import BASE_URL, SC2PulseClient
from smurfsniper.api.sc2pulse.ids import League, MatchType, Queue, TeamType
from smurfsniper.api.transport import HttpTransport


@pytest.fixture
def client() -> SC2PulseClient:
    t = HttpTransport(
        service="sc2pulse",
        base_url=BASE_URL,
        cache=TieredCache(MemoryCache(), None),
        limiter=None,
    )
    yield SC2PulseClient(t)
    t.close()


def params(route) -> list[tuple[str, str]]:
    return list(route.calls.last.request.url.params.multi_items())


@respx.mock
def test_search_strips_discriminator_and_caches(client, fixture_json):
    route = respx.get(f"{BASE_URL}/characters").mock(
        return_value=httpx.Response(200, json=fixture_json("characters_query"))
    )
    res = client.search_characters("Serral#769")
    assert params(route) == [("query", "Serral")]
    assert res[0].members.character.id == 236695
    client.search_characters("Serral")
    assert route.call_count == 1  # cached


@respx.mock
def test_search_skips_invalid(client):
    respx.get(f"{BASE_URL}/characters").mock(
        return_value=httpx.Response(200, json=[{"members": None}, {"bogus": 1}])
    )
    assert client.search_characters("x") == []


@respx.mock
def test_characters_chunking(client, fixture_json):
    route = respx.get(f"{BASE_URL}/characters").mock(
        return_value=httpx.Response(200, json=fixture_json("chars_by_ids"))
    )
    res = client.characters(character_ids=list(range(1200)))
    assert route.call_count == 3
    assert len(res) == 6
    sizes = [len(c.request.url.params.get_list("characterId")) for c in route.calls]
    assert sizes == [500, 500, 200]


@respx.mock
def test_account_characters(client, fixture_json):
    route = respx.get(f"{BASE_URL}/characters").mock(
        return_value=httpx.Response(200, json=fixture_json("chars_account"))
    )
    res = client.account_characters(321489851)
    assert params(route) == [("accountId", "321489851")]
    assert res[0].rating_max == 8127


@respx.mock
def test_find_character_ids_rules(client):
    route = respx.get(f"{BASE_URL}/characters").mock(
        return_value=httpx.Response(200, json=[{"id": 1}, {"id": 2}])
    )
    assert client.find_character_ids("Serral#1", region="EU", queues=[Queue.LOTV_1V1]) == [1, 2]
    p = params(route)
    assert ("field", "id") in p and ("name", "Serral") in p and ("queue", "LOTV_1V1") in p
    assert ("caseSensitive", "false") in p
    with pytest.raises(ValueError):
        client.find_character_ids("x", queues=[Queue.LOTV_1V1, Queue.LOTV_2V2], seasons=[1, 2])
    with pytest.raises(ValueError):
        client.find_character_ids("x", seasons=list(range(11)))


@respx.mock
def test_character_teams_rule_and_params(client, fixture_json):
    route = respx.get(f"{BASE_URL}/character-teams").mock(
        return_value=httpx.Response(200, json=fixture_json("character_teams_filtered"))
    )
    with pytest.raises(ValueError):
        client.character_teams([1, 2])
    with pytest.raises(ValueError):
        client.character_teams([1, 2], queues=[Queue.LOTV_1V1], seasons=[67, 68])
    teams = client.character_teams([341427506], queues=[Queue.LOTV_1V1], seasons=[68])
    assert params(route) == [
        ("characterId", "341427506"),
        ("queue", "LOTV_1V1"),
        ("season", "68"),
    ]
    assert teams[0].rating == 8127
    client.character_teams([1, 2], queues=[Queue.LOTV_2V2], seasons=[68])
    assert route.calls.last.request.url.params.get_list("characterId") == ["1", "2"]


@respx.mock
def test_character_matches_page(client, fixture_json):
    route = respx.get(f"{BASE_URL}/character-matches").mock(
        return_value=httpx.Response(200, json=fixture_json("character_matches"))
    )
    page = client.character_matches([341427506], types=[MatchType._1V1], limit=10)
    assert params(route) == [("characterId", "341427506"), ("type", "_1V1"), ("limit", "10")]
    assert len(page.result) == 2 and page.navigation.after


@respx.mock
def test_iter_character_matches_follows_cursor(client, fixture_json):
    first = fixture_json("character_matches")
    second = {"result": first["result"][:1], "navigation": {"before": None, "after": None}}
    route = respx.get(f"{BASE_URL}/character-matches").mock(
        side_effect=[httpx.Response(200, json=first), httpx.Response(200, json=second)]
    )
    got = list(client.iter_character_matches([341427506], page_size=2, max_items=100))
    assert len(got) == 3
    assert route.call_count == 2
    assert route.calls[1].request.url.params["after"] == first["navigation"]["after"]


@respx.mock
def test_iter_character_matches_max_items(client, fixture_json):
    route = respx.get(f"{BASE_URL}/character-matches").mock(
        return_value=httpx.Response(200, json=fixture_json("character_matches"))
    )
    got = list(client.iter_character_matches([1], page_size=50, max_items=1))
    assert len(got) == 1
    assert route.calls.last.request.url.params["limit"] == "1"


@respx.mock
def test_team_histories_params(client, fixture_json):
    route = respx.get(f"{BASE_URL}/team-histories").mock(
        return_value=httpx.Response(200, json=fixture_json("team_histories"))
    )
    series = client.team_histories([f"uid{i}" for i in range(12)])
    assert route.call_count == 2
    p = route.calls[0].request.url.params
    assert p["groupBy"] == "LEGACY_UID" and p["static"] == "LEGACY_ID"
    assert "RATING" in p.get_list("history") and "WINS" in p.get_list("history")
    assert len(p.get_list("teamLegacyUid")) == 10
    assert len(series) == 2


@respx.mock
def test_summaries(client, fixture_json):
    route = respx.get(f"{BASE_URL}/team-history-summaries").mock(
        return_value=httpx.Response(200, json=fixture_json("team_history_summaries"))
    )
    out = client.team_history_summaries(["201-0-2-1.315071.3"])
    assert out[0].rating_max == 7557
    assert "RATING_MAX" in route.calls.last.request.url.params.get_list("summary")


@respx.mock
def test_seasons_and_current(client, fixture_json):
    route = respx.get(f"{BASE_URL}/seasons").mock(
        return_value=httpx.Response(200, json=fixture_json("seasons"))
    )
    s = client.current_season("US")
    assert s.battlenet_id == 68 and s.region == "US"
    client.current_season("EU")
    assert route.call_count == 1


@respx.mock
def test_tier_thresholds(client, fixture_json):
    route = respx.get(f"{BASE_URL}/tier-thresholds").mock(
        return_value=httpx.Response(200, json=fixture_json("tier_thresholds"))
    )
    tt = client.tier_thresholds(Queue.LOTV_1V1, TeamType.ARRANGED, 68, regions=["EU"])
    assert params(route) == [
        ("queue", "LOTV_1V1"),
        ("teamType", "ARRANGED"),
        ("season", "68"),
        ("region", "EU"),
    ]
    assert tt.band("EU", 4000)[0] == 4


@respx.mock
def test_teams_variants(client, fixture_json):
    route = respx.get(f"{BASE_URL}/teams").mock(
        return_value=httpx.Response(200, json=fixture_json("teams_last"))
    )
    assert client.teams_last(["a"])[0].season == 67
    assert ("last", "true") in params(route)
    client.teams_by_legacy_uid([f"u{i}" for i in range(11)], season_min=60)
    assert route.call_count == 3
    assert ("seasonMin", "60") in params(route)
    client.teams_by_id([1, 2])
    assert params(route) == [("teamId", "1"), ("teamId", "2")]


@respx.mock
def test_ladder_and_recent(client, fixture_json):
    route = respx.get(f"{BASE_URL}/teams").mock(
        side_effect=[
            httpx.Response(200, json=fixture_json("teams_ladder")),
            httpx.Response(200, json=fixture_json("teams_recent")),
        ]
    )
    page = client.ladder(
        Queue.LOTV_1V1, TeamType.ARRANGED, 68, regions=["EU"], leagues=[League.GRANDMASTER]
    )
    assert page.result[0].rating == 8127
    assert ("league", "GRANDMASTER") in route.calls[0].request.url.params.multi_items()
    recent = client.recent_teams(Queue.LOTV_1V1, league=League.GRANDMASTER, rating_min=4000)
    assert recent[0].members[0].pro_nickname == "Haste"
    assert ("recent", "true") in params(route) and ("ratingMin", "4000") in params(route)


@respx.mock
def test_links_entities_pro(client, fixture_json):
    respx.get(f"{BASE_URL}/character-links").mock(
        return_value=httpx.Response(200, json=fixture_json("character_links"))
    )
    ent = respx.get(f"{BASE_URL}/entities").mock(
        return_value=httpx.Response(200, json=fixture_json("entities_multi"))
    )
    assert client.character_links([236695])[0].player_character_id == 236695
    group = client.entities(character_ids=[341427506], clan_ids=[127866])
    assert group.clans[0].tag == "MINDEL"
    assert params(ent) == [("characterId", "341427506"), ("clanId", "127866")]
    assert client.pro_player(1) is None  # entities_multi has no proPlayers


@respx.mock
def test_streams_stats_patches(client, fixture_json):
    respx.get(f"{BASE_URL}/streams").mock(
        return_value=httpx.Response(200, json=fixture_json("streams"))
    )
    respx.get(f"{BASE_URL}/stats/player-base").mock(
        return_value=httpx.Response(200, json=fixture_json("stats_player_base"))
    )
    respx.get(f"{BASE_URL}/stats/activity").mock(
        return_value=httpx.Response(200, json=fixture_json("stats_activity"))
    )
    bal = respx.get(f"{BASE_URL}/stats/balance-reports").mock(
        return_value=httpx.Response(200, json=fixture_json("balance_reports"))
    )
    respx.get(f"{BASE_URL}/patches").mock(
        return_value=httpx.Response(200, json=fixture_json("patches"))
    )
    assert client.streams(identified_only=True, limit=5).streams
    assert client.player_base_stats(Queue.LOTV_1V1, TeamType.ARRANGED)[-1].season == 68
    assert 63 in client.activity_stats(Queue.LOTV_1V1, TeamType.ARRANGED).by_season
    rep = client.balance_report(
        Queue.LOTV_1V1, TeamType.ARRANGED, League.GRANDMASTER, 0, 68, races=["ZERG"]
    )
    assert rep.frames
    assert ("tier", "FIRST") in params(bal) and ("league", "GRANDMASTER") in params(bal)
    assert client.patches()[0].patch.version == "5.0.17"


@respx.mock
def test_vods_and_clans(client, fixture_json):
    vod = respx.get(f"{BASE_URL}/matches").mock(
        return_value=httpx.Response(200, json=fixture_json("matches_vod"))
    )
    clans = respx.get(f"{BASE_URL}/clans").mock(
        side_effect=[
            httpx.Response(200, json=fixture_json("clans_list")),
            httpx.Response(200, json=fixture_json("clans_query")),
        ]
    )
    hist = respx.get(f"{BASE_URL}/clan-histories").mock(
        return_value=httpx.Response(200, json=fixture_json("clan_hist"))
    )
    assert client.vod_matches(race="ZERG").result
    assert ("vod", "true") in params(vod)
    assert client.clans(region="EU").result[0].tag == "RBLN"
    assert len(client.search_clans("Team", limit=2)) == 2
    assert ("query", "Team") in params(clans)
    assert client.clan_histories(character_ids=[236695]).events
    assert ("limit", "50") in params(hist)


@respx.mock
def test_force_refresh_bypasses_cache(client, fixture_json):
    route = respx.get(f"{BASE_URL}/seasons").mock(
        return_value=httpx.Response(200, json=fixture_json("seasons"))
    )
    client.seasons()
    client.seasons(force_refresh=True)
    assert route.call_count == 2
