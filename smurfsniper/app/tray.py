"""System tray icon and menu."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QObject, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from smurfsniper import paths
from smurfsniper._version import __version__
from smurfsniper.app.hotkeys import UNAVAILABLE_HINT, to_display
from smurfsniper.assets import asset_path
from smurfsniper.models.config import HotkeyConfig
from smurfsniper.ui.theme import stylesheet


class TrayController(QObject):
    """Owns the ``QSystemTrayIcon``; every action calls back into the app."""

    def __init__(
        self,
        *,
        hotkeys: HotkeyConfig,
        on_cheatsheet: Callable[[], None],
        on_settings: Callable[[], None],
        on_account: Callable[[], None],
        on_pause: Callable[[bool], None],
        on_hide: Callable[[bool], None],
        on_sounds: Callable[[bool], None],
        on_quit: Callable[[], None],
        sounds_enabled: bool = True,
    ):
        super().__init__()
        self._on_cheatsheet = on_cheatsheet
        self.icon = QSystemTrayIcon(QIcon(str(asset_path("tray.png"))))
        self.status_text = "Waiting for SC2"
        self.menu = QMenu()
        self.menu.setStyleSheet(stylesheet())

        self.title = QAction(f"SmurfSniper {__version__}")
        self.title.setEnabled(False)
        self.status = QAction(f"● {self.status_text}")
        self.status.setEnabled(False)
        self.warning = QAction(UNAVAILABLE_HINT)
        self.warning.setEnabled(False)
        self.warning.setVisible(False)
        self.menu.addAction(self.title)
        self.menu.addAction(self.status)
        self.menu.addAction(self.warning)
        self.menu.addSeparator()

        self.hotkeys_action = self.menu.addAction("Hotkeys…")
        self.hotkeys_action.triggered.connect(lambda: on_cheatsheet())
        self.settings_action = self.menu.addAction("Settings…")
        self.settings_action.triggered.connect(lambda: on_settings())
        self.account_action = self.menu.addAction("Change account…")
        self.account_action.triggered.connect(lambda: on_account())
        self.menu.addSeparator()

        self.pause_action = self.menu.addAction("Pause lookups")
        self.pause_action.setCheckable(True)
        self.pause_action.toggled.connect(on_pause)
        self.hide_action = self.menu.addAction("Hide HUD")
        self.hide_action.setCheckable(True)
        self.hide_action.toggled.connect(on_hide)
        self.sounds_action = self.menu.addAction("Sounds")
        self.sounds_action.setCheckable(True)
        self.sounds_action.setChecked(sounds_enabled)
        self.sounds_action.toggled.connect(on_sounds)
        self.menu.addSeparator()

        self.logs_action = self.menu.addAction("Open logs folder")
        self.logs_action.triggered.connect(lambda: self._open(paths.log_dir()))
        self.data_action = self.menu.addAction("Open data folder")
        self.data_action.triggered.connect(lambda: self._open(paths.data_dir()))
        self.menu.addSeparator()
        self.quit_action = self.menu.addAction("Quit")
        self.quit_action.triggered.connect(lambda: on_quit())

        self.icon.setContextMenu(self.menu)
        self.icon.activated.connect(self._on_activated)
        self._on_message_click: Callable[[], None] | None = None
        self.icon.messageClicked.connect(self._message_clicked)
        self.set_hotkeys(hotkeys)
        self.set_status(self.status_text)

    # --------------------------------------------------------------------- api
    @property
    def available(self) -> bool:
        return QSystemTrayIcon.isSystemTrayAvailable()

    def show(self) -> None:
        self.icon.show()

    def hide(self) -> None:
        self.icon.hide()

    def set_status(self, text: str) -> None:
        self.status_text = text
        self.status.setText(f"● {text}")
        self.icon.setToolTip(f"SmurfSniper {__version__} - {text}")

    def set_hotkeys(self, hotkeys: HotkeyConfig) -> None:
        """Show the hide-all binding next to the menu entry."""
        self.hide_action.setText(f"Hide HUD\t{to_display(hotkeys.hide_all)}")

    def set_hud_hidden(self, hidden: bool) -> None:
        if self.hide_action.isChecked() != hidden:
            self.hide_action.blockSignals(True)
            self.hide_action.setChecked(hidden)
            self.hide_action.blockSignals(False)

    def set_hotkeys_unavailable(self, unavailable: bool) -> None:
        self.warning.setVisible(unavailable)

    def message(self, title: str, text: str, on_click: Callable[[], None] | None = None) -> None:
        # Each balloon gets its own click handler; a click never runs a stale action.
        self._on_message_click = on_click
        self.icon.showMessage(title, text, QSystemTrayIcon.MessageIcon.NoIcon, 8000)

    def _message_clicked(self) -> None:
        if self._on_message_click is not None:
            self._on_message_click()

    def menu_labels(self) -> list[str]:
        return [a.text() for a in self.menu.actions() if not a.isSeparator()]

    # --------------------------------------------------------------- internals
    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._on_cheatsheet()

    @staticmethod
    def _open(path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
