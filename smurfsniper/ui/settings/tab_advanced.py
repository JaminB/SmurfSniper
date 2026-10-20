"""Settings > Advanced."""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLineEdit, QSpinBox, QWidget

from smurfsniper.models.config import AdvancedConfig, Config
from smurfsniper.ui.settings.widgets import (
    SettingsHooks,
    SettingsTab,
    ToggleSwitch,
    button,
    form_row,
    label,
)

RELEASES_URL = "https://github.com/JaminB/SmurfSniper/releases"
LOG_LEVELS = ("DEBUG", "INFO", "WARNING")


def format_bytes(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} MB"
    return f"{max(1, n // 1024) if n else 0} KB"


class AdvancedTab(SettingsTab):
    title = "Advanced"

    def __init__(self, config: Config, hooks: SettingsHooks):
        super().__init__(config, hooks)
        self.heading("Advanced")

        self.url = QLineEdit()
        self.url.setMinimumWidth(220)
        self.poll = QSpinBox()
        self.poll.setRange(500, 10000)
        self.poll.setSingleStep(100)
        self.poll.setSuffix(" ms")
        self.window = QSpinBox()
        self.window.setRange(100, 2000)
        self.window.setSingleStep(50)
        self.window.setSuffix(" MMR")
        self.sounds = ToggleSwitch(True)
        self.level = QComboBox()
        self.level.addItems(LOG_LEVELS)
        self.disk_cache = ToggleSwitch(True)

        self.root.addWidget(form_row("SC2 client URL", self.url, "Where SC2 serves its local API."))
        self.root.addWidget(form_row("UI poll interval", self.poll))
        self.root.addWidget(
            form_row("MMR match window", self.window, "How far from your MMR a candidate may be.")
        )
        self.root.addWidget(form_row("Sounds", self.sounds, "Short chimes for new games."))
        self.root.addWidget(form_row("Log level", self.level))
        self.root.addWidget(
            form_row(
                "Disk cache", self.disk_cache, "Remember lookups between runs. Restart to apply."
            )
        )

        cache_row = QWidget()
        lay = QHBoxLayout(cache_row)
        lay.setContentsMargins(0, 0, 0, 0)
        self.cache_label = label("", "muted")
        self.clear_btn = button("Clear cache")
        lay.addWidget(self.cache_label, 1)
        lay.addWidget(self.clear_btn)
        self.root.addWidget(cache_row)

        files = QHBoxLayout()
        self.open_config = button("Open config file")
        self.open_logs = button("Open logs folder")
        files.addWidget(self.open_config)
        files.addWidget(self.open_logs)
        files.addStretch(1)
        self.root.addLayout(files)

        about = QHBoxLayout()
        about.addWidget(label(f"Version {hooks.version}" if hooks.version else "", "muted"))
        self.releases = button("View releases", flat=True)
        about.addWidget(self.releases)
        about.addStretch(1)
        self.root.addLayout(about)
        self.root.addStretch(1)

        self.url.editingFinished.connect(self._on_url)
        self.poll.valueChanged.connect(self._on_poll)
        self.window.valueChanged.connect(self._on_window)
        self.sounds.toggled.connect(self._on_sounds)
        self.level.currentTextChanged.connect(self._on_level)
        self.disk_cache.toggled.connect(self._on_cache)
        self.clear_btn.clicked.connect(self._clear_cache)
        self.open_config.clicked.connect(lambda: self.hooks.open_path("config"))
        self.open_logs.clicked.connect(lambda: self.hooks.open_path("logs"))
        self.releases.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(RELEASES_URL)))
        self.refresh()

    @property
    def adv(self) -> AdvancedConfig:
        return self.config.advanced

    def refresh_cache_label(self) -> None:
        stats = self.hooks.cache_stats()
        if stats is None:
            self.cache_label.setText("")
            self.clear_btn.setEnabled(False)
            return
        entries, size = stats
        self.cache_label.setText(f"Cache: {entries:,} entries · {format_bytes(size)}")
        self.clear_btn.setEnabled(True)

    def refresh(self) -> None:
        was, self._loading = self._loading, True
        try:
            a = self.adv
            self.url.setText(a.sc2_client_url)
            self.poll.setValue(a.ui_poll_ms)
            self.window.setValue(a.mmr_window)
            self.sounds.setChecked(a.sounds_enabled)
            self.level.setCurrentText(a.log_level)
            self.disk_cache.setChecked(a.disk_cache)
            self.refresh_cache_label()
        finally:
            self._loading = was

    def reset_defaults(self) -> None:
        self.config.advanced = AdvancedConfig()
        self.set_config(self.config)
        self.commit()

    def _set(self, name: str, value) -> None:
        if self._loading:
            return
        setattr(self.adv, name, value)
        self.commit()

    def _on_url(self) -> None:
        text = self.url.text().strip().rstrip("/")
        if text.endswith("/game"):
            text = text[: -len("/game")]
        if text:
            self._set("sc2_client_url", text)

    def _on_poll(self, v: int) -> None:
        self._set("ui_poll_ms", v)

    def _on_window(self, v: int) -> None:
        self._set("mmr_window", v)

    def _on_sounds(self, on: bool) -> None:
        self._set("sounds_enabled", on)

    def _on_level(self, text: str) -> None:
        if text in LOG_LEVELS:
            self._set("log_level", text)

    def _on_cache(self, on: bool) -> None:
        self._set("disk_cache", on)

    def _clear_cache(self) -> None:
        self.hooks.clear_cache()
        self.refresh_cache_label()
