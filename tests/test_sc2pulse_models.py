from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import TypeAdapter

from smurfsniper.api.sc2pulse import models as m
from smurfsniper.api.sc2pulse.ids import (
    HistoryColumn,
    Queue,
    solo_legacy_uid,
    toon_handle,
)

LIST_FIXTURES = {
    "characters_query": m.LadderDistinctCharacter,
    "chars_account": m.LadderDistinctCharacter,
    "chars_by_ids": m.LadderDistinctCharacter,
    "chars_toon": m.LadderDistinctCharacter,
    "character_teams": m.LadderTeam,
    "character_teams_filtered": m.LadderTeam,
    "character_links": m.CharacterLinks,
    "team_histories": m.TeamHistorySeries,
    "team_history_summaries": m.TeamHistorySummary,
    "team_history_summaries_active": m.TeamHistorySummary,
    "teams_last": m.LadderTeam,
    "teams_recent": m.LadderTeam,
    "seasons": m.Season,
    "patches": m.PatchEntry,
    "clans_query": m.Clan,
    "stats_player_base": m.QueueStats,
}


@pytest.mark.parametrize("name,model", sorted(LIST_FIXTURES.items()))
def test_list_fixtures_validate(fixture_json, name, model):
    data = fixture_json(name)
    parsed = TypeAdapter(list[model]).validate_python(data)
    assert len(parsed) == len(data) > 0


@pytest.mark.parametrize(
    "name,model",
    [
        ("character_matches", m.Page[m.LadderMatch]),
        ("matches_vod", m.Page[m.LadderMatch]),
        ("teams_ladder", m.Page[m.LadderTeam]),
        ("clans_list", m.Page[m.Clan]),
        ("entities_char", m.EntityGroup),
        ("entities_multi", m.EntityGroup),
        ("tier_thresholds", m.TierThresholds),
        ("streams", m.StreamsResponse),
        ("stats_activity", m.ActivityStats),
        ("balance_reports", m.BalanceReport),
    ],
)
def test_object_fixtures_validate(fixture_json, name, model):
    model.model_validate(fixture_json(name))


def test_serral_character(fixture_json):
    chars = TypeAdapter(list[m.LadderDistinctCharacter]).validate_python(
        fixture_json("characters_query")
    )
    serral = chars[0]
    assert serral.members.character.id == 236695
    assert serral.members.character.base_name == "Serral"
    assert serral.members.zerg_games_played == 5131
    assert serral.members.random_games_played == 0
    assert serral.members.main_race == "ZERG"
    assert serral.members.clan.tag == "BASKGG"
    assert serral.members.pro_player.pro_player.nickname == "Serral"
    assert serral.rating == 7065  # falls back to previous season
    assert serral.current_stats.rating is None


def test_team_fields(fixture_json):
    team = m.LadderTeam.model_validate(fixture_json("character_teams")[0])
    assert team.legacy_uid == "201-0-2-1.11355642.4"
    assert team.league_id == 6
    assert team.last_played == datetime(2026, 10, 13, 16, 31, 39, tzinfo=UTC)
    assert team.region_percentile == pytest.approx(100 * (1 - 2 / 54165))
    assert team.character_ids == {341427506}


def test_team_history_series(fixture_json):
    series = TypeAdapter(list[m.TeamHistorySeries]).validate_python(fixture_json("team_histories"))
    s = series[0]
    assert s.legacy_uid == "201-0-2-1.11355642.4"
    assert s.column(HistoryColumn.RATING)[0] == 7696
    assert len(s.column(HistoryColumn.WINS)) == len(s) == 18
    assert s.column(HistoryColumn.GLOBAL_RANK) is None


def test_team_history_unequal_columns_truncated():
    s = m.TeamHistorySeries.model_validate(
        {"staticData": {"LEGACY_UID": "x"}, "history": {"TIMESTAMP": [1, 2, 3], "RATING": [5, 6]}}
    )
    assert s.column("TIMESTAMP") == [1, 2]


def test_summary(fixture_json):
    s = m.TeamHistorySummary.model_validate(fixture_json("team_history_summaries")[0])
    assert s.legacy_uid == "201-0-2-1.315071.3"
    assert s.rating_max == 7557 and s.games == 5131 and s.league_type_max == 6


def test_tier_thresholds_band(fixture_json):
    tt = m.TierThresholds.model_validate(fixture_json("tier_thresholds"))
    assert tt.band("EU", 4000) == (4, 0, 3960, 4360)
    assert tt.band("EU", 1000) == (0, 2, 1000, 1253)
    assert tt.band("EU", 9000) is None
    assert tt.band("US", 4000) is None


def test_match_helpers(fixture_json):
    page = m.Page[m.LadderMatch].model_validate(fixture_json("character_matches"))
    match = page.result[0]
    me = match.participant_for(341427506)
    assert me is not None and me.participant.decision == "WIN"
    opps = match.opponents_of(341427506)
    assert opps and all(o.participant.player_character_id != 341427506 for o in opps)
    assert match.map.name == "Rainfall LE"
    assert page.navigation.after


def test_links_and_streams(fixture_json):
    links = TypeAdapter(list[m.CharacterLinks]).validate_python(fixture_json("character_links"))
    assert links[0].links[1].url == "https://sc2replaystats.com/player/125470"
    streams = m.StreamsResponse.model_validate(fixture_json("streams"))
    entry = streams.streams[0]
    assert entry.stream.user_name == "ninasc2"
    assert entry.pro_player.pro_player.aligulac_id == 317
    assert entry.pro_player.links[0].type == "ALIGULAC"


def test_clan_history(fixture_json):
    hist = m.ClanHistory.model_validate(fixture_json("clan_hist")["result"])
    assert hist.events[0].type == "JOIN"
    assert hist.clans[0].tag == "BASKGG"


def test_ids():
    assert solo_legacy_uid(Queue.LOTV_1V1, "EU", 1, 315071, "ZERG") == "201-0-2-1.315071.3"
    assert solo_legacy_uid(Queue.LOTV_1V1, "US", 1, 5, None) == "201-0-1-1.5.*"
    assert toon_handle("EU", 1, 315071) == "2-S2-1-315071"
