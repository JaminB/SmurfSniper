"""The hotkey cheat-sheet opened from the tray."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QWidget

from smurfsniper.app.hotkeys import ACTION_LABELS, HotkeyAction, to_display
from smurfsniper.models.config import HotkeyConfig
from smurfsniper.ui.frameless import FramelessDialog
from smurfsniper.ui.settings.widgets import ChipLabel, button, label

FOOTER = "Overlays are click-through. Press a panel's hotkey again to close it."


class HotkeyCheatSheet(FramelessDialog):
    edit_requested = Signal()

    def __init__(self, hotkeys: HotkeyConfig, parent: QWidget | None = None):
        super().__init__("Hotkeys", (360, 330), close_on_focus_loss=True, parent=parent)
        self.chips: dict[HotkeyAction, ChipLabel] = {}
        for action in HotkeyAction:
            row = QHBoxLayout()
            row.setContentsMargins(0, 3, 0, 3)
            row.addWidget(label(ACTION_LABELS[action]), 1)
            chip = ChipLabel()
            self.chips[action] = chip
            row.addWidget(chip)
            self.body.addLayout(row)
        self.disabled_note = label("Global hotkeys are turned off in Settings.", "warning")
        self.body.addWidget(self.disabled_note)
        self.body.addSpacing(4)
        self.body.addWidget(label(FOOTER, "muted", wrap=True))
        edit = button("Edit hotkeys…")
        edit.clicked.connect(self._edit)
        self.body.addWidget(edit)
        self.body.addStretch(1)
        self.set_hotkeys(hotkeys)

    def set_hotkeys(self, hotkeys: HotkeyConfig) -> None:
        for action, chip in self.chips.items():
            chip.setText(to_display(getattr(hotkeys, action.value)))
        self.disabled_note.setVisible(not hotkeys.enabled)

    def _edit(self) -> None:
        self.edit_requested.emit()
        self.close()
