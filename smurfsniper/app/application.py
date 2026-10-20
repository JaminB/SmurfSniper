"""``SmurfSniperApp``: owns the QApplication, services, tray and hotkeys."""

from __future__ import annotations

import json
import signal
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from PySide6.QtCore import QCoreApplication, QEvent, QLockFile, QObject, QTimer, QUrl, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from smurfsniper import paths
from smurfsniper._version import __version__
from smurfsniper.api.registry import Clients, build_clients, validate_aligulac_key
from smurfsniper.app.hotkeys import HotkeyAction, HotkeyManager, to_display
from smurfsniper.app.sounds import SoundPlayer
from smurfsniper.app.tray import TrayController
from smurfsniper.assets import asset_path
from smurfsniper.core.account import AccountCandidate, AccountService
from smurfsniper.core.events import EventBus
from smurfsniper.logger import logger, setup_logging
from smurfsniper.models.config import Config, save_config
from smurfsniper.service import Service
from smurfsniper.storage.db import init_db
from smurfsniper.storage.player_log import PlayerLogStore
from smurfsniper.ui.account_picker import AccountPickerDialog
from smurfsniper.ui.cheatsheet import HotkeyCheatSheet
from smurfsniper.ui.hud import HudController
from smurfsniper.ui.settings import SettingsHooks, SettingsWindow

SAVE_DEBOUNCE_MS = 500
REBUILD_DEBOUNCE_MS = 1000  # typing an API key must not rebuild clients per keystroke
_IDENTITY_FIELDS = (
    "character_id",
    "toon_handle",
    "name",
    "region",
    "mmr_by_queue",
    "mmr_updated_at",
)


def load_state() -> dict[str, Any]:
    try:
        return json.loads(paths.state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict[str, Any]) -> None:
    try:
        p = paths.state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(state), encoding="utf-8")
    except OSError as e:
        logger.debug(f"could not save state: {e}")


class SmurfSniperApp(QObject):
    def __init__(
        self,
        config: Config,
        config_path: Path,
        *,
        headless: bool = False,
        tray: bool = True,
    ):
        super().__init__()
        self.config = config
        self.config_path = Path(config_path)
        self.headless = headless
        self.use_tray = tray and not headless
        self.qapp: QApplication | None = None
        self.bus = EventBus()
        self.clients: Clients | None = None
        self.service: Service | None = None
        self.account: AccountService | None = None
        self.hotkeys: HotkeyManager | None = None
        self.tray: TrayController | None = None
        self.settings: SettingsWindow | None = None
        self.picker: AccountPickerDialog | None = None
        self.cheatsheet: HotkeyCheatSheet | None = None
        self.hud: HudController | None = None
        self._db = None
        self._executor: ThreadPoolExecutor | None = None
        self._lock: QLockFile | None = None
        self._dirty = False
        self._state = load_state() if not headless else {}
        self._wake: QTimer | None = None
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DEBOUNCE_MS)
        self._save_timer.timeout.connect(self.save_now)
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(REBUILD_DEBOUNCE_MS)
        self._rebuild_timer.timeout.connect(self._rebuild_clients)

    # --------------------------------------------------------------- lifecycle
    def run(self) -> int:
        """Run until quit. Returns 1 if another instance holds the lock."""
        app = QApplication.instance() or QApplication(sys.argv[:1])
        assert isinstance(app, QApplication)
        self.qapp = app
        app.setApplicationName("SmurfSniper")
        app.setQuitOnLastWindowClosed(False)
        app.setWindowIcon(QIcon(str(asset_path("logo.ico"))))
        if not self.acquire_lock():
            if not self.headless:
                QMessageBox.information(
                    None,
                    "SmurfSniper",
                    "SmurfSniper is already running. Look for its icon in the system tray.",
                )
            logger.warning("Another SmurfSniper instance is already running; exiting.")
            return 1
        try:
            self.start()
            return app.exec()
        finally:
            self.shutdown()

    def acquire_lock(self) -> bool:
        lock = QLockFile(str(paths.lock_path()))
        lock.setStaleLockTime(0)
        if not lock.tryLock(100):
            return False
        self._lock = lock
        return True

    def start(self) -> None:
        """Build every component and start polling (no event loop is run here)."""
        app = self.qapp or QApplication.instance()
        paths.ensure_dirs()
        cfg = self.config
        self._db = init_db(paths.db_path())
        store = PlayerLogStore(self._db)
        self.clients = build_clients(cfg, disk_cache=cfg.advanced.disk_cache)
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="account")
        sounds = SoundPlayer(enabled=cfg.advanced.sounds_enabled)
        self.account = AccountService(cfg, self.clients, self._executor, self.schedule_save)
        self.service = Service(
            cfg, self.clients, store, self.bus, sounds=sounds, account=self.account
        )
        # Created before Service.start() so the HUD sees game_started before lookups run.
        self.hud = HudController(self.bus, self.service.pipeline, cfg, chime=sounds.play)
        self.hotkeys = HotkeyManager(cfg.hotkeys)
        self.hotkeys.triggered.connect(self._on_hotkey)

        self.account.candidates_ready.connect(self._on_candidates)
        self.account.account_changed.connect(self._on_account_changed)
        self.account.mmr_refreshed.connect(self._on_mmr_refreshed)
        self.account.needs_picker.connect(self._on_needs_picker)
        self.service.state_text_changed.connect(self._on_state_text)
        self.hud.hidden_changed.connect(self._on_hidden_changed)
        self.hud.links_changed.connect(self._on_links_changed)

        if self.use_tray:
            self._build_tray()
        if not self.headless:
            issues = self.hotkeys.start()
            errors = [i for i in issues if i.level == "error"]
            for i in errors:
                logger.warning(f"Hotkey {i.action.value}: {i.message}")
            if self.tray is not None:
                self.tray.set_hotkeys_unavailable(self.hotkeys.unavailable)

        self.service.start()
        if app is not None:
            signal.signal(signal.SIGINT, lambda *_: app.quit())
            self._wake = QTimer(self)  # let Python handle Ctrl+C while Qt runs
            self._wake.timeout.connect(lambda: None)
            self._wake.start(500)
        if not self.headless:
            QTimer.singleShot(0, self._first_run)

    def shutdown(self) -> None:
        # Idempotent: the widgets deleted at the end must not be touched again.
        if getattr(self, "_shut_down", False):
            return
        self._shut_down = True
        if self._wake is not None:
            self._wake.stop()
        if self.hotkeys is not None:
            self.hotkeys.stop()
        if self.hud is not None:
            self.hud.dismiss_all()
        if self.tray is not None:
            self.tray.hide()
        if self._save_timer.isActive():
            self._save_timer.stop()
        self._rebuild_timer.stop()
        self.save_now()
        if self.service is not None:
            self.service.stop()
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
        if self._db is not None:
            self._db.close()
        if self._lock is not None:
            self._lock.unlock()
            self._lock = None
        # Delete overlays while the QApplication still exists; leaving them to
        # interpreter finalization can crash the process on exit.
        qapp = QApplication.instance()
        if qapp is not None:
            # Deliver signals already queued (e.g. the final state change) while the
            # widgets are alive, then stop the bus reaching the HUD.
            qapp.processEvents()
            self.bus.blockSignals(True)
            for w in QApplication.topLevelWidgets():
                w.close()
                w.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    # ------------------------------------------------------------------ config
    def schedule_save(self) -> None:
        """Debounced save (main thread)."""
        self._dirty = True
        self._save_timer.start()

    def save_now(self) -> None:
        if not self._dirty:
            return
        try:
            save_config(self.config, self.config_path)
            self._dirty = False
        except OSError as e:
            logger.warning(f"Could not save config to {self.config_path}: {e}")

    def apply_config(self, new: Config) -> None:
        """Apply a config coming from Settings: diff, update services, schedule a save."""
        old = self.config
        for name in _IDENTITY_FIELDS:  # the app owns identity and auto-refreshed MMR
            setattr(new.account, name, getattr(old.account, name))
        before = old.model_dump()
        old.replace_with(new)
        after = old.model_dump()

        def changed(*keys: str) -> bool:
            return any(before[k] != after[k] for k in keys)

        if changed("hotkeys") and self.hotkeys is not None:
            issues = self.hotkeys.apply(old.hotkeys)
            if self.tray is not None:
                self.tray.set_hotkeys(old.hotkeys)
                self.tray.set_hotkeys_unavailable(self.hotkeys.unavailable)
            if self.cheatsheet is not None:
                self.cheatsheet.set_hotkeys(old.hotkeys)
            for i in issues:
                if i.level == "error":
                    logger.warning(f"Hotkey {i.action.value}: {i.message}")
        if (
            before["integrations"] != after["integrations"]
            or before["advanced"]["sc2_client_url"] != after["advanced"]["sc2_client_url"]
        ):
            self._rebuild_timer.start()
        if self.service is not None:
            self.service.sounds.enabled = old.advanced.sounds_enabled
            if self.service.poller is not None:
                self.service.poller.ui_interval_ms = old.advanced.ui_poll_ms
        if before["advanced"]["log_level"] != after["advanced"]["log_level"]:
            setup_logging(old.advanced.log_level, console=True)
        if self.tray is not None:
            self.tray.sounds_action.blockSignals(True)
            self.tray.sounds_action.setChecked(old.advanced.sounds_enabled)
            self.tray.sounds_action.blockSignals(False)
        if changed("overlays"):
            self.bus.config_changed.emit(old)
        self.schedule_save()

    def _rebuild_clients(self) -> None:
        self._rebuild_timer.stop()
        if self.service is None or self.clients is None:
            return
        logger.info("Rebuilding API clients after a settings change")
        new = build_clients(self.config, cache=self.clients.cache)
        self.clients = new
        self.service.set_clients(new)

    # ------------------------------------------------------------------ hotkeys
    @Slot(str)
    def _on_hotkey(self, action: str) -> None:
        self.handle_hotkey(HotkeyAction(action))

    def handle_hotkey(self, action: HotkeyAction) -> None:
        if action is HotkeyAction.REDETECT:
            if self.service is not None:
                self.service.request_redetect()
        elif self.hud is not None:
            self.hud.on_hotkey(action.value)

    # --------------------------------------------------------------------- tray
    def _build_tray(self) -> None:
        cfg = self.config
        self.tray = TrayController(
            hotkeys=cfg.hotkeys,
            on_cheatsheet=self.show_cheatsheet,
            on_settings=self.show_settings,
            on_account=self.show_picker,
            on_pause=self._on_pause,
            on_hide=self._on_hide,
            on_sounds=self._on_sounds,
            on_quit=self.quit,
            sounds_enabled=cfg.advanced.sounds_enabled,
        )
        self.tray.show()

    def quit(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _on_pause(self, paused: bool) -> None:
        if self.service is not None:
            self.service.set_paused(paused)
        if paused and self.hud is not None:
            self.hud.dismiss_all()

    def _on_hide(self, hidden: bool) -> None:
        if self.hud is not None:
            self.hud.set_hidden(hidden)

    def _on_sounds(self, on: bool) -> None:
        self.config.advanced.sounds_enabled = on
        if self.service is not None:
            self.service.sounds.enabled = on
        if self.settings is not None:
            self.settings.set_config(self.config)
        self.schedule_save()

    @Slot(str)
    def _on_state_text(self, text: str) -> None:
        if self.tray is not None:
            self.tray.set_status(text)

    @Slot(bool)
    def _on_hidden_changed(self, hidden: bool) -> None:
        if self.tray is not None:
            self.tray.set_hud_hidden(hidden)

    @Slot(list)
    def _on_links_changed(self, links: list) -> None:
        if self.tray is not None:
            self.tray.set_links(links)

    # ------------------------------------------------------------------ dialogs
    def show_cheatsheet(self) -> None:
        if self.cheatsheet is None:
            self.cheatsheet = HotkeyCheatSheet(self.config.hotkeys)
            self.cheatsheet.edit_requested.connect(lambda: self.show_settings("Hotkeys"))
        self.cheatsheet.set_hotkeys(self.config.hotkeys)
        self._place_near_tray(self.cheatsheet)
        self.cheatsheet.show()
        self.cheatsheet.raise_()
        self.cheatsheet.activateWindow()

    def _place_near_tray(self, widget) -> None:
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return
        g = screen.availableGeometry()
        widget.move(g.right() - widget.width() - 8, g.bottom() - widget.height() - 8)

    def show_settings(self, tab: str | None = None) -> None:
        if self.settings is None:
            self.settings = SettingsWindow(self.config, self._settings_hooks())
            self.settings.changed.connect(self.apply_config)
        else:
            self.settings.set_config(self.config)
        if tab:
            self.settings.show_tab(tab)
        self.settings.show()
        self.settings.raise_()
        self.settings.activateWindow()

    def _settings_hooks(self) -> SettingsHooks:
        return SettingsHooks(
            change_account=self.show_picker,
            refresh_mmr=lambda: self.account.refresh_mmr_now() if self.account else None,
            test_aligulac=validate_aligulac_key,
            cache_stats=self._cache_stats,
            clear_cache=lambda: self.clients.cache.clear() if self.clients else None,
            open_path=self._open_path,
            preview=self._preview,
            suspend_hotkeys=lambda: self.hotkeys.suspend() if self.hotkeys else None,
            resume_hotkeys=lambda: self.hotkeys.resume() if self.hotkeys else None,
            version=__version__,
        )

    def _preview(self, config: Config) -> None:
        if self.hud is not None:
            self.hud.preview(config)

    def _cache_stats(self) -> tuple[int, int] | None:
        disk = self.clients.cache.disk if self.clients else None
        return disk.stats() if disk is not None else None

    def _open_path(self, which: str) -> None:
        target = {
            "config": self.config_path,
            "logs": paths.log_dir(),
            "data": paths.data_dir(),
        }[which]
        if which == "config" and not target.exists():
            self._dirty = True
            self.save_now()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target)))

    def show_picker(self, initial: str = "") -> None:
        if self.picker is None:
            self.picker = AccountPickerDialog(initial or self.config.account.name or "")
            self.picker.search_requested.connect(self._on_search)
            self.picker.chosen.connect(self._on_chosen)
            self.picker.detect_requested.connect(self._on_detect_requested)
            self.picker.finished.connect(self._on_picker_closed)
        self.picker.show()
        self.picker.raise_()
        self.picker.activateWindow()

    @Slot(str)
    def _on_search(self, query: str) -> None:
        if self.account is not None:
            self.account.search(query)

    @Slot(object)
    def _on_chosen(self, cand: AccountCandidate) -> None:
        if self.account is not None:
            self.account.choose(cand)

    @Slot()
    def _on_detect_requested(self) -> None:
        self._state["picker_skipped"] = True
        save_state(self._state)

    @Slot(int)
    def _on_picker_closed(self, _result: int) -> None:
        if self.picker is not None:
            self.picker.deleteLater()
            self.picker = None

    @Slot(str, list)
    def _on_candidates(self, query: str, cands: list) -> None:
        if self.picker is not None:
            self.picker.set_results(query, cands)

    @Slot(object)
    def _on_account_changed(self, _acct) -> None:
        if self.settings is not None:
            self.settings.refresh_account(self.config)

    @Slot(int, int)
    def _on_mmr_refreshed(self, queue: int, rating: int) -> None:
        logger.info(f"MMR for queue {queue} is now {rating}")
        if self.settings is not None:
            self.settings.refresh_account(self.config)

    @Slot(list)
    def _on_needs_picker(self, names: list) -> None:
        if self.tray is None or self.config.account.character_id is not None:
            return
        who = " or ".join(names[:2])
        self.tray.message(
            "Which account is yours?",
            f"SmurfSniper could not tell if you are {who}. Click here to choose.",
            on_click=lambda: self.show_picker(names[0] if names else ""),
        )

    # ---------------------------------------------------------------- first run
    def _first_run(self) -> None:
        if not self._state.get("first_run_done") and self.tray is not None:
            hide = to_display(self.config.hotkeys.hide_all)
            self.tray.message(
                "SmurfSniper",
                f"SmurfSniper is running in the tray. {hide} hides the HUD.",
            )
            self._state["first_run_done"] = True
            save_state(self._state)
        if self.tray is not None and not self.tray.available:
            self.show_settings()  # no tray here: Settings is the only way in
        if self.config.account.character_id is None and not self._state.get("picker_skipped"):
            self.show_picker()
