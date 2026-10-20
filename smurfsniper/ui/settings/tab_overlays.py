"""Settings > Overlays."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QHBoxLayout, QSpinBox, QVBoxLayout

from smurfsniper.models.config import Config, OverlayConfig, Placement
from smurfsniper.ui.settings.widgets import (
    AnchorGrid,
    Card,
    LabeledSlider,
    ScreenPreview,
    SettingsHooks,
    SettingsTab,
    ToggleSwitch,
    button,
    form_row,
    label,
)

DISPLAY_NOTE = (
    "Overlays appear above SC2 in Windowed (Fullscreen) or windowed mode, "
    "not in exclusive fullscreen."
)


def _offset_spin() -> QSpinBox:
    s = QSpinBox()
    s.setRange(-2000, 2000)
    s.setFixedWidth(76)
    s.setSingleStep(4)
    return s


class SurfaceRow(Card):
    """Placement controls for one overlay surface."""

    def __init__(
        self,
        title: str,
        *,
        toggle: bool = True,
        seconds_label: str | None = None,
        seconds_range: tuple[float, float] = (0, 300),
        decimals: int = 0,
    ):
        super().__init__()
        head = QHBoxLayout()
        head.addWidget(label(title, "h2"))
        head.addStretch(1)
        self.enabled = ToggleSwitch(True)
        self.enabled.setVisible(toggle)
        head.addWidget(self.enabled)
        self.body.addLayout(head)

        grid_row = QHBoxLayout()
        grid_row.setSpacing(16)
        self.grid = AnchorGrid()
        grid_row.addWidget(self.grid, 0, Qt.AlignmentFlag.AlignTop)
        fields = QVBoxLayout()
        fields.setSpacing(6)
        offs = QHBoxLayout()
        self.off_x, self.off_y = _offset_spin(), _offset_spin()
        offs.addWidget(label("X", "muted"))
        offs.addWidget(self.off_x)
        offs.addSpacing(8)
        offs.addWidget(label("Y", "muted"))
        offs.addWidget(self.off_y)
        offs.addStretch(1)
        fields.addLayout(offs)
        self.seconds: QDoubleSpinBox | None = None
        if seconds_label:
            sec = QHBoxLayout()
            sec.addWidget(label(seconds_label, "muted"))
            self.seconds = QDoubleSpinBox()
            self.seconds.setDecimals(decimals)
            self.seconds.setRange(*seconds_range)
            self.seconds.setSuffix(" s")
            self.seconds.setFixedWidth(84)
            sec.addWidget(self.seconds)
            sec.addStretch(1)
            fields.addLayout(sec)
        fields.addStretch(1)
        grid_row.addLayout(fields, 1)
        self.body.addLayout(grid_row)

    def _widgets(self):
        return [w for w in (self.enabled, self.grid, self.off_x, self.off_y, self.seconds) if w]

    def load(self, enabled: bool, placement: Placement, seconds: float | None) -> None:
        for w in self._widgets():
            w.blockSignals(True)
        self.enabled.setChecked(enabled)
        self.grid.set_anchor(placement.anchor)
        self.off_x.setValue(placement.offset_x)
        self.off_y.setValue(placement.offset_y)
        if self.seconds is not None and seconds is not None:
            self.seconds.setValue(seconds)
        for w in self._widgets():
            w.blockSignals(False)

    def placement(self) -> Placement:
        return Placement(
            anchor=self.grid.anchor(), offset_x=self.off_x.value(), offset_y=self.off_y.value()
        )


class OverlaysTab(SettingsTab):
    title = "Overlays"

    def __init__(self, config: Config, hooks: SettingsHooks):
        super().__init__(config, hooks)
        self.heading("Overlays", DISPLAY_NOTE)

        top = QHBoxLayout()
        top.setSpacing(20)
        left = QVBoxLayout()
        left.setSpacing(10)
        self.opacity = LabeledSlider(40, 100, 5)
        self.opacity.setMinimumWidth(200)
        self.scale = LabeledSlider(75, 150, 5)
        self.scale.setMinimumWidth(200)
        self.screen = QComboBox()
        self.screen.setMinimumWidth(160)
        self.replays = ToggleSwitch()
        left.addWidget(form_row("Opacity", self.opacity))
        left.addWidget(form_row("Size", self.scale))
        left.addWidget(form_row("Screen", self.screen))
        left.addWidget(form_row("Show in replays", self.replays))
        top.addLayout(left, 1)
        self.preview_pane = ScreenPreview(config.overlays)
        right = QVBoxLayout()
        right.addWidget(self.preview_pane)
        self.preview_btn = button("Preview on screen")
        right.addWidget(self.preview_btn)
        right.addStretch(1)
        top.addLayout(right)
        self.root.addLayout(top)

        self.card_row = SurfaceRow(
            "Opponent card", seconds_label="Auto-hide (0 = stay)", seconds_range=(0, 600)
        )
        self.toast_row = SurfaceRow("Toasts", seconds_label="Visible for", decimals=1)
        self.panel_row = SurfaceRow("Panels", toggle=False)
        self.hint_row = SurfaceRow("Hotkey hint", seconds_label="Visible for", decimals=1)
        self.rows = [self.card_row, self.toast_row, self.panel_row, self.hint_row]
        for r in self.rows:
            self.root.addWidget(r)
        self.root.addStretch(1)

        self.opacity.valueChanged.connect(self._on_opacity)
        self.scale.valueChanged.connect(self._on_scale)
        self.screen.currentIndexChanged.connect(self._on_screen)
        self.replays.toggled.connect(self._on_replays)
        for r in self.rows:
            r.enabled.toggled.connect(self._on_surface)
            r.grid.anchorChanged.connect(self._on_surface)
            r.off_x.valueChanged.connect(self._on_surface)
            r.off_y.valueChanged.connect(self._on_surface)
            if r.seconds is not None:
                r.seconds.valueChanged.connect(self._on_surface)
        self.preview_btn.clicked.connect(lambda: self.hooks.preview(self.config))
        self.refresh()

    @property
    def ov(self) -> OverlayConfig:
        return self.config.overlays

    def _fill_screens(self) -> None:
        self.screen.blockSignals(True)
        self.screen.clear()
        self.screen.addItem("Primary screen", None)
        for i, name in enumerate(self.hooks.screens()):
            self.screen.addItem(f"{i + 1}: {name}", i)
        idx = self.screen.findData(self.ov.screen)
        self.screen.setCurrentIndex(max(0, idx))
        self.screen.blockSignals(False)

    def refresh(self) -> None:
        was, self._loading = self._loading, True
        try:
            ov = self.ov
            self.opacity.set_value(round(ov.opacity * 100))
            self.scale.set_value(round(ov.scale * 100))
            self.replays.blockSignals(True)
            self.replays.setChecked(ov.show_in_replays)
            self.replays.blockSignals(False)
            self._fill_screens()
            self.card_row.load(ov.card.enabled, ov.card.placement, ov.card.auto_hide_seconds)
            self.toast_row.load(ov.toasts.enabled, ov.toasts.placement, ov.toasts.seconds)
            self.panel_row.load(True, ov.panels.placement, None)
            self.hint_row.load(ov.hint.enabled, ov.hint.placement, ov.hint.seconds)
            self.preview_pane.set_overlays(ov)
        finally:
            self._loading = was

    def reset_defaults(self) -> None:
        self.config.overlays = OverlayConfig()
        self.set_config(self.config)
        self.commit()

    # ---------------------------------------------------------------- handlers
    def _after(self) -> None:
        self.preview_pane.set_overlays(self.ov)
        self.commit()

    def _on_opacity(self, v: int) -> None:
        self.ov.opacity = v / 100
        self._after()

    def _on_scale(self, v: int) -> None:
        self.ov.scale = v / 100
        self._after()

    def _on_screen(self, _i: int) -> None:
        if self._loading:
            return
        self.ov.screen = self.screen.currentData()
        self._after()

    def _on_replays(self, on: bool) -> None:
        self.ov.show_in_replays = on
        self._after()

    def _on_surface(self, *_args) -> None:
        if self._loading:
            return
        ov = self.ov
        ov.card.enabled = self.card_row.enabled.isChecked()
        ov.card.placement = self.card_row.placement()
        ov.card.auto_hide_seconds = int(self.card_row.seconds.value())
        ov.toasts.enabled = self.toast_row.enabled.isChecked()
        ov.toasts.placement = self.toast_row.placement()
        ov.toasts.seconds = float(self.toast_row.seconds.value())
        ov.panels.placement = self.panel_row.placement()
        ov.hint.enabled = self.hint_row.enabled.isChecked()
        ov.hint.placement = self.hint_row.placement()
        ov.hint.seconds = float(self.hint_row.seconds.value())
        self._after()
