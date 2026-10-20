"""Wires the SC2 poller -> event bus -> lookup pipeline (the HUD subscribes to both).

Hotkeys live in ``app.hotkeys``; ``SmurfSniperApp`` routes re-detect here and every
HUD hotkey to ``ui.hud.HudController`` (all on the main thread).

Threads:
- main: Qt event loop, all widgets, this ``Service``.
- poller QThread: ``Sc2ClientPoller`` (local SC2 API).
- lookup executor: SC2Pulse / Aligulac / Liquipedia calls.
- writer executor: player log writes and cache pruning.
- keyboard hook thread: only emits ``HotkeyManager.triggered``.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QMetaObject, QObject, Qt, QThread, Signal, Slot

from smurfsniper.api.registry import Clients
from smurfsniper.app.sounds import SoundPlayer
from smurfsniper.core import matching
from smurfsniper.core.account import AccountService
from smurfsniper.core.events import EventBus
from smurfsniper.core.game_state import GameContext, GameResult, GameState, Sc2ClientPoller
from smurfsniper.core.lookup import LookupPipeline
from smurfsniper.logger import logger
from smurfsniper.models.config import Config
from smurfsniper.storage.player_log import PlayerLogStore
from smurfsniper.textutil import RACE_LABEL


class Service(QObject):
    redetect_requested = Signal()
    state_text_changed = Signal(str)  # tray status line
    game_logged = Signal(object)  # GameResult, after its opponents reached the player log

    def __init__(
        self,
        config: Config,
        clients: Clients,
        store: PlayerLogStore,
        bus: EventBus,
        *,
        sounds: SoundPlayer | None = None,
        account: AccountService | None = None,
    ):
        super().__init__()
        self.config = config
        self.clients = clients
        self.store = store
        self.bus = bus
        self.account = account
        self.sounds = sounds or SoundPlayer(enabled=config.advanced.sounds_enabled)
        self.paused = False
        self._state: GameState | None = None
        self._ctx: GameContext | None = None
        self._writer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="writer")
        self.pipeline = LookupPipeline(
            clients,
            store,
            my_mmr=self._my_mmr,
            my_region=lambda: self.config.account.region,
            mmr_window=lambda: self.config.advanced.mmr_window,
        )
        self.poller: Sc2ClientPoller | None = None
        self._thread: QThread | None = None

    def _my_mmr(self) -> int | None:
        ctx = self.pipeline.context()
        queue = int(matching.queue_for(ctx.mode)) if ctx is not None else 201
        return self.config.account.mmr_for(queue)

    def _identify_me(self, players):
        if self.account is not None:
            return self.account.identify_me(players)
        return matching.identify_me(players, self.config.account.name)

    # --------------------------------------------------------------- lifecycle
    def start(self) -> None:
        self.poller = Sc2ClientPoller(
            self.clients.sc2,
            identify_me=self._identify_me,
            teammates=lambda: set(self.config.account.teammates),
            ui_interval_ms=self.config.advanced.ui_poll_ms,
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
        self.bus.state_changed.connect(self._on_state_changed)
        self.redetect_requested.connect(self.poller.force_redetect)

        if self.clients.cache.disk is not None:
            self._writer.submit(self._prune_cache)
        self._thread.start()

    def stop(self) -> None:
        if self.account is not None:
            self.account.stop()
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

    def set_clients(self, clients: Clients) -> None:
        """Swap in rebuilt API clients (settings changed). The old ones are closed."""
        old, self.clients = self.clients, clients
        self.pipeline.clients = clients
        if self.poller is not None:
            self.poller.client = clients.sc2
        if self.account is not None:
            self.account.clients = clients
        old.close(close_cache=False)

    # --------------------------------------------------------- public actions
    def request_redetect(self) -> None:
        logger.info("Re-detecting the current game")
        self.sounds.play("one")
        self.redetect_requested.emit()

    def set_paused(self, paused: bool) -> None:
        self.paused = paused
        if paused:
            self.pipeline.cancel()
        self._announce_state()

    # ------------------------------------------------------------------ slots
    @Slot(object)
    def _on_game_started(self, ctx: GameContext) -> None:
        names = ", ".join(p.name for p in ctx.opponents) or "nobody"
        logger.info(f"Game {ctx.game_id} started ({ctx.mode}) vs {names}")
        self._ctx = ctx
        if self.account is not None:
            self.account.observe_game(ctx)
        if self.paused:
            logger.info("Lookups paused: skipping this game")
        else:
            self.pipeline.start(ctx)
        self._announce_state()

    @Slot(object)
    def _on_game_ended(self, result: GameResult) -> None:
        logger.info(f"Game {result.context.game_id} ended: {result.my_result or 'unknown'}")
        if result.context.vs_ai:
            return
        if self.account is not None:
            self.account.refresh_mmr_after_game(result)
        profiles = self.pipeline.results(result.context.game_id)
        self._writer.submit(self._record, result, profiles)

    @Slot(object)
    def _on_state_changed(self, state: GameState) -> None:
        self._state = state
        if state is not GameState.IN_GAME:
            self._ctx = None
        self._announce_state()

    def state_text(self) -> str:
        """One-line status for the tray tooltip and menu."""
        if self.paused:
            return "Paused"
        state, ctx = self._state, self._ctx
        if state is GameState.IN_GAME and ctx is not None:
            if ctx.vs_ai:
                return "In game vs AI"
            if ctx.opponents:
                opp = ctx.opponents[0]
                race = RACE_LABEL.get(opp.race_code or "")
                more = f" +{len(ctx.opponents) - 1}" if len(ctx.opponents) > 1 else ""
                return f"In game vs {opp.name}{more}" + (f" ({race})" if race else "")
            return "In game"
        if state in (GameState.MENU, GameState.RESULT, GameState.LOADING):
            return "In menus"
        if state is GameState.REPLAY:
            return "Watching a replay"
        return "Waiting for SC2"

    def _announce_state(self) -> None:
        self.state_text_changed.emit(self.state_text())

    # -------------------------------------------------------------- internals
    def _record(self, result: GameResult, profiles) -> None:
        try:
            self.store.record_game(result, profiles)
        except Exception as e:
            logger.opt(exception=True).warning(f"Could not log game: {e}")
        self.game_logged.emit(result)  # from the writer thread: delivered queued

    def _prune_cache(self) -> None:
        try:
            self.clients.cache.disk.prune()
        except Exception as e:
            logger.debug(f"cache prune failed: {e}")
