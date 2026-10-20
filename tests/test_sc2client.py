from __future__ import annotations

import httpx
import pytest
import respx

from smurfsniper.api.errors import Unavailable
from smurfsniper.api.sc2client import LocalSc2Client, normalize_base_url

BASE = "http://localhost:6119"


def test_normalize_base_url():
    assert normalize_base_url("http://localhost:6119/game") == BASE
    assert normalize_base_url("http://localhost:6119/") == BASE
    assert normalize_base_url(None) == BASE


@respx.mock
def test_game_and_ui(fixture_json):
    respx.get(f"{BASE}/game").mock(return_value=httpx.Response(200, json=fixture_json("game_2v2")))
    respx.get(f"{BASE}/ui").mock(return_value=httpx.Response(200, json=fixture_json("ui_loading")))
    c = LocalSc2Client(f"{BASE}/game")
    game = c.game()
    assert len(game.players) == 4 and not game.is_replay
    assert [p.race_code for p in game.players] == ["TERRAN", "PROTOSS", "ZERG", "RANDOM"]
    assert all(p.is_human for p in game.players)
    assert c.ui().loading
    c.close()


@respx.mock
def test_ai_player(fixture_json):
    respx.get(f"{BASE}/game").mock(
        return_value=httpx.Response(200, json=fixture_json("game_vs_ai"))
    )
    game = LocalSc2Client().game()
    assert [p.is_human for p in game.players] == [True, False]


@respx.mock
def test_refused_is_unavailable_single_try():
    route = respx.get(f"{BASE}/ui").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(Unavailable):
        LocalSc2Client().ui()
    assert route.call_count == 1
