"""Settings > Hotkeys."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtWidgets import QGridLayout, QKeySequenceEdit, QVBoxLayout, QWidget

from smurfsniper.app.hotkeys import (
    ACTION_LABELS,
    DEFAULT_BINDINGS,
    BindingIssue,
    HotkeyAction,
    from_qkeysequence,
    normalize,
    to_display,
    validate_bindings,
)
from smurfsniper.models.config import Config, HotkeyConfig
from smurfsniper.ui.settings.widgets import (
    ChipLabel,
    SettingsHooks,
    SettingsTab,
    ToggleSwitch,
    button,
    form_row,
    label,
)

FOOTNOTE = "SC2 still receives these keys. Avoid combos bound in your SC2 hotkey profile."


class RecordEdit(QKeySequenceEdit):
    """Key recorder that reports Esc as a cancel instead of recording it."""

    cancelled = Signal()

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key.Key_Escape and e.modifiers() == Qt.KeyboardModifier.NoModifier:
            self.cancelled.emit()
            return
        super().keyPressEvent(e)


class HotkeyRow(QWidget):
    recorded = Signal(object, str)  # (HotkeyAction, binding)
    reset_requested = Signal(object)
    recording_started = Signal(object)
    recording_stopped = Signal(object)

    def __init__(self, action: HotkeyAction):
        super().__init__()
        self.action = action
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 4)
        outer.setSpacing(2)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setColumnStretch(0, 1)
        self.name = label(ACTION_LABELS[action])
        self.chip = ChipLabel()
        self.edit = RecordEdit()
        self.edit.setMaximumSequenceLength(1)
        self.edit.setFixedWidth(150)
        self.edit.hide()
        self.record_btn = button("Record")
        self.reset_btn = button("Reset", flat=True)
        grid.addWidget(self.name, 0, 0)
        grid.addWidget(self.chip, 0, 1, Qt.AlignmentFlag.AlignRight)
        grid.addWidget(self.edit, 0, 1, Qt.AlignmentFlag.AlignRight)
        grid.addWidget(self.record_btn, 0, 2)
        grid.addWidget(self.reset_btn, 0, 3)
        outer.addLayout(grid)
        self.message = label("", "error", wrap=True)
        self.message.hide()
        outer.addWidget(self.message)

        self.record_btn.clicked.connect(self.toggle_recording)
        self.reset_btn.clicked.connect(lambda: self.reset_requested.emit(self.action))
        self.edit.keySequenceChanged.connect(self._on_sequence)
        self.edit.cancelled.connect(self.stop_recording)

    @property
    def recording(self) -> bool:
        return not self.edit.isHidden()

    def toggle_recording(self) -> None:
        if self.edit.isHidden():
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self) -> None:
        self.recording_started.emit(self.action)
        self.chip.hide()
        self.edit.clear()
        self.edit.show()
        self.edit.setFocus()
        self.record_btn.setText("Cancel")

    def stop_recording(self) -> None:
        was_recording = not self.edit.isHidden()
        self.edit.hide()
        self.edit.clear()
        self.chip.show()
        self.record_btn.setText("Record")
        if was_recording:
            self.recording_stopped.emit(self.action)

    def _on_sequence(self, seq: QKeySequence) -> None:
        if seq.isEmpty() or self.edit.isHidden():
            return
        binding = from_qkeysequence(seq)
        self.stop_recording()
        if binding and binding != "escape":
            self.recorded.emit(self.action, binding)

    def show_binding(self, binding: str) -> None:
        self.chip.setText(to_display(binding))

    def show_issue(self, issue: BindingIssue | None, text: str | None = None) -> None:
        if issue is None and not text:
            self.message.hide()
            return
        level = issue.level if issue else "error"
        self.message.setProperty("role", "error" if level == "error" else "warning")
        self.message.style().unpolish(self.message)
        self.message.style().polish(self.message)
        self.message.setText(text or (issue.message if issue else ""))
        self.message.show()


class HotkeysTab(SettingsTab):
    title = "Hotkeys"

    def __init__(self, config: Config, hooks: SettingsHooks):
        super().__init__(config, hooks)
        self.heading(
            "Hotkeys", "Press a panel's hotkey again to close it. Overlays never block the mouse."
        )
        self.enabled = ToggleSwitch(True)
        self.root.addWidget(form_row("Enable global hotkeys", self.enabled))
        self.rows: dict[HotkeyAction, HotkeyRow] = {}
        box = QVBoxLayout()
        box.setSpacing(0)
        for action in HotkeyAction:
            row = HotkeyRow(action)
            row.recorded.connect(self.set_binding)
            row.reset_requested.connect(self._reset_one)
            row.recording_started.connect(lambda _a: self.hooks.suspend_hotkeys())
            row.recording_stopped.connect(lambda _a: self.hooks.resume_hotkeys())
            self.rows[action] = row
            box.addWidget(row)
        self.root.addLayout(box)
        self.root.addWidget(label(FOOTNOTE, "muted", wrap=True))
        self.root.addStretch(1)
        self.enabled.toggled.connect(self._on_enabled)
        self.refresh()

    @property
    def hk(self) -> HotkeyConfig:
        return self.config.hotkeys

    def refresh(self) -> None:
        was, self._loading = self._loading, True
        try:
            self.enabled.blockSignals(True)
            self.enabled.setChecked(self.hk.enabled)
            self.enabled.blockSignals(False)
            for action, row in self.rows.items():
                row.show_binding(getattr(self.hk, action.value))
            self._show_issues()
        finally:
            self._loading = was

    def _show_issues(self, rejected: dict[HotkeyAction, str] | None = None) -> None:
        issues = validate_bindings(self.hk)
        by_action: dict[HotkeyAction, BindingIssue] = {}
        for i in issues:
            cur = by_action.get(i.action)
            if cur is None or (cur.level == "warning" and i.level == "error"):
                by_action[i.action] = i
        for action, row in self.rows.items():
            if rejected and action in rejected:
                row.show_issue(None, rejected[action])
            else:
                row.show_issue(by_action.get(action))

    def reset_defaults(self) -> None:
        self.config.hotkeys = HotkeyConfig()
        self.set_config(self.config)
        self.commit()

    # ---------------------------------------------------------------- handlers
    def set_binding(self, action: HotkeyAction, binding: str) -> bool:
        """Apply ``binding`` unless it has errors. Returns whether it was applied."""
        old = getattr(self.hk, action.value)
        setattr(self.hk, action.value, normalize(binding))
        errors = [
            i for i in validate_bindings(self.hk) if i.action is action and i.level == "error"
        ]
        if errors:
            setattr(self.hk, action.value, old)
            self._show_issues({action: errors[0].message})
            return False
        self.rows[action].show_binding(getattr(self.hk, action.value))
        self._show_issues()
        self.commit()
        return True

    def _reset_one(self, action: HotkeyAction) -> None:
        self.set_binding(action, DEFAULT_BINDINGS[action])

    def _on_enabled(self, on: bool) -> None:
        if self._loading:
            return
        self.hk.enabled = on
        self.commit()
