"""Keep wheel gestures on form controls scrolling their containing page."""
from PySide6.QtCore import QObject, QEvent, QCoreApplication, QPointF
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (QApplication, QWidget, QAbstractSlider, QScrollBar,
    QAbstractSpinBox, QComboBox, QCalendarWidget, QScrollArea)


class PageWheelGuard(QObject):
    def eventFilter(self, watched, event):
        if event.type() != QEvent.Type.Wheel or not isinstance(watched, QWidget):
            return False
        # Open dropdowns are independent popup windows: their own scrolling is intentional.
        node = watched
        protected = False
        scroll = None
        while node is not None:
            if isinstance(node, QScrollArea) and node.property('protect_form_wheel'):
                scroll = node
                break
            if isinstance(node, (QAbstractSpinBox, QComboBox, QCalendarWidget)) or (isinstance(node, QAbstractSlider) and not isinstance(node, QScrollBar)):
                protected = True
            node = node.parentWidget()
        if scroll is None or not protected or watched.window() != scroll.window():
            return False
        if not event.pixelDelta().isNull():
            pixels = event.pixelDelta()
            bar = scroll.verticalScrollBar() if pixels.y() else scroll.horizontalScrollBar()
            bar.setValue(bar.value() - (pixels.y() or pixels.x()))
            event.accept()
            return True
        viewport = scroll.viewport()
        wheel = QWheelEvent(QPointF(viewport.mapFromGlobal(event.globalPosition().toPoint())),
                            event.globalPosition(), event.pixelDelta(), event.angleDelta(),
                            event.buttons(), event.modifiers(), event.phase(), event.inverted())
        QCoreApplication.sendEvent(viewport, wheel)
        event.accept()
        return True


def protect_page(scroll):
    scroll.setProperty('protect_form_wheel', True)
    app = QApplication.instance()
    if not hasattr(app, '_form_wheel_guard'):
        app._form_wheel_guard = PageWheelGuard(app)
        app.installEventFilter(app._form_wheel_guard)
