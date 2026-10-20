"""Qt stylesheet for normal (focusable) windows: Settings, picker, cheat-sheet."""

from __future__ import annotations

from smurfsniper.ui import tokens as t

R = t.RADIUS
BG = t.css(t.SURFACE)
RAISED = t.css(t.SURFACE_RAISED)
ACCENT = t.css(t.INFO)
TEXT = t.css(t.TEXT_PRIMARY)
TEXT2 = t.css(t.TEXT_SECONDARY)
MUTED = t.css(t.TEXT_MUTED)
LINE = t.css(t.BORDER)
FIELD = "rgba(255, 255, 255, 0.06)"
FIELD_HOVER = "rgba(255, 255, 255, 0.10)"
ERROR = t.css(t.NEGATIVE)
OK = t.css(t.POSITIVE)
AMBER = t.css(t.WARNING)


def stylesheet() -> str:
    return f"""
* {{ font-family: {t.FONT_FAMILY_CSS}; font-size: {t.FONT_SIZE["body"] + 1}px; color: {TEXT}; }}
QWidget#root, QDialog#root, QWidget#settings {{ background: {BG}; }}
QLabel {{ background: transparent; }}
QLabel[role="title"] {{ font-size: {t.FONT_SIZE["title"] + 3}px; font-weight: 600; }}
QLabel[role="h2"] {{ font-size: {t.FONT_SIZE["title"]}px; font-weight: 600; }}
QLabel[role="muted"] {{ color: {MUTED}; font-size: {t.FONT_SIZE["caption"] + 1}px; }}
QLabel[role="secondary"] {{ color: {TEXT2}; }}
QLabel[role="error"] {{ color: {ERROR}; font-size: {t.FONT_SIZE["caption"] + 1}px; }}
QLabel[role="warning"] {{ color: {AMBER}; font-size: {t.FONT_SIZE["caption"] + 1}px; }}
QLabel[role="ok"] {{ color: {OK}; font-size: {t.FONT_SIZE["caption"] + 1}px; }}
QFrame[role="card"] {{ background: {RAISED}; border: 1px solid {LINE};
    border-radius: {R["card"]}px; }}
QFrame[role="card"] QLabel {{ background: transparent; }}
QListWidget#nav {{ background: rgba(255,255,255,0.03); border: none; outline: none;
    border-right: 1px solid {LINE}; padding: 8px 6px; }}
QListWidget#nav::item {{ padding: 8px 12px; border-radius: {R["chip"] + 2}px;
    color: {TEXT2}; margin-bottom: 2px; }}
QListWidget#nav::item:hover {{ background: {FIELD}; }}
QListWidget#nav::item:selected {{ background: rgba(96,165,250,0.18); color: {TEXT}; }}
QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget#results::item {{ padding: 8px 10px; border-radius: {R["chip"] + 2}px; }}
QListWidget#results::item:hover {{ background: {FIELD}; }}
QListWidget#results::item:selected {{ background: rgba(96,165,250,0.20); }}
QPushButton {{ background: {FIELD}; border: 1px solid {LINE}; border-radius: {R["chip"] + 2}px;
    padding: 6px 14px; }}
QPushButton:hover {{ background: {FIELD_HOVER}; }}
QPushButton:pressed {{ background: rgba(255,255,255,0.14); }}
QPushButton:disabled {{ color: {MUTED}; }}
QPushButton[primary="true"] {{ background: {ACCENT}; color: #0b1020; border: none;
    font-weight: 600; }}
QPushButton[primary="true"]:hover {{ background: rgb(125, 183, 252); }}
QPushButton[flat="true"] {{ background: transparent; border: none; color: {TEXT2}; }}
QPushButton[flat="true"]:hover {{ color: {TEXT}; background: {FIELD}; }}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QKeySequenceEdit {{ background: {FIELD};
    border: 1px solid {LINE}; border-radius: {R["chip"] + 2}px; padding: 5px 8px;
    selection-background-color: {ACCENT}; selection-color: #0b1020; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QKeySequenceEdit:focus {{
    border: 1px solid {ACCENT}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {RAISED}; border: 1px solid {LINE};
    selection-background-color: rgba(96,165,250,0.30); outline: none; }}
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px;
    border: 1px solid rgba(255,255,255,0.28); background: {FIELD}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border: 1px solid {ACCENT}; }}
QSlider::groove:horizontal {{ height: 4px; background: rgba(255,255,255,0.12);
    border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: #fff; width: 14px; height: 14px; margin: -5px 0;
    border-radius: 7px; }}
QScrollArea {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 0; }}
QScrollBar::handle:vertical {{ background: rgba(255,255,255,0.18); border-radius: 4px;
    min-height: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QToolTip {{ background: {RAISED}; color: {TEXT}; border: 1px solid {LINE}; padding: 4px 6px; }}
QMenu {{ background: {RAISED}; border: 1px solid {LINE}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 4px; }}
QMenu::item:selected {{ background: rgba(96,165,250,0.25); }}
QMenu::item:disabled {{ color: {MUTED}; }}
QMenu::separator {{ height: 1px; background: {LINE}; margin: 4px 8px; }}
"""
