from PySide6.QtWidgets import QApplication

OPEN_OVERLAYS = []


def register_overlay(widget):
    OPEN_OVERLAYS.append(widget)


def close_all_overlays():
    app = QApplication.instance()
    if not app:
        return

    # Close in reverse order to avoid painting glitches
    for w in reversed(OPEN_OVERLAYS):
        try:
            w.close()
        except:
            pass

    OPEN_OVERLAYS.clear()

    # 🔥 IMPORTANT: Let Qt process the close events
    for _ in range(15):
        app.processEvents()
