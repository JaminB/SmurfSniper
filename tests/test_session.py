"""Session snapshot maths, the SQLite store's 3 h rollover and the SessionTracker wiring."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from smurfsniper.analyze.history import Record
from smurfsniper.analyze.session import snapshot
from smurfsniper.api.sc2client.models import GamePlayer
from smurfsniper.core.events import EventBus
from smurfsniper.core.game_state import GameContext, GameResult
from smurfsniper.core.session import SessionTracker
from smurfsniper.storage.db import init_db
from smurfsniper.storage.rows import SessionGame, SessionOpponent
from smurfsniper.storage.session_store import SESSION_GAP, SessionStore

T0 = datetime(2026, 10, 19, 18, 0, tzinfo=UTC)


class Inline:
    """Executor that runs jobs immediately on the calling thread."""

    def submit(self, fn, *a, **kw):
        fn(*a, **kw)


class FakePipeline:
    def results(self, game_id):
        return {}


class Clock:
    def __init__(self, now: datetime = T0):
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def sg(
    n: int,
    result: str | None,
    *,
    race: str = "ZERG",
    mode: str = "1v1",
    before: int | None = None,
    after: int | None = None,
    secs: int | None = 600,
) -> SessionGame:
    return SessionGame(
        session_id=1,
        game_uid=f"g{n}",
        started_at=T0 + timedelta(minutes=20 * n),
        ended_at=T0 + timedelta(minutes=20 * n + 10),
        mode=mode,
        my_result=result,
        opponents=(SessionOpponent(f"Opp{n}", race),),
        mmr_before=before,
        mmr_after=after,
        game_seconds=secs,
    )


# ----------------------------------------------------------------- snapshot
def test_snapshot_record_streak_and_matchups():
    games = [
        sg(0, "victory", race="ZERG"),
        sg(1, "defeat", race="ZERG"),
        sg(2, "victory", race="TERRAN"),
        sg(3, "victory", race="PROTOSS"),
        sg(4, "tie", race="ZERG"),
        sg(5, "victory", race="ZERG"),
    ]
    s = snapshot(games, mmr_start=None)
    assert (s.games, s.wins, s.losses, s.ties) == (6, 4, 1, 1)
    assert s.streak == ("W", 3)  # a tie does not break the run: W W (tie) W
    assert s.by_matchup == {"vP": Record(1, 0), "vT": Record(1, 0), "vZ": Record(2, 1)}
    assert s.time_played_s == 6 * 600


def test_snapshot_streak_runs():
    s = snapshot(
        [sg(0, "defeat"), sg(1, "victory"), sg(2, "victory"), sg(3, "victory")], mmr_start=None
    )
    assert s.streak == ("W", 3)
    s = snapshot([sg(0, "victory"), sg(1, "defeat"), sg(2, "defeat")], mmr_start=None)
    assert s.streak == ("L", 2)
    assert snapshot([], mmr_start=None).streak is None
    assert snapshot([sg(0, "tie")], mmr_start=None).streak is None


def test_snapshot_mmr_is_hidden_until_one_rating_after_is_known():
    games = [sg(0, "victory", before=4100), sg(1, "victory", before=4118)]
    s = snapshot(games, mmr_start=4100)
    assert s.mmr_start == 4100 and s.mmr_now is None and s.mmr_delta is None
    assert s.mmr_points == ()
    games[0] = sg(0, "victory", before=4100, after=4118)
    s = snapshot(games, mmr_start=4100)
    assert (s.mmr_now, s.mmr_delta) == (4118, 18)
    assert s.mmr_points == (4100, 4118)


def test_snapshot_with_unknown_start_and_unknown_after():
    games = [sg(0, "defeat", after=4000), sg(1, "defeat"), sg(2, "victory", after=4020)]
    s = snapshot(games, mmr_start=None)
    assert s.mmr_delta is None and s.mmr_now == 4020 and s.mmr_points == ()
    s = snapshot(games, mmr_start=4010)
    assert s.mmr_points == (4010, 4000, 4020) and s.mmr_delta == 10


def test_snapshot_matchups_are_1v1_only_and_ignore_unknown():
    games = [
        sg(0, "victory", mode="2v2"),
        sg(1, "victory", race="RANDOM"),
        sg(2, None),
        SessionGame(1, "x", T0, T0, "1v1", "victory", opponents=()),
    ]
    s = snapshot(games, mmr_start=None)
    assert s.by_matchup == {"vR": Record(1, 0)}
    assert s.games == 4 and s.wins == 3 and s.losses == 0


def test_empty_snapshot():
    s = snapshot([], mmr_start=None, started_at=T0)
    assert s.games == 0 and s.started_at == T0 and s.mmr_delta is None and s.by_matchup == {}


# -------------------------------------------------------------------- store
@pytest.fixture
def store(tmp_path):
    db = init_db(tmp_path / "log.db")
    yield SessionStore(db)
    db.close()


def result(game_id: int, outcome: str | None = "victory", started: datetime = T0) -> GameResult:
    me = GamePlayer(id=1, name="Me", race="Zerg")
    opp = GamePlayer(id=2, name="Bob#1", race="Terran")
    ctx = GameContext(game_id, started, (me, opp), me, (), (opp,), "1v1", False)
    return GameResult(ctx, outcome, 612.0)  # type: ignore[arg-type]


def test_store_groups_games_and_rolls_over_after_three_hours(store):
    a = store.current_session(T0)
    store.add_game(result(1), {}, 4000, uid="u1", now=T0)
    store.add_game(result(2), {}, 4010, uid="u2", now=T0 + timedelta(hours=2, minutes=59))
    assert (
        store.current_session(T0 + timedelta(hours=5)).id == a.id
    )  # last game 2h01 earlier: same session
    assert [g.game_uid for g in store.games(a.id)] == ["u1", "u2"]

    late = T0 + timedelta(hours=2, minutes=59) + SESSION_GAP + timedelta(minutes=1)
    store.add_game(result(3), {}, 4020, uid="u3", now=late)
    sessions = {g.session_id for g in (*store.games(a.id), *store.games(a.id + 1))}
    assert sessions == {a.id, a.id + 1}
    assert [g.game_uid for g in store.games(a.id + 1)] == ["u3"]
    assert store.latest_session().id == a.id + 1


def test_store_gap_boundary_is_inclusive(store):
    store.add_game(result(1), {}, None, uid="a", now=T0)
    exactly = store.add_game(result(2), {}, None, uid="b", now=T0 + SESSION_GAP)
    over = store.add_game(
        result(3), {}, None, uid="c", now=T0 + 2 * SESSION_GAP + timedelta(seconds=1)
    )
    assert exactly.session_id == 1
    assert over.session_id == 2


def test_store_is_idempotent_and_updates_mmr_after(store):
    g1 = store.add_game(result(1), {}, 4000, uid="u1", now=T0)
    g2 = store.add_game(result(1), {}, 9999, uid="u1", now=T0)
    assert g1.id == g2.id and g2.mmr_before == 4000
    store.set_mmr_after("u1", 4018)
    (g,) = store.games(g1.session_id)
    assert g.mmr_after == 4018 and g.my_result == "victory" and g.game_seconds == 612
    assert g.opponents == (SessionOpponent("Bob", "TERRAN", None, None),)
    assert g.started_at == T0 and g.ended_at == T0


# ------------------------------------------------------------------ tracker
@pytest.fixture
def tracker(qtbot, store):
    bus = EventBus()
    clock = Clock()
    mmr = {201: 4000}
    t = SessionTracker(
        bus,
        store,
        FakePipeline(),
        mmr_for=lambda q: mmr.get(q),
        executor=Inline(),
        now=clock,
    )
    t.bus_ = bus  # type: ignore[attr-defined]
    t.clock = clock  # type: ignore[attr-defined]
    t.mmr = mmr  # type: ignore[attr-defined]
    return t


def play(tracker, game_id: int, outcome: str | None = "victory", minutes: int = 12) -> GameResult:
    r = result(game_id, outcome, started=tracker.clock.now)
    tracker.bus_.game_started.emit(r.context)
    tracker.clock.now += timedelta(minutes=minutes)
    tracker.bus_.game_ended.emit(r)
    return r


def test_tracker_counts_games_and_stores_them(qtbot, tracker, store):
    seen = []
    tracker.bus_.session_updated.connect(seen.append)
    play(tracker, 1, "victory")
    play(tracker, 2, "defeat")
    snap = tracker.current()
    assert (snap.games, snap.wins, snap.losses) == (2, 1, 1)
    assert snap.mmr_start == 4000 and snap.mmr_delta is None
    assert len(seen) == 2
    stored = store.games(store.latest_session().id)
    assert [g.my_result for g in stored] == ["victory", "defeat"]


def test_tracker_wires_mmr_refreshed_to_the_latest_game_of_that_queue(qtbot, tracker, store):
    play(tracker, 1)
    play(tracker, 2)
    tracker.mmr[201] = 4018
    tracker.on_mmr_refreshed(201, 4018)
    games = tracker.games()
    assert games[0].mmr_after is None and games[1].mmr_after == 4018
    assert tracker.current().mmr_delta == 18
    assert [g.mmr_after for g in store.games(store.latest_session().id)] == [None, 4018]
    tracker.on_mmr_refreshed(201, 4030)  # the latest game already has one: nothing to attach
    assert tracker.games()[1].mmr_after == 4018
    tracker.on_mmr_refreshed(202, 3000)  # other queue: ignored
    assert tracker.current().mmr_now == 4018


def test_tracker_ignores_ai_unknown_results_and_other_modes(qtbot, tracker):
    me = GamePlayer(id=1, name="Me", race="Zerg")
    ai = GamePlayer(id=2, name="A.I.", type="computer", race="Terran")
    ctx = GameContext(5, T0, (me, ai), me, (), (ai,), "other", True)
    tracker.bus_.game_ended.emit(GameResult(ctx, "victory", 300.0))
    tracker.bus_.game_ended.emit(result(6, None))
    assert tracker.current().games == 0


def test_tracker_session_rolls_over_after_three_hours(qtbot, tracker, store):
    play(tracker, 1)
    play(tracker, 2)
    assert tracker.current().games == 2
    tracker.clock.now += SESSION_GAP + timedelta(minutes=1)
    assert tracker.current().games == 0  # reads empty without a new game
    play(tracker, 3, "defeat")
    snap = tracker.current()
    assert (snap.games, snap.wins, snap.losses) == (1, 0, 1)
    assert len({g.session_id for g in store.games(1)} | {g.session_id for g in store.games(2)}) == 2


def test_tracker_resumes_a_recent_session_on_load(qtbot, tracker, store):
    play(tracker, 1)
    play(tracker, 2)
    fresh = SessionTracker(
        EventBus(),
        store,
        FakePipeline(),
        mmr_for=lambda q: None,
        executor=Inline(),
        now=tracker.clock,
    )
    fresh.load()
    assert fresh.current().games == 2
    tracker.clock.now += SESSION_GAP + timedelta(hours=1)
    stale = SessionTracker(
        EventBus(),
        store,
        FakePipeline(),
        mmr_for=lambda q: None,
        executor=Inline(),
        now=tracker.clock,
    )
    stale.load()
    assert stale.current().games == 0


def test_tracker_works_without_a_store(qtbot):
    t = SessionTracker(EventBus(), None, FakePipeline(), mmr_for=lambda q: None, now=Clock())
    t.on_game_ended(result(1))
    assert t.current().games == 1
    t.shutdown()


def test_migration_to_v3_keeps_existing_player_log_rows(tmp_path):
    from peewee import SqliteDatabase

    from smurfsniper.storage.db import migrate, schema_version
    from smurfsniper.storage.migrations import MIGRATIONS

    db = SqliteDatabase(str(tmp_path / "old.db"))
    for step in MIGRATIONS[:2]:  # a database as v2 left it
        step(db)
    db.execute_sql("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    db.execute_sql("INSERT INTO schema_version VALUES (2)")
    db.execute_sql(
        "INSERT INTO player_log (battlenet_id, name, realm, region, match_status, created_at) "
        "VALUES (1, 'Bob', 1, 'EU', 'victory', '2026-10-01 10:00:00')"
    )
    assert migrate(db) == 3 and schema_version(db) == 3
    assert db.execute_sql("SELECT COUNT(*) FROM player_log").fetchone()[0] == 1
    cols = {r[1] for r in db.execute_sql("PRAGMA table_info(session_game)")}
    assert {"game_uid", "mmr_before", "mmr_after", "opponents", "game_seconds"} <= cols
    assert {r[1] for r in db.execute_sql("PRAGMA table_info(session)")} == {
        "id",
        "started_at",
        "ended_at",
        "character_id",
    }
    db.close()
