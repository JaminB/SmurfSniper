"""Wires the SC2 poller -> event bus -> lookup pipeline -> legacy overlays.

Threads:
- main: Qt event loop, all widgets, this ``Service``.
- poller QThread: ``Sc2ClientPoller`` (local SC2 API).
- lookup executor: SC2Pulse / Aligulac / Liquipedia calls.
- writer executor: player log writes and cache pruning.
- keyboard hook thread: only emits signals.
"""

from __future__ import annotations

import signal
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QMetaObject, QObject, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtWidgets import QApplication

from smurfsniper import paths
from smurfsniper.api.registry import Clients, build_clients
from smurfsniper.core import matching
from smurfsniper.core.events import EventBus
from smurfsniper.core.game_state import GameContext, GameResult, Sc2ClientPoller
from smurfsniper.core.lookup import LookupPipeline
from smurfsniper.core.profile import Stage
from smurfsniper.logger import logger
from smurfsniper.models.config import Config
from smurfsniper.sounds import SoundPlayer
from smurfsniper.storage.db import init_db
from smurfsniper.storage.player_log import PlayerLogStore
from smurfsniper.ui.legacy_render import LegacyRenderer
from smurfsniper.ui.overlay_manager import close_all_overlays

MMR_WINDOW = 500


class Service(QObject):
    redetect_requested = Signal()
    intel_requested = Signal()

    def __init__(
        self,
        config: Config,
        clients: Clients,
        store: PlayerLogStore,
        bus: EventBus,
        *,
        hotkeys: bool = True,
        sounds: SoundPlayer | None = None,
    ):
        super().__init__()
        self.config = config
        self.clients = clients
        self.store = store
        self.bus = bus
        self.sounds = sounds or SoundPlayer()
        self._use_hotkeys = hotkeys
        self._hotkeys: list = []
        self._writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="writer")
        self.pipeline = LookupPipeline(
            clients,
            store,
            my_mmr=lambda: self.config.me.mmr,
            my_region=lambda: None,
            mmr_window=lambda: MMR_WINDOW,
        )
        self.renderer = LegacyRenderer(config, chime=self.sounds.play)
        self.poller: Sc2ClientPoller | None = None
        self._thread: QThread | None = None

    # --------------------------------------------------------------- lifecycle
    def start(self) -> None:
        self.poller = Sc2ClientPoller(
            self.clients.sc2,
            identify_me=lambda ps: matching.identify_me(ps, self.config.me.name),
            teammates=lambda: set(self.config.team.members),
        )
        self._thread = QThread()
        self._thread.setObjectName("sc2-poller")
        self.poller.moveToThread(self._thread)
        self._thread.started.connect(self.poller.start)

        self.poller.state_changed.connect(self.bus.state_changed)
        self.poller.game_started.connect(self.bus.game_started)
        self.poller.game_ended.connect(self.bus.game_ended)
        self.bus.game_started.connect(self._on_game_started)
        self.bus.game_ended.connect(self._on_game_ended)
        self.pipeline.update.connect(self.renderer.on_update)
        self.redetect_requested.connect(self.poller.force_redetect)
        self.redetect_requested.connect(self._on_redetect)
        self.intel_requested.connect(self._on_intel)

        if self.clients.cache.disk is not None:
            self._writer.submit(self._prune_cache)
        if self._use_hotkeys:
            self._register_hotkeys()
        self._thread.start()

    def stop(self) -> None:
        self._unregister_hotkeys()
        if self.poller is not None and self._thread is not None and self._thread.isRunning():
            QMetaObject.invokeMethod(
                self.poller, "stop", Qt.ConnectionType.BlockingQueuedConnection
            )
            self._thread.quit()
            self._thread.wait(3000)
        self.pipeline.shutdown()
        self._writer.shutdown(wait=True)
        self.sounds.stop()
        self.clients.close()

    # ------------------------------------------------------------------ slots
    @Slot(object)
    def _on_game_started(self, ctx: GameContext) -> None:
        names = ", ".join(p.name for p in ctx.opponents) or "nobody"
        logger.info(f"Game {ctx.game_id} started ({ctx.mode}) vs {names}")
        self.renderer.on_game_started(ctx)
        self.pipeline.start(ctx)

    @Slot(object)
    def _on_game_ended(self, result: GameResult) -> None:
        logger.info(f"Game {result.context.game_id} ended: {result.my_result or 'unknown'}")
        close_all_overlays()
        if result.context.vs_ai:
            return
        profiles = self.pipeline.results(result.context.game_id)
        self._writer.submit(self._record, result, profiles)

    @Slot()
    def _on_redetect(self) -> None:
        logger.info("Ctrl+F1: re-detecting the current game")
        self.sounds.play("one")

    @Slot()
    def _on_intel(self) -> None:
        self.sounds.play("one")
        gid = self.pipeline.game_id
        if gid is None:
            logger.info("Ctrl+F2: no current opponent to look up.")
            return
        self.renderer.request_intel()
        for slot in self.renderer.profiles:
            self.pipeline.ensure(gid, slot, Stage.INTEL)
            self.pipeline.ensure(gid, slot, Stage.TENDENCIES)

    # -------------------------------------------------------------- internals
    def _record(self, result: GameResult, profiles) -> None:
        try:
            self.store.record_game(result, profiles)
        except Exception as e:
            logger.opt(exception=True).warning(f"Could not log game: {e}")

    def _prune_cache(self) -> None:
        try:
            self.clients.cache.disk.prune()
        except Exception as e:
            logger.debug(f"cache prune failed: {e}")

    def _register_hotkeys(self) -> None:
        try:
            import keyboard
        except ImportError as e:
            logger.warning(f"Hotkeys unavailable: {e}")
            return
        # Callbacks run on the keyboard hook thread: emit a signal and nothing else.
        for combo, sig in (("ctrl+f1", self.redetect_requested), ("ctrl+f2", self.intel_requested)):
            try:
                self._hotkeys.append(keyboard.add_hotkey(combo, sig.emit, suppress=False))
            except Exception as e:  # no hook permission, unsupported platform
                logger.warning(f"Could not register {combo}: {e}")

    def _unregister_hotkeys(self) -> None:
        if not self._hotkeys:
            return
        try:
            import keyboard

            for h in self._hotkeys:
                keyboard.remove_hotkey(h)
        except Exception as e:
            logger.debug(f"unhook failed: {e}")
        self._hotkeys = []


def main(url: str, config: Config, app: QApplication | None = None) -> int:
    """Run the overlay service until the Qt app quits. Returns the exit code."""
    app = app or QApplication.instance() or QApplication([])
    paths.ensure_dirs()
    db = init_db(paths.db_path())
    store = PlayerLogStore(db)
    clients = build_clients(config, sc2_url=url)
    bus = EventBus()
    service = Service(config, clients, store, bus)
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    # Let the Python interpreter run periodically so Ctrl+C is handled.
    wake = QTimer()
    wake.timeout.connect(lambda: None)
    wake.start(500)
    service.start()
    try:
        return app.exec()
    finally:
        service.stop()
        db.close()
