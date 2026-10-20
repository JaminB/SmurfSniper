from __future__ import annotations

import httpx
import respx

from smurfsniper.api.sc2client import LocalSc2Client
from smurfsniper.api.sc2client.models import GameInfo, GamePlayer, UiInfo
from smurfsniper.core.game_state import (
    GameState,
    GameStateMachine,
    Sc2ClientPoller,
    derive_state,
    split_teams,
)
from smurfsniper.core.matching import identify_me


def machine(name: str | None = "Me", teammates: set[str] | None = None) -> GameStateMachine:
    return GameStateMachine(
        identify_me=lambda ps: identify_me(ps, name), teammates=lambda: set(teammates or ())
    )


def load(fixture_json):
    def _l(name, model):
        return model.model_validate(fixture_json(name))

    return {
        "menu": _l("ui_menu", UiInfo),
        "loading": _l("ui_loading", UiInfo),
        "ingame": _l("ui_ingame", UiInfo),
        "score": _l("ui_score", UiInfo),
        "g1v1": _l("game_1v1", GameInfo),
        "g2v2": _l("game_2v2", GameInfo),
        "result": _l("game_result", GameInfo),
        "replay": _l("game_replay", GameInfo),
        "ai": _l("game_vs_ai", GameInfo),
        "empty": _l("game_menu", GameInfo),
    }


def kinds(events):
    return [e.kind for e in events]


def test_rematch_detected(fixture_json):
    f = load(fixture_json)
    m = machine()
    seq = [
        (f["menu"], f["empty"]),
        (f["loading"], None),
        (f["ingame"], f["g1v1"]),
        (f["ingame"], f["g1v1"]),
        (f["ingame"], f["result"]),
        (f["score"], f["result"]),
        (f["menu"], f["result"]),
        (f["loading"], None),
        (f["ingame"], f["g1v1"]),
    ]
    started, ended, states = [], [], []
    for ui, game in seq:
        state, events = m.next_state(ui, game)
        states.append(state)
        for e in events:
            if e.kind == "started":
                started.append(e.payload)
            elif e.kind == "ended":
                ended.append(e.payload)
    assert states == [
        GameState.MENU,
        GameState.LOADING,
        GameState.IN_GAME,
        GameState.IN_GAME,
        GameState.RESULT,
        GameState.RESULT,
        GameState.RESULT,
        GameState.LOADING,
        GameState.IN_GAME,
    ]
    assert len(started) == 2
    assert started[0].game_id != started[1].game_id
    assert [p.name for p in started[1].opponents] == ["Serral"]
    assert len(ended) == 1
    assert ended[0].my_result == "victory" and ended[0].display_time == 872.0


def test_state_event_only_on_change(fixture_json):
    f = load(fixture_json)
    m = machine()
    _, ev1 = m.next_state(f["menu"], None)
    _, ev2 = m.next_state(f["menu"], None)
    assert kinds(ev1) == ["state"] and ev2 == []


def test_replay_no_game_started(fixture_json):
    f = load(fixture_json)
    m = machine()
    m.next_state(f["menu"], None)
    state, events = m.next_state(f["ingame"], f["replay"])
    assert state is GameState.REPLAY
    assert "started" not in kinds(events)


def test_vs_ai(fixture_json):
    f = load(fixture_json)
    _, events = machine().next_state(f["ingame"], f["ai"])
    ctx = next(e.payload for e in events if e.kind == "started")
    assert ctx.vs_ai and ctx.mode == "other" and ctx.opponents == ()


def test_offline_then_online(fixture_json):
    f = load(fixture_json)
    m = machine()
    m.state = GameState.MENU
    state, events = m.next_state(None, None)
    assert state is GameState.OFFLINE and kinds(events) == ["state"]
    _, events = m.next_state(None, None)
    assert events == []
    state, events = m.next_state(f["menu"], f["empty"])
    assert state is GameState.MENU and kinds(events) == ["state"]


def test_game_only_fallback(fixture_json):
    f = load(fixture_json)
    m = machine()
    assert m.next_state(None, f["g1v1"])[0] is GameState.IN_GAME
    assert m.next_state(None, f["result"])[0] is GameState.RESULT
    _, events = m.next_state(None, f["g1v1"])
    assert "started" in kinds(events)


def test_force_redetect(fixture_json):
    f = load(fixture_json)
    m = machine()
    m.next_state(f["ingame"], f["g1v1"])
    m.force_redetect()
    _, events = m.next_state(f["ingame"], f["g1v1"])
    assert kinds(events) == ["started"]
    assert m.current.game_id == 2


def test_unknown_me_result_from_opponents(fixture_json):
    f = load(fixture_json)
    m = machine(name=None)
    m.next_state(f["ingame"], f["g1v1"])
    _, events = m.next_state(f["ingame"], f["result"])
    res = next(e.payload for e in events if e.kind == "ended")
    # me unknown: both players are "opponents"; first opponent "Me" won -> we lost
    assert res.my_result in ("defeat", "victory")
    assert res.context.me is None and len(res.context.opponents) == 2


def test_split_teams_2v2(fixture_json):
    g = GameInfo.model_validate(fixture_json("game_2v2"))
    me = g.players[0]
    allies, opps = split_teams(g.players, me, set())
    assert [p.name for p in allies] == ["Eason"]
    assert [p.name for p in opps] == ["Nobody", "Nobody2"]
    # a configured teammate on the "other" half overrides the id split
    allies, opps = split_teams(g.players, me, {"nobody"})
    assert [p.name for p in allies] == ["Nobody"]
    assert {p.name for p in opps} == {"Eason", "Nobody2"}
    # me unknown: only teammates are excluded
    allies, opps = split_teams(g.players, None, {"Eason"})
    assert [p.name for p in opps] == ["BuyOneGetOne", "Nobody", "Nobody2"]


def test_mode_2v2(fixture_json):
    f = load(fixture_json)
    _, events = machine(name="BuyOneGetOne").next_state(f["ingame"], f["g2v2"])
    ctx = events[-1].payload
    assert ctx.mode == "2v2" and len(ctx.opponents) == 2


def test_derive_state_loading_beats_result():
    ui = UiInfo(active_screens=["ScreenLoading/ScreenLoading"])
    game = GameInfo(players=[GamePlayer(id=1, name="a", result="Victory")])
    assert derive_state(GameState.RESULT, ui, game) is GameState.LOADING


@respx.mock
def test_poller_tick_emits(qtbot, fixture_json):
    respx.get("http://localhost:6119/ui").mock(
        return_value=httpx.Response(200, json=fixture_json("ui_ingame"))
    )
    respx.get("http://localhost:6119/game").mock(
        return_value=httpx.Response(200, json=fixture_json("game_1v1"))
    )
    poller = Sc2ClientPoller(
        LocalSc2Client(), identify_me=lambda ps: identify_me(ps, "Me"), teammates=set
    )
    started = []
    poller.game_started.connect(started.append)
    poller.tick()
    poller.tick()
    assert len(started) == 1 and started[0].opponents[0].name == "Serral"


@respx.mock
def test_poller_offline_logs_once(qtbot):
    from loguru import logger

    respx.get("http://localhost:6119/ui").mock(side_effect=httpx.ConnectError("refused"))
    respx.get("http://localhost:6119/game").mock(side_effect=httpx.ConnectError("refused"))
    msgs: list[str] = []
    sink = logger.add(lambda m: msgs.append(m.record["message"]), level="DEBUG")
    try:
        poller = Sc2ClientPoller(LocalSc2Client(), identify_me=lambda ps: None, teammates=set)
        for _ in range(3):
            poller.tick()
    finally:
        logger.remove(sink)
    assert msgs.count("SC2 client offline") == 1
    assert not any("ERROR" in m or "failed" in m for m in msgs)


def test_screen_over_running_game_is_not_a_new_game(fixture_json):
    f = load(fixture_json)
    m = machine()
    m.next_state(f["ingame"], f["g1v1"])
    # e.g. the in-game menu: /ui reports a screen while /game still runs undecided
    state, events = m.next_state(f["menu"], f["g1v1"])
    assert state is GameState.IN_GAME and events == []
    state, events = m.next_state(f["ingame"], f["g1v1"])
    assert state is GameState.IN_GAME and events == []
    assert m.current.game_id == 1


def test_roster_change_while_in_game_starts_new_game(fixture_json):
    f = load(fixture_json)
    m = machine(name="BuyOneGetOne")
    m.next_state(f["ingame"], f["g1v1"])
    _, events = m.next_state(f["ingame"], f["g2v2"])
    assert kinds(events) == ["started"] and m.current.game_id == 2
