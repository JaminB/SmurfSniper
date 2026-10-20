"""Frameless, rounded, focusable dialog shell used by the picker and cheat-sheet."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor, QIcon, QKeyEvent
from PySide6.QtWidgets import QDialog, QFrame, QGraphicsDropShadowEffect, QVBoxLayout, QWidget

from smurfsniper.assets import asset_path
from smurfsniper.ui import tokens as t
from smurfsniper.ui.settings.widgets import TitleBar
from smurfsniper.ui.theme import stylesheet

MARGIN = 14  # room for the drop shadow


class FramelessDialog(QDialog):
    """Rounded dark sheet with a title bar. ``body`` is the layout for content."""

    def __init__(
        self,
        title: str,
        size: tuple[int, int],
        *,
        close_on_focus_loss: bool = False,
        parent: QWidget | None = None,
    ):
        self._close_on_focus_loss = close_on_focus_loss
        super().__init__(parent)
        self.setObjectName("frameless")
        self.setWindowTitle(title)
        self.setWindowIcon(QIcon(str(asset_path("logo.ico"))))
        flags = Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        flags |= Qt.WindowType.Dialog
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(stylesheet())
        self.resize(size[0] + 2 * MARGIN, size[1] + 2 * MARGIN)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(MARGIN, MARGIN, MARGIN, MARGIN)
        self.sheet = QFrame()
        self.sheet.setObjectName("sheet")
        r = t.RADIUS["panel"]
        self.sheet.setStyleSheet(
            f"QFrame#sheet {{ background: {t.css(t.SURFACE)};"
            f" border: 1px solid {t.css((255, 255, 255, 30))}; border-radius: {r}px; }}"
        )
        shadow = QGraphicsDropShadowEffect(self.sheet)
        shadow.setBlurRadius(t.SHADOW["blur"] + 6)
        shadow.setOffset(0, t.SHADOW["dy"])
        shadow.setColor(QColor(0, 0, 0, 150))
        self.sheet.setGraphicsEffect(shadow)
        outer.addWidget(self.sheet)

        inner = QVBoxLayout(self.sheet)
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)
        self.title_bar = TitleBar(title)
        self.title_bar.closeRequested.connect(self.reject)
        inner.addWidget(self.title_bar)
        self.content = QWidget()
        self.content.setObjectName("content")
        self.content.setStyleSheet("QWidget#content { background: transparent; }")
        self.body = QVBoxLayout(self.content)
        self.body.setContentsMargins(16, 6, 16, 16)
        self.body.setSpacing(10)
        inner.addWidget(self.content, 1)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(e)

    def changeEvent(self, e: QEvent) -> None:
        super().changeEvent(e)
        if (
            self._close_on_focus_loss
            and e.type() == QEvent.Type.ActivationChange
            and self.isVisible()
            and not self.isActiveWindow()
        ):
            self.reject()
