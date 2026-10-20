from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from smurfsniper.api.registry import build_clients
from smurfsniper.api.sc2client.models import GamePlayer
from smurfsniper.core import account as account_mod
from smurfsniper.core.account import AccountCandidate, AccountService
from smurfsniper.core.game_state import GameContext, GameResult, split_teams
from smurfsniper.models.config import AccountConfig, Config

NOW = datetime(2026, 10, 14, 12, tzinfo=UTC)


class RecordingExecutor:
    """Executor that remembers submissions instead of running them."""

    def __init__(self):
        self.jobs: list[tuple] = []

    def submit(self, fn, *args, **kw):
        self.jobs.append((fn.__name__, args))

    def shutdown(self, **_kw):
        pass


def human(i: int, name: str, race: str = "Zerg") -> GamePlayer:
    return GamePlayer(id=i, name=name, race=race)


def ctx_for(players, me=None, mode="1v1", vs_ai=False, game_id=1) -> GameContext:
    opps = tuple(p for p in players if p != me and p.is_human)
    return GameContext(game_id, NOW, tuple(players), me, (), opps, mode, vs_ai)


@pytest.fixture
def svc(qtbot):
    cfg = Config()
    saves: list[int] = []
    s = AccountService(cfg, None, RecordingExecutor(), lambda: saves.append(1), now=lambda: NOW)
    s.saves = saves
    return s


def test_identify_by_configured_name(svc):
    svc.config.account.name = "Hero"
    me = human(1, "hero")
    assert svc.identify_me([me, human(2, "Foe")]) == me
    assert svc.identify_me([human(2, "Foe"), human(3, "Other")]) is None


def test_vs_ai_single_human_is_me_and_name_is_saved(svc, qtbot):
    me = human(1, "Hero#123")
    ai = GamePlayer(id=2, name="Elite AI", type="computer", race="Terr")
    assert svc.identify_me([me, ai]) == me
    qtbot.waitUntil(lambda: svc.config.account.name == "Hero", timeout=2000)
    assert svc.saves
    # the detected name triggers an account search on the executor
    assert svc._executor.jobs and svc._executor.jobs[0][0] == "_search_job"
    assert svc._executor.jobs[0][1] == ("Hero", True)


def test_auto_detect_off_does_not_store_name(svc, qtbot):
    svc.config.account.auto_detect = False
    me = human(1, "Hero")
    assert svc.identify_me([me]) == me
    qtbot.wait(50)
    assert svc.config.account.name is None


def test_two_of_three_rule(svc, qtbot):
    hero = "Hero"
    g1 = [human(1, hero), human(2, "A")]
    g2 = [human(1, hero), human(2, "B")]
    g3 = [human(1, hero), human(2, "C")]
    assert svc.identify_me(g1) is None  # first game: nothing to compare yet
    svc.observe_game(ctx_for(g1))
    svc._game_open = False  # the game ended
    svc.observe_game(ctx_for(g2))
    me = svc.identify_me(g3)
    assert me is not None and me.name == hero
    qtbot.waitUntil(lambda: svc.config.account.name == hero, timeout=2000)


def test_rematch_is_ambiguous_and_asks_for_picker(svc, qtbot):
    g = [human(1, "Hero"), human(2, "Rival")]
    svc.observe_game(ctx_for(g))
    svc._game_open = False
    asked: list[list[str]] = []
    svc.needs_picker.connect(asked.append)
    assert svc.identify_me(g) is None
    assert asked and sorted(asked[0]) == ["hero", "rival"]


def test_redetect_does_not_double_count(svc):
    g = [human(1, "Hero"), human(2, "A")]
    svc.observe_game(ctx_for(g))
    svc.observe_game(ctx_for(g, game_id=2))  # same roster, same running game
    assert len(svc._history) == 1
    assert svc.identify_me(g) is None  # still only one game of evidence


def test_unknown_me_shows_everyone_but_teammates_as_opponents():
    players = [human(1, "Me"), human(2, "Mate"), human(3, "X"), human(4, "Y")]
    allies, opponents = split_teams(players, None, {"mate"})
    assert [p.name for p in allies] == ["Mate"]
    assert [p.name for p in opponents] == ["Me", "X", "Y"]


# ---------------------------------------------------------------- search / choose
def test_search_builds_labelled_candidates(qtbot, pulse):
    clients = build_clients(Config(), disk_cache=False)
    ex = ThreadPoolExecutor(max_workers=1)
    svc = AccountService(Config(), clients, ex, lambda: None, now=lambda: NOW)
    with qtbot.waitSignal(svc.candidates_ready, timeout=5000) as blocker:
        svc.search("Serral#769")
    query, cands = blocker.args
    assert query == "Serral"
    assert {c.character.name for c in cands} == {"Serral#769", "Serral#949"}
    top = cands[0]
    assert top.region == "EU"
    label = top.label(NOW)
    assert label.startswith("Serral#") and "EU" in label and "MMR" in label
    assert "last played" in label and label.endswith("ago")
    # a repeated search is served from the in-memory cache without new jobs
    calls = pulse[1]["characters"].call_count
    with qtbot.waitSignal(svc.candidates_ready, timeout=2000):
        svc.search("Serral")
    assert pulse[1]["characters"].call_count == calls
    ex.shutdown()
    clients.close()


def test_choose_persists_identity(svc, qtbot, pulse):
    clients = build_clients(Config(), disk_cache=False)
    ex = ThreadPoolExecutor(max_workers=1)
    real = AccountService(svc.config, clients, ex, svc._save, now=lambda: NOW)
    with qtbot.waitSignal(real.candidates_ready, timeout=5000) as b:
        real.search("Serral")
    cand: AccountCandidate = next(c for c in b.args[1] if c.character.name == "Serral#769")
    with qtbot.waitSignal(real.account_changed, timeout=2000):
        real.choose(cand)
    acct = real.config.account
    assert acct.character_id == cand.character.id and acct.name == "Serral"
    assert acct.region == "EU" and acct.toon_handle
    assert acct.mmr_by_queue.get(201) == cand.mmr_1v1
    assert svc.saves
    ex.shutdown()
    clients.close()


# ----------------------------------------------------------------- mmr refresh
class ImmediateTimer:
    def __init__(self, interval, fn, args=(), kwargs=None):
        self.fn, self.args = fn, args

    def start(self):
        self.fn(*self.args)

    def cancel(self):
        pass

    daemon = True


def test_refresh_mmr_updates_once_then_stops(qtbot, pulse, monkeypatch):
    monkeypatch.setattr(account_mod.threading, "Timer", ImmediateTimer)
    clients = build_clients(Config(), disk_cache=False)
    cfg = Config(
        account=AccountConfig(
            character_id=341427506, name="Hero", region="EU", mmr_by_queue={201: 7000}
        )
    )
    saves: list[int] = []
    ex = ThreadPoolExecutor(max_workers=2)
    svc = AccountService(cfg, clients, ex, lambda: saves.append(1), now=lambda: NOW)
    me = human(1, "Hero", "Zerg")
    started = datetime(2026, 10, 13, 20, tzinfo=UTC)
    ctx = GameContext(1, started, (me, human(2, "Foe")), me, (), (human(2, "Foe"),), "1v1", False)
    emitted: list[tuple[int, int]] = []
    svc.mmr_refreshed.connect(lambda q, r: emitted.append((q, r)))
    with qtbot.waitSignal(svc.mmr_refreshed, timeout=5000) as blocker:
        svc.refresh_mmr_after_game(GameResult(ctx, "victory", 600.0))
    assert blocker.args == [201, 7023]  # the ZERG team's rating
    assert cfg.account.mmr_by_queue[201] == 7023
    assert cfg.account.mmr_updated_at == NOW
    assert saves
    qtbot.wait(300)  # the other two attempts must not apply a second update
    assert emitted == [(201, 7023)] and len(saves) == 1
    ex.shutdown()
    clients.close()


def test_refresh_skips_vs_ai_and_unknown_account(svc):
    me = human(1, "Hero")
    ctx = GameContext(1, NOW, (me,), me, (), (), "other", True)
    svc.config.account.character_id = 5
    svc.refresh_mmr_after_game(GameResult(ctx, "victory", 1.0))
    assert svc._timers == []
    svc.config.account.character_id = None
    ctx2 = GameContext(2, NOW, (me, human(2, "x")), me, (), (human(2, "x"),), "1v1", False)
    svc.refresh_mmr_after_game(GameResult(ctx2, "victory", 1.0))
    assert svc._timers == []


def test_retry_schedule_and_cancel(svc):
    svc.config.account.character_id = 5
    me = human(1, "Hero")
    ctx = GameContext(1, NOW, (me, human(2, "x")), me, (), (human(2, "x"),), "1v1", False)
    svc.refresh_mmr_after_game(GameResult(ctx, "victory", 1.0))
    assert [t.interval for t in svc._timers] == [20.0, 90.0, 300.0]
    assert all(isinstance(t, threading.Timer) for t in svc._timers)
    svc.stop()
    assert svc._timers == []
