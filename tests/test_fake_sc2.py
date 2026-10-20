from __future__ import annotations

import importlib.util
from pathlib import Path

from smurfsniper.api.sc2client.models import GameInfo, UiInfo
from smurfsniper.core.game_state import GameState, GameStateMachine
from smurfsniper.core.matching import identify_me

ROOT = Path(__file__).resolve().parent.parent


def load_script():
    spec = importlib.util.spec_from_file_location("fake_sc2", ROOT / "scripts" / "fake_sc2.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_phase_cycle_drives_state_machine(monkeypatch):
    mod = load_script()
    clock = [0.0]
    monkeypatch.setattr(mod.time, "monotonic", lambda: clock[0])
    phases = mod.Phases(mod.load("game_1v1"), menu=1, loading=1, in_game=1, result=1, me="Me")
    m = GameStateMachine(identify_me=lambda ps: identify_me(ps, "Me"), teammates=set)
    seen, started, ended = [], 0, []
    for step in range(11):  # two full cycles, then menu, loading, in-game again
        clock[0] = step + 0.5
        _, ui, game = phases.current()
        state, events = m.next_state(UiInfo.model_validate(ui), GameInfo.model_validate(game))
        seen.append(state)
        started += sum(e.kind == "started" for e in events)
        ended += [e.payload for e in events if e.kind == "ended"]
    assert seen[:4] == [GameState.MENU, GameState.LOADING, GameState.IN_GAME, GameState.RESULT]
    assert started == 3 and len(ended) == 2
    assert ended[0].my_result == "victory"
