"""First-run account picker: search SC2Pulse and choose which character is you."""

from __future__ import annotations

from PySide6.QtCore import QSize, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QWidget,
)

from smurfsniper.core.account import AccountCandidate
from smurfsniper.ui import tokens as t
from smurfsniper.ui.frameless import FramelessDialog
from smurfsniper.ui.settings.widgets import button, label

EMPTY_TEXT = (
    "No exact match on SC2Pulse. Check spelling (no #1234), or play one game "
    "and SmurfSniper will detect you."
)
IDLE_TEXT = "Type your in-game name (without the #1234)."
DEBOUNCE_MS = 400


class CandidateRow(QFrame):
    """One result: race accent bar plus the candidate label."""

    def __init__(self, cand: AccountCandidate):
        super().__init__()
        self.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        bar = QFrame()
        bar.setFixedWidth(t.ACCENT_BAR_WIDTH)
        color = t.RACE_ACCENT.get(cand.top_race, t.RACE_ACCENT[None])
        bar.setStyleSheet(f"background: {t.css(color)}; border-radius: 1px;")
        lay.addWidget(bar)
        text = label(cand.label(), wrap=True)
        text.setStyleSheet("font-size: 12px;")
        lay.addWidget(text, 1)


class AccountPickerDialog(FramelessDialog):
    search_requested = Signal(str)
    chosen = Signal(object)  # AccountCandidate
    detect_requested = Signal()

    def __init__(self, initial_query: str = "", parent: QWidget | None = None):
        super().__init__("Choose your account", (420, 480), parent=parent)
        self._cands: list[AccountCandidate] = []
        self._query = ""

        self.body.addWidget(
            label(
                "SmurfSniper uses your account to tell you apart from opponents "
                "and to keep your MMR up to date.",
                "muted",
                wrap=True,
            )
        )
        self.search = QLineEdit(initial_query)
        self.search.setPlaceholderText("In-game name")
        self.body.addWidget(self.search)

        self.status = label(IDLE_TEXT, "muted", wrap=True)
        self.body.addWidget(self.status)
        self.results = QListWidget()
        self.results.setObjectName("results")
        self.results.setSpacing(2)
        self.body.addWidget(self.results, 1)

        buttons = QHBoxLayout()
        self.use_btn = button("Use this account", primary=True)
        self.use_btn.setEnabled(False)
        self.auto_btn = button("Detect automatically")
        self.cancel_btn = button("Cancel", flat=True)
        buttons.addWidget(self.use_btn)
        buttons.addWidget(self.auto_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_btn)
        self.body.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self._fire_search)
        self.search.textChanged.connect(lambda _t: self._timer.start())
        self.results.currentRowChanged.connect(lambda r: self.use_btn.setEnabled(r >= 0))
        self.results.itemDoubleClicked.connect(lambda _i: self._use())
        self.use_btn.clicked.connect(self._use)
        self.auto_btn.clicked.connect(self._auto)
        self.cancel_btn.clicked.connect(self.reject)
        if initial_query.strip():
            self._timer.start(0)

    # --------------------------------------------------------------------- api
    def _fire_search(self) -> None:
        query = self.search.text().split("#")[0].strip()
        if not query:
            self._clear()
            self.status.show()
            self.status.setText(IDLE_TEXT)
            return
        self._query = query
        self._clear()
        self.status.show()
        self.status.setText("Searching…")
        self.search_requested.emit(query)

    def set_results(self, query: str, cands: list[AccountCandidate]) -> None:
        """Show ``cands`` if ``query`` is still what the user typed."""
        if query.casefold() != self.search.text().split("#")[0].strip().casefold():
            return
        self._clear()
        self._cands = list(cands)
        self.status.show()
        if not cands:
            self.status.setText(EMPTY_TEXT)
            return
        self.status.setText("")
        self.status.hide()
        for cand in cands:
            item = QListWidgetItem()
            row = CandidateRow(cand)
            item.setSizeHint(QSize(100, max(44, row.sizeHint().height() + 14)))
            item.setForeground(QColor("white"))
            self.results.addItem(item)
            self.results.setItemWidget(item, row)
        self.results.setCurrentRow(0)

    def _clear(self) -> None:
        self.results.clear()
        self._cands = []
        self.use_btn.setEnabled(False)

    def _use(self) -> None:
        row = self.results.currentRow()
        if 0 <= row < len(self._cands):
            self.chosen.emit(self._cands[row])
            self.accept()

    def _auto(self) -> None:
        self.detect_requested.emit()
        self.accept()
