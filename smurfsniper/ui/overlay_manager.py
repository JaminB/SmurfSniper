from PySide6.QtWidgets import QApplication

OPEN_OVERLAYS = []


def register_overlay(widget):
    OPEN_OVERLAYS.append(widget)


def close_all_overlays():
    app = QApplication.instance()
    if not app:
        return

    for w in reversed(OPEN_OVERLAYS):
        try:
            w.close()
        except:
            pass

    OPEN_OVERLAYS.clear()

    for _ in range(15):
        app.processEvents()
