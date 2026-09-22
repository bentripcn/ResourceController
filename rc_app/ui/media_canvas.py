"""A size-independent image/video viewport with cursor-anchored zoom."""
from PySide6.QtCore import QPointF, QRectF, QSize, QSizeF, Qt, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QGraphicsScene, QGraphicsView, QSizePolicy


class MediaCanvas(QGraphicsView):
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QGraphicsScene(self))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet("QGraphicsView { background: #15191f; border: none; }")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setMinimumSize(0, 0)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.NoAnchor)
        self.setRenderHints(QPainter.RenderHint.SmoothPixmapTransform | QPainter.RenderHint.Antialiasing)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.item = None
        self.content_size = QSizeF()
        self.zoom = 1.0
        self.message = ""
        self._pan_anchor = None
        self._pan_center = None
        self._panned = False

    def sizeHint(self):
        return QSize(320, 180)

    def minimumSizeHint(self):
        return QSize(0, 0)

    def set_video_item(self, item):
        self.item = item
        self.scene().addItem(item)
        item.nativeSizeChanged.connect(self.set_content_size)
        item.videoSink().videoFrameChanged.connect(self._video_frame_changed)

    def _video_frame_changed(self, frame):
        # Qt retains nativeSize across sources of the same dimensions, so it
        # may emit no size change when revisiting a clip after clear().
        if self.content_size.isEmpty() and frame.isValid():
            self.set_content_size(self.item.nativeSize())

    def set_content_size(self, size):
        if size.isEmpty() or size == self.content_size:
            return
        self.content_size = QSizeF(size)
        if hasattr(self.item, "setSize"):
            self.item.setSize(size)
        # Extra scene space permits anchoring even when the fitted media is
        # smaller than the viewport. Scrollbars remain hidden.
        w, h = size.width(), size.height()
        self.setSceneRect(-8 * w, -8 * h, 17 * w, 17 * h)
        self.reset_zoom()

    def set_image(self, image):
        if self.item is None:
            self.item = self.scene().addPixmap(QPixmap())
        self.item.setPixmap(QPixmap.fromImage(image))
        self.set_content_size(QSizeF(image.size()))
        self.reset_zoom()

    def clear(self):
        self.message = ""
        self.zoom = 1.0
        self.content_size = QSizeF()
        if self.item is not None and hasattr(self.item, "setPixmap"):
            self.item.setPixmap(QPixmap())
        self.resetTransform()
        self.viewport().update()

    def setText(self, message):
        self.message = message
        self.viewport().update()

    def _fit_scale(self):
        if self.content_size.isEmpty():
            return 1.0
        return min(self.viewport().width() / self.content_size.width(),
                   self.viewport().height() / self.content_size.height())

    def reset_zoom(self):
        self.zoom = 1.0
        self.resetTransform()
        factor = max(0.001, self._fit_scale())
        self.scale(factor, factor)
        self.centerOn(self.content_size.width() / 2, self.content_size.height() / 2)

    def zoom_at(self, point, steps):
        if self.content_size.isEmpty():
            return
        next_zoom = min(8.0, max(1.0, self.zoom * 1.10 ** max(-4, min(4, steps))))
        if next_zoom == self.zoom:
            return
        if next_zoom <= 1.00001:
            self.reset_zoom()
            return
        anchor = self.mapToScene(point)
        factor = next_zoom / self.zoom
        self.zoom = next_zoom
        self.scale(factor, factor)
        after = self.mapToScene(point)
        self.centerOn(self.mapToScene(self.viewport().rect().center()) + anchor - after)

    def wheelEvent(self, event):
        steps = event.pixelDelta().y() / 100 if not event.pixelDelta().isNull() else event.angleDelta().y() / 120
        self.zoom_at(event.position().toPoint(), steps)
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.zoom > 1.00001:
            self._pan_anchor = event.position().toPoint()
            self._pan_center = self.mapToScene(self.viewport().rect().center())
            self._panned = False
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan_anchor is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            current = event.position().toPoint()
            if (current - self._pan_anchor).manhattanLength() >= 3:
                self._panned = True
            if self._panned:
                anchor_scene = self.mapToScene(self._pan_anchor)
                current_scene = self.mapToScene(current)
                self.centerOn(self._pan_center + anchor_scene - current_scene)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            dragged = self._panned
            self._pan_anchor = None
            self._pan_center = None
            self.viewport().unsetCursor()
            if not dragged:
                self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def resizeEvent(self, event):
        center = self.mapToScene(self.viewport().rect().center())
        super().resizeEvent(event)
        if self.zoom == 1:
            self.reset_zoom()
        else:
            self.resetTransform()
            factor = self._fit_scale() * self.zoom
            self.scale(factor, factor)
            self.centerOn(center)

    def drawForeground(self, painter, rect):
        if self.message:
            painter.save()
            painter.resetTransform()
            painter.setPen(Qt.GlobalColor.white)
            painter.drawText(QRectF(self.viewport().rect()), Qt.AlignmentFlag.AlignCenter, self.message)
            painter.restore()
