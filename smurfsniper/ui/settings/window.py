"""The Settings window: left navigation, instant-apply pages, no Save button."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from smurfsniper.assets import asset_path
from smurfsniper.models.config import Config
from smurfsniper.ui.settings.tab_account import AccountTab
from smurfsniper.ui.settings.tab_advanced import AdvancedTab
from smurfsniper.ui.settings.tab_hotkeys import HotkeysTab
from smurfsniper.ui.settings.tab_integrations import IntegrationsTab
from smurfsniper.ui.settings.tab_overlays import OverlaysTab
from smurfsniper.ui.settings.widgets import SettingsHooks, SettingsTab, button, label
from smurfsniper.ui.theme import stylesheet

TABS = (AccountTab, OverlaysTab, HotkeysTab, IntegrationsTab, AdvancedTab)


class SettingsWindow(QWidget):
    """Edits a private copy of the config; every change emits ``changed(Config)``."""

    changed = Signal(object)

    def __init__(self, config: Config, hooks: SettingsHooks | None = None):
        super().__init__()
        self.hooks = hooks or SettingsHooks()
        self.config = config.model_copy(deep=True)
        self.setObjectName("settings")
        self.setWindowTitle("SmurfSniper Settings")
        self.setWindowIcon(QIcon(str(asset_path("logo.ico"))))
        self.resize(720, 560)
        self.setMinimumSize(640, 480)
        self.setStyleSheet(stylesheet())

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setFixedWidth(160)
        outer.addWidget(self.nav)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        self.stack = QStackedWidget()
        right.addWidget(self.stack, 1)
        foot = QHBoxLayout()
        foot.setContentsMargins(20, 8, 20, 12)
        self.reset_btn = button("Reset tab to defaults", flat=True)
        foot.addWidget(self.reset_btn)
        foot.addStretch(1)
        foot.addWidget(label("Changes apply instantly", "muted"))
        right.addLayout(foot)
        outer.addLayout(right, 1)

        self.tabs: list[SettingsTab] = []
        for cls in TABS:
            tab = cls(self.config, self.hooks)
            tab.changed.connect(self._on_changed)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(tab)
            scroll.viewport().setAutoFillBackground(False)
            tab.setAutoFillBackground(False)
            self.tabs.append(tab)
            self.stack.addWidget(scroll)
            self.nav.addItem(cls.title)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.reset_btn.clicked.connect(self._reset_current)
        self.nav.setCurrentRow(0)

    # --------------------------------------------------------------------- api
    def tab(self, name: str) -> SettingsTab:
        for t in self.tabs:
            if t.title.lower() == name.lower():
                return t
        raise KeyError(name)

    def show_tab(self, name: str) -> None:
        self.nav.setCurrentRow(self.tabs.index(self.tab(name)))

    def set_config(self, config: Config) -> None:
        """Reload every page from ``config`` (the app changed something underneath us)."""
        self.config = config.model_copy(deep=True)
        for t in self.tabs:
            t.set_config(self.config)

    def refresh_account(self, config: Config) -> None:
        """Only the Account page: the app picked or refreshed the account."""
        self.config.account = config.account.model_copy(deep=True)
        self.tab("Account").set_config(self.config)

    # ---------------------------------------------------------------- handlers
    def _on_changed(self) -> None:
        self.changed.emit(self.config.model_copy(deep=True))

    def _reset_current(self) -> None:
        self.tabs[self.stack.currentIndex()].reset_defaults()
