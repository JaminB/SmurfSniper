"""Rivals panel data: the opponent log reduced to a ``RivalsSummary``, cached in memory.

``refresh()`` reads the log on a worker (local SQLite only, never the network) and emits
``ready``. The cache is dropped when a game ends or its opponents have been logged.
"""

from __future__ import annotations

from concurrent.futures import Executor, ThreadPoolExecutor

from PySide6.QtCore import QObject, Signal, Slot

from smurfsniper.analyze.rivals import RivalsSummary, rivals
from smurfsniper.core.events import EventBus
from smurfsniper.logger import logger
from smurfsniper.storage.player_log import PlayerLogStore


class RivalsCache(QObject):
    ready = Signal(object)  # RivalsSummary
    _loaded = Signal(int, object)  # generation, RivalsSummary

    def __init__(
        self,
        store: PlayerLogStore | None,
        bus: EventBus | None = None,
        *,
        executor: Executor | None = None,
    ):
        super().__init__()
        self.store = store
        self._executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="rivals")
        self._own_executor = executor is None
        self._summary: RivalsSummary | None = None
        self._generation = 0
        self._inflight = False
        self._loaded.connect(self._on_loaded)
        if bus is not None:
            bus.game_ended.connect(self.invalidate)

    def invalidate(self, *_: object) -> None:
        self._generation += 1
        self._summary = None
        self._inflight = False

    def summary(self) -> RivalsSummary | None:
        """The cached summary, or None until ``refresh`` has delivered one."""
        return self._summary

    def refresh(self) -> None:
        if self._summary is not None or self._inflight:
            return
        self._inflight = True
        gen = self._generation
        try:
            self._executor.submit(self._job, gen)
        except RuntimeError:
            self._inflight = False

    def _job(self, gen: int) -> None:
        summary = RivalsSummary()
        if self.store is not None:
            try:
                summary = rivals(self.store.all_rows())
            except Exception as e:
                logger.warning(f"Could not read the opponent log: {e}")
        self._loaded.emit(gen, summary)

    @Slot(int, object)
    def _on_loaded(self, gen: int, summary: RivalsSummary) -> None:
        if gen != self._generation:
            return
        self._inflight = False
        self._summary = summary
        self.ready.emit(summary)

    def shutdown(self) -> None:
        if self._own_executor and isinstance(self._executor, ThreadPoolExecutor):
            self._executor.shutdown(wait=False, cancel_futures=True)
