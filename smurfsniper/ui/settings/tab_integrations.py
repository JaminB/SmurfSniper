"""Settings > Integrations."""

from __future__ import annotations

import threading

from pydantic import SecretStr
from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QWidget

from smurfsniper.models.config import Config, IntegrationsConfig
from smurfsniper.ui.settings.widgets import (
    Card,
    SettingsHooks,
    SettingsTab,
    ToggleSwitch,
    button,
    form_row,
    label,
)

SC2PULSE_CREDIT = "Data: SC2Pulse (sc2pulse.nephest.com), non-commercial use"
ALIGULAC_URL = "https://aligulac.com/about/api/"
CREDITS = (
    SC2PULSE_CREDIT,
    "Pro player ratings: Aligulac (aligulac.com)",
    "Player intros: Liquipedia (liquipedia.net), CC-BY-SA 3.0",
)


class IntegrationsTab(SettingsTab):
    title = "Integrations"
    _tested = Signal(object)  # True / False / None (could not test)

    def __init__(self, config: Config, hooks: SettingsHooks):
        super().__init__(config, hooks)
        self.heading("Integrations", "Optional sources that add scouting intel.")

        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("Paste your Aligulac API key")
        self.eye = button("Show", flat=True)
        self.eye.setCheckable(True)
        self.test_btn = button("Test")
        self.test_btn.setEnabled(hooks.test_aligulac is not None)
        self.test_result = label("", "muted")
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(self.key_edit, 1)
        lay.addWidget(self.eye)
        lay.addWidget(self.test_btn)

        card = Card()
        card.body.addWidget(label("Aligulac API key", "h2"))
        card.body.addWidget(
            label("Adds pro-player ratings to the scouting intel panel.", "muted", wrap=True)
        )
        card.body.addWidget(row)
        foot = QHBoxLayout()
        foot.addWidget(self.test_result)
        foot.addStretch(1)
        self.get_key = button("Get a free key", flat=True)
        foot.addWidget(self.get_key)
        card.body.addLayout(foot)
        self.root.addWidget(card)

        self.lp_toggle = ToggleSwitch(True)
        self.root.addWidget(
            form_row(
                "Liquipedia player intros",
                self.lp_toggle,
                "Looks up public player pages. Cached for 24 hours.",
            )
        )
        self.contact = QLineEdit()
        self.contact.setPlaceholderText("Optional email or Discord")
        self.contact.setMinimumWidth(220)
        self.root.addWidget(
            form_row(
                "Contact for Liquipedia",
                self.contact,
                "Sent in the User-Agent so they can reach you.",
            )
        )

        self.root.addSpacing(6)
        self.root.addWidget(label("Data sources", "h2"))
        for line in CREDITS:
            self.root.addWidget(label(line, "muted"))
        self.root.addStretch(1)

        self.key_edit.textChanged.connect(self._on_key)
        self.eye.toggled.connect(self._on_eye)
        self.test_btn.clicked.connect(self._run_test)
        self.get_key.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(ALIGULAC_URL)))
        self.lp_toggle.toggled.connect(self._on_lp)
        self.contact.textChanged.connect(self._on_contact)
        self._tested.connect(self._show_test)
        self.refresh()

    @property
    def integ(self) -> IntegrationsConfig:
        return self.config.integrations

    def refresh(self) -> None:
        was, self._loading = self._loading, True
        try:
            self.key_edit.setText(self.config.aligulac_key)
            self.lp_toggle.setChecked(self.integ.liquipedia_enabled)
            self.contact.setText(self.integ.liquipedia_contact or "")
            self.contact.setEnabled(self.integ.liquipedia_enabled)
        finally:
            self._loading = was

    def reset_defaults(self) -> None:
        self.config.integrations = IntegrationsConfig()
        self.set_config(self.config)
        self.test_result.setText("")
        self.commit()

    # ---------------------------------------------------------------- handlers
    def _on_key(self, text: str) -> None:
        if self._loading:
            return
        text = text.strip()
        self.integ.aligulac_api_key = SecretStr(text) if text else None
        self.test_result.setText("")
        self.commit()

    def _on_eye(self, shown: bool) -> None:
        self.key_edit.setEchoMode(
            QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password
        )
        self.eye.setText("Hide" if shown else "Show")

    def _on_lp(self, on: bool) -> None:
        if self._loading:
            return
        self.integ.liquipedia_enabled = on
        self.contact.setEnabled(on)
        self.commit()

    def _on_contact(self, text: str) -> None:
        if self._loading:
            return
        self.integ.liquipedia_contact = text.strip() or None
        self.commit()

    def _run_test(self) -> None:
        key = self.key_edit.text().strip()
        test = self.hooks.test_aligulac
        if not key:
            self._show_test(None)
            return
        if test is None:
            return
        self.test_result.setProperty("role", "muted")
        self.test_result.setText("Testing…")
        self.test_btn.setEnabled(False)

        def work() -> None:
            try:
                ok: bool | None = bool(test(key))
            except Exception:
                ok = None
            self._tested.emit(ok)

        threading.Thread(target=work, name="aligulac-test", daemon=True).start()

    def _show_test(self, ok: bool | None) -> None:
        self.test_btn.setEnabled(self.hooks.test_aligulac is not None)
        text, role = {
            True: ("✓ Valid", "ok"),
            False: ("✕ Invalid key", "error"),
            None: ("Could not test the key", "warning"),
        }[ok]
        self.test_result.setProperty("role", role)
        self.test_result.style().unpolish(self.test_result)
        self.test_result.style().polish(self.test_result)
        self.test_result.setText(text)
