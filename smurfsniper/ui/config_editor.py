"""Modal config editor dialog.

Exposes every config.yaml option in a form. On "Run" the form is serialized to a
yaml-shaped dict, validated through the same Pydantic path as on-disk configs, and
returned to the caller. The caller owns the QApplication; this module never creates
one.
"""

from __future__ import annotations

from pydantic import ValidationError
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from smurfsniper.models.config import Config, OverlayPreferences, Preferences

ORIENTATIONS = ["horizontal", "vertical"]
# Only the anchors overlays.py::_position_overlay actually handles.
POSITIONS = [
    "top_left",
    "top_center",
    "top_right",
    "center",
    "bottom_left",
    "bottom_center",
    "bottom_right",
]

# MMR spinbox bounds — wide enough to cover any ladder value.
MMR_MIN = 0
MMR_MAX = 12000

# Labels for the six overlay blocks, paired with their yaml key.
OVERLAY_BLOCKS = [
    ("1v1 overlay", "1v1_overlay", "overlay_1v1"),
    ("2v2 overlay", "2v2_overlay", "overlay_2v2"),
    ("Team overlay", "team_overlay", "overlay_team"),
    ("Player log 1", "overlay_player_log_1", "overlay_player_log_1"),
    ("Player log 2", "overlay_player_log_2", "overlay_player_log_2"),
    ("External overlay", "external_overlay", "overlay_external"),
]


class OverlayGroup(QGroupBox):
    """Editor for a single OverlayPreferences block."""

    def __init__(self, title: str, prefs: OverlayPreferences):
        super().__init__(title)

        self.visible = QCheckBox()
        self.visible.setChecked(prefs.visible)

        self.orientation = QComboBox()
        self.orientation.addItems(ORIENTATIONS)
        self.orientation.setCurrentText(prefs.orientation)

        self.position = QComboBox()
        self.position.addItems(POSITIONS)
        self.position.setCurrentText(prefs.position)

        self.delay = QDoubleSpinBox()
        self.delay.setRange(0.0, 600.0)
        self.delay.setSingleStep(0.5)
        self.delay.setValue(prefs.seconds_delay_before_show)

        self.seconds_visible = QSpinBox()
        self.seconds_visible.setRange(0, 3600)
        self.seconds_visible.setValue(prefs.seconds_visible)

        form = QFormLayout(self)
        form.addRow("Visible", self.visible)
        form.addRow("Orientation", self.orientation)
        form.addRow("Position", self.position)
        form.addRow("Delay before show (s)", self.delay)
        form.addRow("Seconds visible", self.seconds_visible)

    def to_yaml_dict(self) -> dict:
        return {
            "visible": self.visible.isChecked(),
            "orientation": self.orientation.currentText(),
            "position": self.position.currentText(),
            "seconds_delay_before_show": self.delay.value(),
            "seconds_visible": self.seconds_visible.value(),
        }


class ConfigEditorDialog(QDialog):
    def __init__(self, config: Config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("SmurfSniper — Configuration")
        self.setMinimumWidth(480)
        self.result_config: Config | None = None

        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        tabs.addTab(self._build_general_tab(config), "General")
        tabs.addTab(self._build_overlays_tab(config), "Overlays")
        tabs.addTab(self._build_integrations_tab(config), "Integrations")
        layout.addWidget(tabs)

        self.error_banner = QLabel()
        self.error_banner.setStyleSheet("color: #d33; font-weight: bold;")
        self.error_banner.setWordWrap(True)
        self.error_banner.hide()
        layout.addWidget(self.error_banner)

        buttons = QDialogButtonBox()
        run_btn = QPushButton("Run")
        run_btn.setDefault(True)
        buttons.addButton(run_btn, QDialogButtonBox.AcceptRole)
        buttons.addButton(QDialogButtonBox.Cancel)
        run_btn.clicked.connect(self._on_run)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_general_tab(self, config: Config) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        self.me_name = QLineEdit(config.me.name)
        self.me_mmr = QSpinBox()
        self.me_mmr.setRange(MMR_MIN, MMR_MAX)
        self.me_mmr.setValue(config.me.mmr)

        self.team_name = QLineEdit(config.team.name)
        self.team_mmr = QSpinBox()
        self.team_mmr.setRange(MMR_MIN, MMR_MAX)
        self.team_mmr.setValue(config.team.mmr)
        self.team_members = QPlainTextEdit("\n".join(config.team.members))
        self.team_members.setPlaceholderText("One member name per line")

        form.addRow("My name", self.me_name)
        form.addRow("My MMR", self.me_mmr)
        form.addRow("Team name", self.team_name)
        form.addRow("Team MMR", self.team_mmr)
        form.addRow("Team members", self.team_members)
        return w

    def _build_overlays_tab(self, config: Config) -> QWidget:
        prefs = config.preferences or Preferences.defaults()
        container = QWidget()
        vbox = QVBoxLayout(container)

        self.overlay_groups: dict[str, OverlayGroup] = {}
        for title, yaml_key, field in OVERLAY_BLOCKS:
            group = OverlayGroup(title, getattr(prefs, field))
            self.overlay_groups[yaml_key] = group
            vbox.addWidget(group)
        vbox.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(container)
        return scroll

    def _build_integrations_tab(self, config: Config) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)

        api_key = ""
        if config.integrations and config.integrations.aligulac:
            api_key = config.integrations.aligulac.api_key
        self.aligulac_key = QLineEdit(api_key)

        form.addRow("Aligulac API key", self.aligulac_key)
        return w

    def _collect_raw(self) -> dict:
        return {
            "me": {
                "mmr": self.me_mmr.value(),
                "name": self.me_name.text(),
            },
            "team": {
                "name": self.team_name.text(),
                "mmr": self.team_mmr.value(),
                "members": [
                    line.strip()
                    for line in self.team_members.toPlainText().splitlines()
                    if line.strip()
                ],
            },
            "preferences": {
                yaml_key: group.to_yaml_dict()
                for yaml_key, group in self.overlay_groups.items()
            },
            "integrations": {
                "aligulac": {"api_key": self.aligulac_key.text()},
            },
        }

    def _on_run(self) -> None:
        raw = self._collect_raw()
        try:
            raw["preferences"] = Preferences.from_yaml(raw["preferences"])
            self.result_config = Config.model_validate(raw)
        except ValidationError as e:
            self._show_errors(e)
            return
        self.accept()

    def _show_errors(self, error: ValidationError) -> None:
        lines = []
        for err in error.errors():
            loc = ".".join(str(p) for p in err["loc"])
            lines.append(f"{loc}: {err['msg']}")
        self.error_banner.setText("Invalid config:\n" + "\n".join(lines))
        self.error_banner.show()


def edit_config(config: Config) -> Config | None:
    """Show the editor modally. Returns the edited Config on Run, None on cancel.

    A QApplication must already exist (the caller owns it).
    """
    dlg = ConfigEditorDialog(config)
    if dlg.exec() == QDialog.Accepted:
        return dlg.result_config
    return None
