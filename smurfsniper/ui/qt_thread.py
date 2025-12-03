import sys

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import QApplication


class UiExecutor(QObject):
    run = Signal(object)

    def __init__(self):
        super().__init__()
        self.run.connect(self._execute)

    def _execute(self, fn):
        fn()


class QtThread(QThread):
    """
    A dedicated Qt GUI thread that owns the QApplication event loop.
    All Qt UI work must run inside this thread.
    """

    def __init__(self):
        super().__init__()
        self.executor = None

    def run(self):
        self.app = QApplication.instance() or QApplication(sys.argv)
        self.executor = UiExecutor()
        self.app.exec()


qt_thread = QtThread()


def run_in_ui(fn):
    """
    Schedule a function to run in the Qt GUI thread.
    Safe to call from any thread (async / background thread, etc.)
    """
    if qt_thread.executor is None:
        raise RuntimeError(
            "QtThread not started — call qt_thread.start() before using run_in_ui()."
        )

    qt_thread.executor.run.emit(fn)
