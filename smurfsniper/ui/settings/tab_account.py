"""Settings > Account."""

from __future__ import annotations

from datetime import UTC, datetime

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QSpinBox, QVBoxLayout, QWidget

from smurfsniper.core.profile import ago
from smurfsniper.models.config import QUEUE_1V1, AccountConfig, Config
from smurfsniper.ui.settings.widgets import (
    Card,
    ChipList,
    SettingsHooks,
    SettingsTab,
    ToggleSwitch,
    button,
    form_row,
    label,
)


class AccountTab(SettingsTab):
    title = "Account"

    def __init__(self, config: Config, hooks: SettingsHooks):
        super().__init__(config, hooks)
        self.heading("Account", "SmurfSniper finds your account and keeps your MMR up to date.")

        self.card = Card()
        self.name_label = label("", "h2")
        self.detail_label = label("", "secondary", wrap=True)
        self.card.body.addWidget(self.name_label)
        self.card.body.addWidget(self.detail_label)
        actions = QHBoxLayout()
        self.change_btn = button("Change account…", primary=True)
        self.refresh_btn = button("Refresh MMR now")
        actions.addWidget(self.change_btn)
        actions.addWidget(self.refresh_btn)
        actions.addStretch(1)
        self.card.body.addLayout(actions)
        self.root.addWidget(self.card)

        self.auto = ToggleSwitch()
        self.root.addWidget(
            form_row(
                "Auto-detect my in-game name",
                self.auto,
                "Learns who you are from the games you play.",
            )
        )

        group = QVBoxLayout()
        group.setSpacing(1)
        group.addWidget(label("Teammates"))
        group.addWidget(
            label("Names treated as allies in arranged team games.", "muted", wrap=True)
        )
        self.root.addLayout(group)
        self.teammates = ChipList("Add a teammate and press Enter")
        self.root.addWidget(self.teammates)

        self.override_box = QCheckBox("Override")
        self.override_spin = QSpinBox()
        self.override_spin.setRange(0, 9999)
        self.override_spin.setValue(3000)
        self.override_spin.setFixedWidth(96)
        holder = QWidget()
        lay = QHBoxLayout(holder)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.override_box)
        lay.addWidget(self.override_spin)
        self.root.addWidget(
            form_row("Manual MMR", holder, "Used for opponent matching instead of the auto value.")
        )
        self.root.addStretch(1)

        self.change_btn.clicked.connect(lambda: self.hooks.change_account())
        self.refresh_btn.clicked.connect(lambda: self.hooks.refresh_mmr())
        self.auto.toggled.connect(self._on_auto)
        self.teammates.itemsChanged.connect(self._on_teammates)
        self.override_box.toggled.connect(self._on_override)
        self.override_spin.valueChanged.connect(self._on_override)
        self.refresh()

    # ------------------------------------------------------------------ state
    @property
    def acct(self) -> AccountConfig:
        return self.config.account

    def summary(self, now: datetime | None = None) -> tuple[str, str]:
        a = self.acct
        if not a.name:
            return (
                "No account selected yet",
                "Play a game and SmurfSniper will detect you, or pick your account now.",
            )
        parts: list[str] = []
        if a.region:
            parts.append(a.region)
        mmr = a.mmr_for(QUEUE_1V1)
        if mmr:
            parts.append(f"{mmr:,} MMR" + (" (manual)" if a.mmr_override is not None else ""))
        if a.mmr_updated_at and a.mmr_override is None:
            parts.append(f"updated {ago(a.mmr_updated_at, now or datetime.now(UTC))} ago")
        return a.name, "  ·  ".join(parts)

    def refresh(self) -> None:
        was, self._loading = self._loading, True
        try:
            title, detail = self.summary()
            self.name_label.setText(title)
            self.detail_label.setText(detail)
            self.detail_label.setVisible(bool(detail))
            self.refresh_btn.setEnabled(self.acct.character_id is not None)
            self.auto.setChecked(self.acct.auto_detect)
            self.teammates.set_items(self.acct.teammates)
            has_override = self.acct.mmr_override is not None
            self.override_box.setChecked(has_override)
            self.override_spin.setEnabled(has_override)
            if has_override:
                self.override_spin.setValue(self.acct.mmr_override)
        finally:
            self._loading = was

    def reset_defaults(self) -> None:
        self.acct.auto_detect = True
        self.acct.teammates = []
        self.acct.mmr_override = None
        self.set_config(self.config)
        self.commit()

    # ---------------------------------------------------------------- handlers
    def _on_auto(self, on: bool) -> None:
        if self._loading:
            return
        self.acct.auto_detect = on
        self.commit()

    def _on_teammates(self, items: list) -> None:
        self.acct.teammates = list(items)
        self.commit()

    def _on_override(self, *_args) -> None:
        if self._loading:
            return
        on = self.override_box.isChecked()
        self.override_spin.setEnabled(on)
        self.acct.mmr_override = self.override_spin.value() if on else None
        self.commit()
