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
    assert prof.tendencies is None or prof.tendencies.data.games >= 3
    assert prof.intel is not None and prof.intel.liquipedia.title == "Serral"

    # cold cache: query, teams, seasons, thresholds, histories, summaries, matches, account
    # (+ entities and links for the pro-only INTEL stage)
    core_calls = pulse_calls(routes) - routes["entities"].call_count - routes["links"].call_count
    assert core_calls <= 8  # + the account's other characters (alt-account signal)
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


# ------------------------------------------------------------------ branch 5
@pytest.fixture
def store_pipeline(tmp_path):
    clients = build_clients(config(), disk_cache=False)
    db = init_db(tmp_path / "db.sqlite3")
    store = PlayerLogStore(db)
    pipe = LookupPipeline(
        clients, store, my_mmr=lambda: 7000, my_region=lambda: "EU", mmr_window=lambda: 500
    )
    yield pipe, store
    pipe.shutdown()
    clients.close()
    db.close()


def test_alt_account_with_a_higher_peak_adds_the_alt_peak_reason(
    qtbot, pulse, pipeline, fixture_json
):
    _, routes = pulse
    search = httpx.Response(200, json=fixture_json("characters_query"))
    account = httpx.Response(200, json=fixture_json("chars_account"))

    def handler(request: httpx.Request) -> httpx.Response:
        return account if "accountId" in request.url.params else search

    routes["characters"].side_effect = handler
    got = collect(pipeline)
    pipeline.start(ctx())
    qtbot.waitUntil(lambda: Stage.SMURF in {u.stage for u in got}, timeout=5000)
    assessment = pipeline.results(1)[0].smurf.assessment
    alt = next(r for r in assessment.reasons if r.code == "alt_peak")
    assert alt.points == 35 and "peaked 8,127" in alt.text
    assert any("accountId" in str(c.request.url) for c in routes["characters"].calls)


def test_smurf_stage_survives_an_account_lookup_failure(qtbot, pulse, pipeline, fixture_json):
    _, routes = pulse
    search = httpx.Response(200, json=fixture_json("characters_query"))
    routes["characters"].side_effect = lambda r: (
        httpx.Response(500) if "accountId" in r.url.params else search
    )
    got = collect(pipeline)
    pipeline.start(ctx())
    qtbot.waitUntil(lambda: Stage.SMURF in {u.stage for u in got}, timeout=8000)
    smurf = next(u for u in got if u.stage is Stage.SMURF)
    assert smurf.error is None and smurf.data is not None


def test_tendencies_stage_wraps_the_pure_analysis(qtbot, pulse, pipeline):
    from tests.test_tendencies import mk

    _, routes = pulse
    matches = [mk(i, i % 3 != 0, me=236695, opp_race="TERRAN", secs=500) for i in range(1, 9)]
    page = {
        "result": [m.model_dump(by_alias=True, mode="json") for m in matches],
        "navigation": {"after": None},
    }
    routes["matches"].mock(return_value=httpx.Response(200, json=page))
    got = collect(pipeline)
    pipeline.start(ctx())
    qtbot.waitUntil(lambda: Stage.TENDENCIES in {u.stage for u in got}, timeout=5000)
    data = pipeline.results(1)[0].tendencies.data
    assert data.games == 8 and data.vs_race["TERRAN"].games == 8
    assert data.avg_duration_s == 500 and len(data.form) == 8
    assert routes["matches"].calls.last.request.url.params["limit"] == "50"


def test_tendencies_stage_is_empty_below_three_matches(qtbot, pulse, pipeline):
    _, routes = pulse
    routes["matches"].mock(
        return_value=httpx.Response(200, json={"result": [], "navigation": {"after": None}})
    )
    got = collect(pipeline)
    pipeline.start(ctx())
    qtbot.waitUntil(lambda: Stage.TENDENCIES in {u.stage for u in got}, timeout=5000)
    assert pipeline.results(1)[0].tendencies is None


def test_h2h_is_tagged_rival_or_nemesis(qtbot, pulse, store_pipeline):
    from smurfsniper.storage.player_log import PlayerLog

    pipe, store = store_pipeline
    got = collect(pipe)
    pipe.start(ctx())
    qtbot.waitUntil(lambda: Stage.IDENTITY in {u.stage for u in got}, timeout=5000)
    ident = pipe.results(1)[0].identity
    ch = ident.character

    def log(result: str, n: int) -> None:
        for _ in range(n):
            PlayerLog.insert(
                battlenet_id=ch.battlenet_id,
                name=ch.name,
                realm=ch.realm,
                region=ch.region,
                match_status={"victory": "defeat", "defeat": "victory"}[result],
                created_at=datetime(2026, 10, 1),
                mode="1v1",
                my_result=result,
            ).execute()

    assert pipe._h2h(ctx(), 0, ident) is None
    log("victory", 1)
    assert pipe._h2h(ctx(), 0, ident).rivalry is None  # one game is not a rivalry
    log("victory", 1)
    assert pipe._h2h(ctx(), 0, ident).rivalry == "rival"
    log("defeat", 5)
    info = pipe._h2h(ctx(), 0, ident)
    assert (info.wins, info.losses, info.rivalry) == (2, 5, "nemesis")


@pytest.mark.parametrize(
    ("uid", "race"),
    [
        ("201-0-2-1.315071.3", "ZERG"),
        ("1.315071.2", "PROTOSS"),  # static=LEGACY_ID form
        ("201-0-2-1.315071.*", None),
        ("", None),
    ],
)
def test_race_of_uid_reads_the_race_segment(uid, race):
    from smurfsniper.core.lookup import _race_of_uid

    assert _race_of_uid(uid) == race
