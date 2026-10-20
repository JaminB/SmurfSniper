"""Session tracker: logs every finished ladder game and keeps the live snapshot.

The in-memory list is the source for the UI and updates synchronously on the main
thread when a game ends (the recap toast needs it at once). The SQLite copy is written
by a single worker, so the session survives a restart.

Signals are emitted on the main thread; the bus carries ``session_updated``.
"""

from __future__ import annotations

import contextlib
import dataclasses
from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from datetime import UTC, datetime

from PySide6.QtCore import QObject, Signal, Slot

from smurfsniper.analyze.session import SessionSnapshot, snapshot
from smurfsniper.core import matching
from smurfsniper.core.events import EventBus
from smurfsniper.core.game_state import GameContext, GameResult
from smurfsniper.core.lookup import LookupPipeline
from smurfsniper.logger import logger
from smurfsniper.storage.player_log import game_uid
from smurfsniper.storage.rows import SessionGame
from smurfsniper.storage.session_store import SESSION_GAP, SessionStore, opponents_of

LADDER_MODES = ("1v1", "2v2", "3v3", "4v4")


class SessionTracker(QObject):
    game_added = Signal(object, object, object)  # SessionGame, GameResult, {slot: profile}
    changed = Signal(object)  # SessionSnapshot

    def __init__(
        self,
        bus: EventBus,
        store: SessionStore | None,
        pipeline: LookupPipeline,
        *,
        mmr_for: Callable[[int], int | None],
        character_id: Callable[[], int | None] = lambda: None,
        executor: Executor | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        super().__init__()
        self.bus = bus
        self.store = store
        self.pipeline = pipeline
        self._mmr_for = mmr_for
        self._character_id = character_id
        self._now = now
        self._executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="session")
        self._own_executor = executor is None
        self._games: list[SessionGame] = []
        self._started_at: datetime | None = None
        self._mmr_before: dict[int, int | None] = {}
        bus.game_started.connect(self.on_game_started)
        bus.game_ended.connect(self.on_game_ended)

    # ------------------------------------------------------------------ state
    def load(self) -> None:
        """Resume the stored session if its last game is under 3 h old (startup)."""
        if self.store is None:
            return
        try:
            latest = self.store.latest_session()
            if latest is None or latest.ended_at is not None:
                return
            games = self.store.games(latest.id)
        except Exception as e:
            logger.warning(f"Could not load the session: {e}")
            return
        last = games[-1].ended_at if games else latest.started_at
        if self._now() - last > SESSION_GAP:
            return
        self._games = games
        self._started_at = latest.started_at
        self._publish()

    def games(self) -> list[SessionGame]:
        return list(self._games)

    def current(self) -> SessionSnapshot:
        """The live snapshot; a session whose last game is over 3 h old reads as empty."""
        self._rollover(self._now())
        games = self._games
        start = next((g.mmr_before for g in games if g.mmr_before), None)
        return snapshot(games, mmr_start=start, started_at=self._started_at)

    def _rollover(self, now: datetime) -> None:
        if self._games and now - self._games[-1].ended_at > SESSION_GAP:
            self._games = []
            self._started_at = None

    def _publish(self) -> None:
        snap = self.current()
        self.changed.emit(snap)
        self.bus.session_updated.emit(snap)

    # ------------------------------------------------------------------ slots
    @Slot(object)
    def on_game_started(self, ctx: GameContext) -> None:
        queue = int(matching.queue_for(ctx.mode))
        self._mmr_before[ctx.game_id] = self._mmr_for(queue)
        for old in [g for g in self._mmr_before if g < ctx.game_id - 3]:
            del self._mmr_before[old]

    @Slot(object)
    def on_game_ended(self, result: GameResult) -> None:
        ctx = result.context
        if ctx.vs_ai or ctx.mode not in LADDER_MODES:
            return
        if result.my_result is None:
            logger.info(f"Game {ctx.game_id}: result unknown, not added to the session")
            return
        now = self._now()
        self._rollover(now)
        queue = int(matching.queue_for(ctx.mode))
        before = self._mmr_before.pop(ctx.game_id, None)
        if before is None:
            before = self._mmr_for(queue)
        profiles = self.pipeline.results(ctx.game_id)
        uid = game_uid(result)
        game = SessionGame(
            session_id=0,
            game_uid=uid,
            started_at=ctx.started_at,
            ended_at=now,
            mode=ctx.mode,
            my_result=result.my_result,
            my_race=ctx.me.race_code if ctx.me else None,
            opponents=opponents_of(result, profiles),
            mmr_before=before,
            game_seconds=int(result.display_time) if result.display_time else None,
        )
        if any(g.game_uid == uid for g in self._games):
            return
        if not self._games:
            self._started_at = ctx.started_at
        self._games.append(game)
        self._persist(result, profiles, before, uid, now)
        self.game_added.emit(game, result, profiles)
        self._publish()

    @Slot(int, int)
    def on_mmr_refreshed(self, queue: int, rating: int) -> None:
        """Attach the new rating to the latest game of that queue that has none."""
        for i in range(len(self._games) - 1, -1, -1):
            g = self._games[i]
            if int(matching.queue_for(g.mode)) != queue:
                continue
            if g.mmr_after is not None:
                return
            self._games[i] = dataclasses.replace(g, mmr_after=rating)
            self._persist_mmr(g.game_uid, rating)
            self._publish()
            return

    # ---------------------------------------------------------------- storage
    def _persist(self, result, profiles, before, uid, now) -> None:
        if self.store is None:
            return
        self._submit(self._write_game, result, profiles, before, uid, now)

    def _persist_mmr(self, uid: str, rating: int) -> None:
        if self.store is None:
            return
        self._submit(self._write_mmr, uid, rating)

    def _submit(self, fn, *args) -> None:
        with contextlib.suppress(RuntimeError):  # executor shut down
            self._executor.submit(fn, *args)

    def _write_game(self, result, profiles, before, uid, now) -> None:
        try:
            self.store.add_game(
                result,
                profiles,
                before,
                uid=uid,
                now=now,
                character_id=self._character_id(),
            )
        except Exception as e:
            logger.opt(exception=True).warning(f"Could not store the session game: {e}")

    def _write_mmr(self, uid: str, rating: int) -> None:
        try:
            self.store.set_mmr_after(uid, rating)
        except Exception as e:
            logger.warning(f"Could not store the post-game rating: {e}")

    def shutdown(self) -> None:
        if self._own_executor and isinstance(self._executor, ThreadPoolExecutor):
            self._executor.shutdown(wait=True)
