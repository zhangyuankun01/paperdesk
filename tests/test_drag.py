"""Verify that mouse gestures start a drag, not just that drop handlers work."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt, QPointF, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QListWidgetItem

from paperdesk.window import PhotoList
from paperdesk.engine import Photo


def test_mouse_movement_starts_a_drag():
    app = QApplication.instance() or QApplication([])
    class Probe(PhotoList):
        def startDrag(self, actions):
            self.started += 1
    view = Probe()
    view.started = 0
    view.resize(500, 300)
    item = QListWidgetItem()
    item.setData(Qt.ItemDataRole.UserRole, Photo("one", "a", "a", "a", 100, 100, 0, b""))
    view.addItem(item)
    view.show()
    app.processEvents()
    start = QPointF(view.visualItemRect(item).center())
    end = start + QPointF(100, 30)
    for kind, position, button, buttons in [
        (QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseMove, end, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton),
        (QEvent.Type.MouseButtonRelease, end, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton),
    ]:
        event = QMouseEvent(kind, position, position, position, button, buttons, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(view.viewport(), event)
        app.processEvents()
    assert view.started == 1
    view.close()
