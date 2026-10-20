"""Application-wide signal hub. Create on the main thread and pass everywhere."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class EventBus(QObject):
    state_changed = Signal(object)  # GameState
    game_started = Signal(object)  # GameContext
    game_ended = Signal(object)  # GameResult
    toast_requested = Signal(object)  # ToastSpec (branch 4+)
    config_changed = Signal(object)  # Config
    account_changed = Signal(object)  # AccountConfig (branch 3+)
    session_updated = Signal(object)  # SessionSnapshot (branch 5+)
