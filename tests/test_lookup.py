from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx

from smurfsniper.api import transport as tr
from smurfsniper.api.registry import build_clients
from smurfsniper.api.sc2client.models import GamePlayer
from smurfsniper.api.sc2pulse import BASE_URL
from smurfsniper.core.events import EventBus
from smurfsniper.core.game_state import GameContext
from smurfsniper.core.lookup import TEAM_SLOT, LookupPipeline
from smurfsniper.core.profile import LookupUpdate, Stage
from smurfsniper.models.config import Config
from smurfsniper.storage.db import init_db
from smurfsniper.storage.player_log import PlayerLogStore
from smurfsniper.ui.hud import HudController

CORE = {Stage.IDENTITY, Stage.RATING, Stage.SMURF, Stage.H2H, Stage.TENDENCIES}


def config() -> Config:
    return Config()


def ctx(game_id: int = 1, opponents=("Serral",), mode="1v1") -> GameContext:
    me = GamePlayer(id=1, name="Me", race="Terr")
    opps = tuple(GamePlayer(id=i + 2, name=n, race="Zerg") for i, n in enumerate(opponents))
    return GameContext(
        game_id=game_id,
        started_at=datetime(2026, 10, 19, 12, tzinfo=UTC),
        players=(me, *opps),
        me=me,
        allies=(),
        opponents=opps,
        mode=mode,
        vs_ai=False,
    )


@pytest.fixture
def no_gui_network(monkeypatch):
    def boom(path: str) -> None:
        raise AssertionError(f"network on GUI thread: {path}")

    monkeypatch.setattr(tr, "gui_thread_hook", boom)


@pytest.fixture
def pipeline(tmp_path):
    clients = build_clients(config(), disk_cache=False)
    db = init_db(tmp_path / "db.sqlite3")
    pipe = LookupPipeline(
        clients,
        PlayerLogStore(db),
        my_mmr=lambda: 7000,
        my_region=lambda: "EU",
        mmr_window=lambda: 500,
    )
    yield pipe
    pipe.shutdown()
    clients.close()
    db.close()


def collect(pipe: LookupPipeline) -> list[LookupUpdate]:
    got: list[LookupUpdate] = []
    pipe.update.connect(got.append)
    return got


def pulse_calls(routes) -> int:
    return sum(r.call_count for k, r in routes.items() if k != "liquipedia")


def test_stage_order_and_results(qtbot, pulse, pipeline, no_gui_network):
    _, routes = pulse
    got = collect(pipeline)
    pipeline.start(ctx())
    assert [u.stage for u in got] == [Stage.GAME]  # emitted synchronously
    qtbot.waitUntil(lambda: CORE | {Stage.INTEL} <= {u.stage for u in got}, timeout=5000)

    stages = [u.stage for u in got]
    assert stages[0] is Stage.GAME and stages[1] is Stage.IDENTITY
    assert set(stages[2:]) == {Stage.RATING, Stage.SMURF, Stage.H2H, Stage.TENDENCIES, Stage.INTEL}
    assert all(u.error is None for u in got), [u.error for u in got if u.error]

    prof = pipeline.results(1)[0]
    assert prof.identity.character.id == 236695
    assert prof.rating.mmr is not None and prof.rating.peak_mmr == 7557
    assert prof.smurf.assessment.score >= 0 and prof.smurf.sparkline
    assert prof.h2h is None  # never played
    assert prof.tendencies is None or prof.tendencies.recent is not None
    assert prof.intel is not None and prof.intel.liquipedia.title == "Serral"

    # cold cache: query, teams, seasons, thresholds, histories, summaries, matches
    # (+ entities and links for the pro-only INTEL stage)
    core_calls = pulse_calls(routes) - routes["entities"].call_count - routes["links"].call_count
    assert core_calls <= 7
    assert routes["seasons"].call_count == 1


def test_warm_cache_makes_no_calls(qtbot, pulse, pipeline, no_gui_network):
    _, routes = pulse
    got = collect(pipeline)
    pipeline.start(ctx(1))
    qtbot.waitUntil(lambda: CORE | {Stage.INTEL} <= {u.stage for u in got}, timeout=5000)
    before = pulse_calls(routes) + routes["liquipedia"].call_count
    got.clear()
    pipeline.start(ctx(2))
    qtbot.waitUntil(
        lambda: CORE | {Stage.INTEL} <= {u.stage for u in got if u.game_id == 2}, timeout=5000
    )
    assert pulse_calls(routes) + routes["liquipedia"].call_count == before


def test_ensure_is_noop_when_done(qtbot, pulse, pipeline):
    _, routes = pulse
    got = collect(pipeline)
    pipeline.start(ctx())
    qtbot.waitUntil(lambda: CORE | {Stage.INTEL} <= {u.stage for u in got}, timeout=5000)
    n = len(got)
    pipeline.ensure(1, 0, Stage.INTEL)
    qtbot.wait(100)
    assert len(got) == n


def test_identity_failure_reports_error(qtbot, pipeline, fixture_json):
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE_URL}/characters").mock(return_value=httpx.Response(400))
        got = collect(pipeline)
        pipeline.start(ctx())
        qtbot.waitUntil(lambda: any(u.stage is Stage.IDENTITY for u in got), timeout=5000)
        qtbot.wait(100)
    ident = next(u for u in got if u.stage is Stage.IDENTITY)
    assert ident.data is None and ident.error
    assert {u.stage for u in got} == {Stage.GAME, Stage.IDENTITY}  # successors skipped


def test_no_match_returns_none(qtbot, pipeline):
    with respx.mock(assert_all_called=False) as mock:
        mock.get(f"{BASE_URL}/characters").mock(return_value=httpx.Response(200, json=[]))
        got = collect(pipeline)
        pipeline.start(ctx(opponents=("Nobody",)))
        qtbot.waitUntil(lambda: any(u.stage is Stage.IDENTITY for u in got), timeout=5000)
    ident = next(u for u in got if u.stage is Stage.IDENTITY)
    assert ident.data is None and ident.error is None


def test_vs_ai_skips_lookups(qtbot, pipeline):
    c = ctx()
    c = GameContext(**{**c.__dict__, "vs_ai": True})
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get(f"{BASE_URL}/characters")
        got = collect(pipeline)
        pipeline.start(c)
        qtbot.wait(150)
    assert route.call_count == 0
    assert [u.stage for u in got] == [Stage.GAME]


def test_team_stage_for_2v2(qtbot, pulse, pipeline, fixture_json):
    mock, routes = pulse
    team_payload = fixture_json("character_teams")
    team = dict(team_payload[0])
    serral_member = fixture_json("characters_query")[0]["members"]
    team["members"] = [serral_member, serral_member]
    routes["teams"].mock(return_value=httpx.Response(200, json=[team]))
    got = collect(pipeline)
    pipeline.start(ctx(opponents=("Serral", "Serral"), mode="2v2"))
    qtbot.waitUntil(lambda: any(u.stage is Stage.TEAM for u in got), timeout=5000)
    t = next(u for u in got if u.stage is Stage.TEAM)
    assert t.slot == TEAM_SLOT and t.error is None
    assert t.data is not None and t.data.team.rating == 8127


def test_stale_updates_dropped_by_hud(qtbot, pulse, pipeline):
    hud = HudController(EventBus(), pipeline, config())
    c1 = ctx(1)
    hud.on_game_started(c1)
    pipeline.start(c1)
    # A new game starts before game 1's lookups land.
    c2 = ctx(2)
    hud.on_game_started(c2)
    hud.on_update(LookupUpdate(1, 0, Stage.IDENTITY, None))
    assert hud.dropped >= 1
    pipeline.start(c2)
    qtbot.waitUntil(lambda: hud.profiles[0].done(Stage.SMURF), timeout=5000)
    assert hud.game_id == 2 and hud.card.game_id == 2
    assert hud.profiles[0].rating is not None
    hud.reset_for_new_game()
