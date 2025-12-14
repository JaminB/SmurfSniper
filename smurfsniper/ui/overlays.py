from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QVBoxLayout,
                               QWidget)

from smurfsniper.ui.overlay_manager import register_overlay


class Overlay(QWidget):
    PLAYER_STYLE = """
        color: #FFFFFF;
        background-color: rgba(15, 15, 15, 215);
        padding: 8px 14px;
        border-radius: 10px;
        font-family: 'Segoe UI';
        font-size: 13px;
        font-weight: 500;
        line-height: 145%;
    """

    TM_STYLE = """
        color: #CCCCCC;
        background-color: rgba(10, 10, 10, 180);
        padding: 6px 10px;
        border-radius: 8px;
        font-family: 'Segoe UI';
        font-size: 12px;
        line-height: 140%;
    """

    def __init__(
        self, duration_seconds: int = 40, position: str = "top_center", parent=None
    ):
        super().__init__(parent)

        self.duration_seconds = duration_seconds
        self.position = position

        app = QApplication.instance()
        if not app:
            raise RuntimeError("QApplication must exist before creating Overlay.")

        register_overlay(self)

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowTransparentForInput
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.main_layout.setSpacing(6)

    def add_row(self, blocks: list[str], style: str = None, spacing: int = 18):
        row = QHBoxLayout()
        row.setSpacing(spacing)

        for text in blocks:
            lbl = QLabel(text, self)
            if style:
                lbl.setStyleSheet(style)
            row.addWidget(lbl, 1)

        self.main_layout.addLayout(row)

    def _position_overlay(self):
        screen = QApplication.primaryScreen().geometry()
        self.adjustSize()

        sw, sh = screen.width(), screen.height()
        w, h = self.width(), self.height()

        pos = self.position.lower()

        if pos == "top_left":
            x, y = 20, 20
        elif pos == "top_right":
            x, y = sw - w - 20, 20
        elif pos == "bottom_left":
            x, y = 20, sh - h - 20
        elif pos == "bottom_right":
            x, y = sw - w - 20, sh - h - 20
        elif pos == "bottom_center":
            x, y = (sw - w) // 2, sh - h - 20
        elif pos == "center":
            x, y = (sw - w) // 2, (sh - h) // 2
        else:  # default = top_center
            x, y = (sw - w) // 2, 20

        self.move(x, y)

    def show(self):
        super().show()

        self._position_overlay()

        loop = QEventLoop()
        QTimer.singleShot(0, loop.quit)
        loop.exec()

        QTimer.singleShot(self.duration_seconds * 1000, self.close)
