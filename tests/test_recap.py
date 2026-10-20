"""Post-game recap toast: text, in-place MMR update and the H2H suffix."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from smurfsniper.analyze.h2h import H2HInfo
from smurfsniper.api.sc2client.models import GamePlayer
from smurfsniper.core.events import EventBus
from smurfsniper.core.game_state import GameContext, GameResult
from smurfsniper.core.profile import GameSeed, OpponentProfile
from smurfsniper.core.recap import MMR_WINDOW, RECAP_TOAST_MS, RecapService
from smurfsniper.core.session import SessionTracker
from smurfsniper.ui import tokens as t

T0 = datetime(2026, 10, 19, 18, 0, tzinfo=UTC)


class Inline:
    def submit(self, fn, *a, **kw):
        fn(*a, **kw)


class Pipeline:
    def __init__(self):
        self.profiles: dict = {}

    def results(self, game_id):
        return self.profiles


class Clock:
    now = T0

    def __call__(self):
        return self.now


@pytest.fixture
def env(qtbot):
    bus = EventBus()
    clock = Clock()
    clock.now = T0
    pipe = Pipeline()
    tracker = SessionTracker(bus, None, pipe, mmr_for=lambda q: 4000, executor=Inline(), now=clock)
    recap = RecapService(bus, tracker, now=clock)
    toasts = []
    bus.toast_requested.connect(toasts.append)
    return bus, clock, pipe, tracker, recap, toasts


def finish(
    env, game_id=1, outcome="victory", opponents=(("Bob#12", "Zerg"),), mode="1v1", secs=872.0
):
    bus, clock, pipe, *_ = env
    me = GamePlayer(id=1, name="Me", race="Terran")
    opps = tuple(GamePlayer(id=i + 2, name=n, race=r) for i, (n, r) in enumerate(opponents))
    ctx = GameContext(game_id, clock.now, (me, *opps), me, (), opps, mode, False)
    bus.game_started.emit(ctx)
    clock.now += timedelta(seconds=secs)
    bus.game_ended.emit(GameResult(ctx, outcome, secs))  # type: ignore[arg-type]
    return ctx


def test_recap_constant_matches_the_token():
    assert t.ANIM["toast_recap_ms"] == RECAP_TOAST_MS


def test_victory_toast_text(env):
    finish(env, secs=872.0)
    (spec,) = env[-1]
    assert spec.title == "Victory vs Bob (Zerg)"
    assert spec.body == "14:32 · Session 1-0"
    assert spec.kind == "win" and spec.id == "recap-1" and spec.duration_ms == RECAP_TOAST_MS


def test_defeat_and_session_record_accumulates(env):
    finish(env, 1, "victory")
    finish(env, 2, "defeat")
    spec = env[-1][-1]
    assert spec.title == "Defeat vs Bob (Zerg)" and spec.kind == "loss"
    assert spec.id == "recap-2" and "Session 1-1" in spec.body


def test_tie_is_informational(env):
    finish(env, outcome="tie")
    assert env[-1][-1].title.startswith("Tie vs") and env[-1][-1].kind == "info"


def test_team_games_name_the_opponents(env):
    finish(
        env, 1, mode="2v2", opponents=(("PlayerA#1", "Zerg"), ("PlayerB#2", "Protoss")), secs=700
    )
    assert env[-1][-1].title == "Victory vs PlayerA & PlayerB"
    finish(env, 2, mode="4v4", opponents=tuple((f"P{i}", "Zerg") for i in range(4)), secs=700)
    assert env[-1][-1].title == "Victory vs 4 opponents"


def h2h(wins: int, losses: int) -> H2HInfo:
    return H2HInfo(wins + losses, wins, losses, 0, T0 - timedelta(days=9), T0 - timedelta(days=2))


def test_h2h_suffix_only_from_two_games_including_this_one(env):
    pipe = env[2]
    finish(env, 1)  # never played before: this is game 1
    assert "You" not in env[-1][-1].body
    prof = OpponentProfile(seed=GameSeed("Bob", "ZERG"), h2h=h2h(1, 0))
    pipe.profiles = {0: prof}
    finish(env, 2, "victory")  # stored 1-0 + this win = 2-0
    assert env[-1][-1].body.endswith("You 2-0 vs Bob")
    pipe.profiles = {0: OpponentProfile(seed=GameSeed("Bob", "ZERG"), h2h=h2h(2, 5))}
    finish(env, 3, "defeat")
    assert env[-1][-1].body.endswith("You 2-6 vs Bob")


def test_mmr_update_reuses_the_toast_id_and_prefixes_the_delta(env):
    bus, clock, pipe, tracker, recap, toasts = env
    finish(env, 1)
    clock.now += timedelta(seconds=20)
    recap.on_mmr_refreshed(201, 4024)
    first, second = toasts
    assert second.id == first.id == "recap-1"
    assert second.title == first.title
    assert second.body == "+24 MMR (4,024) · " + first.body
    assert second.duration_ms == RECAP_TOAST_MS  # the timer restarts


def test_negative_delta_and_wrong_queue(env):
    bus, clock, pipe, tracker, recap, toasts = env
    finish(env, 1, "defeat")
    recap.on_mmr_refreshed(202, 4100)  # other queue
    assert len(toasts) == 1
    recap.on_mmr_refreshed(201, 3982)
    assert toasts[-1].body.startswith("-18 MMR (3,982) · ")


def test_mmr_update_after_the_window_is_dropped(env):
    bus, clock, pipe, tracker, recap, toasts = env
    finish(env, 1)
    clock.now += MMR_WINDOW + timedelta(seconds=1)
    recap.on_mmr_refreshed(201, 4024)
    assert len(toasts) == 1


def test_mmr_update_pushes_again_when_the_toast_expired(env, no_anim):
    """Same id after expiry: the stack treats it as a new toast, it is not dropped."""
    from smurfsniper.core.toasts import ToastSpec  # noqa: F401
    from smurfsniper.models.config import Config
    from smurfsniper.ui.overlay import ToastStack
    from smurfsniper.ui.tokens import TokenContext

    bus, clock, pipe, tracker, recap, toasts = env
    stack = ToastStack(TokenContext(), Config().overlays.toasts.placement)
    bus.toast_requested.connect(stack.push)
    finish(env, 1)
    (toast,) = stack.visible_toasts()
    stack.dismiss_toast(toast)  # expired
    assert stack.visible_toasts() == []
    clock.now += timedelta(seconds=30)
    recap.on_mmr_refreshed(201, 4024)
    (again,) = stack.visible_toasts()
    assert again.spec.id == "recap-1" and again.spec.body.startswith("+24 MMR")
    stack.clear()


def test_no_recap_without_a_result_or_for_ai_games(env):
    finish(env, outcome=None)
    assert env[-1] == []


def test_unknown_previous_rating_still_reports_the_new_one(qtbot):
    bus = EventBus()
    clock = Clock()
    clock.now = T0
    tracker = SessionTracker(
        bus, None, Pipeline(), mmr_for=lambda q: None, executor=Inline(), now=clock
    )
    recap = RecapService(bus, tracker, now=clock)
    toasts = []
    bus.toast_requested.connect(toasts.append)
    finish((bus, clock, Pipeline(), tracker, recap, toasts))
    recap.on_mmr_refreshed(201, 4024)
    assert toasts[-1].body.startswith("4,024 MMR · ")
