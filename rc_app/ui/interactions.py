"""Small reusable controls for smooth scrolling and compact editing."""
from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QEvent, QObject, QPropertyAnimation, Qt, Signal
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QPushButton, QVBoxLayout


class SmoothScroll(QObject):
    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.bar = view.verticalScrollBar()
        self.animation = QPropertyAnimation(self.bar, b"value", self)
        self.animation.setDuration(160)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.target = self.bar.value()
        view.viewport().installEventFilter(self)
        self.bar.sliderPressed.connect(self.animation.stop)
        self.bar.rangeChanged.connect(self._range_changed)
        view.model().modelAboutToBeReset.connect(self.animation.stop)

    def _range_changed(self, minimum, maximum):
        self.target = max(minimum, min(maximum, self.target))
        if self.animation.state() == QAbstractAnimation.State.Running:
            self.animation.setEndValue(self.target)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.Hide):
            self.animation.stop()
        if event.type() != QEvent.Type.Wheel:
            return False
        if event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier):
            return False
        if not event.pixelDelta().isNull():
            # Touchpads already supply smooth momentum; avoid adding latency.
            self.animation.stop()
            self.bar.setValue(self.bar.value() - event.pixelDelta().y())
            event.accept()
            return True
        delta = event.angleDelta().y()
        if not delta:
            return False
        running = self.animation.state() == QAbstractAnimation.State.Running
        base = self.target if running else self.bar.value()
        offset = delta / 120 * max(1, QApplication.wheelScrollLines()) * 28
        if running and (self.target - self.bar.value()) * offset > 0:
            base = self.bar.value()  # Reverse direction immediately.
        self.target = int(max(self.bar.minimum(), min(self.bar.maximum(), base - offset)))
        self.animation.stop()
        self.animation.setStartValue(self.bar.value())
        self.animation.setEndValue(self.target)
        self.animation.start()
        event.accept()
        return True


class GradePopup(QFrame):
    chosen = Signal(str)

    def __init__(self, current, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        panel = QFrame()
        panel.setObjectName("gradePopover")
        outer.addWidget(panel)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 8)
        layout.setSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.grade_buttons = []
        for grade in "ABC":
            btn = QPushButton(grade)
            btn.setObjectName("gradeChoice")
            btn.setFixedSize(40, 36)
            btn.setCheckable(True)
            btn.setChecked(grade == current)
            btn.clicked.connect(lambda checked=False, value=grade: self._choose(value))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            row.addWidget(btn)
            self.grade_buttons.append(btn)
        layout.addLayout(row)
        self.clear_button = QPushButton("取消分级")
        self.clear_button.setObjectName("gradeClear")
        self.clear_button.setFixedHeight(30)
        self.clear_button.clicked.connect(lambda: self._choose(""))
        layout.addWidget(self.clear_button)
        self.setStyleSheet("QFrame#gradePopover { background: #ffffff; border: 1px solid #dce3ee; border-radius: 12px; } QPushButton#gradeChoice { background: #f3f5f8; border: 1px solid transparent; border-radius: 8px; padding: 0; font-size: 14px; } QPushButton#gradeChoice:hover { background: #eaf1ff; } QPushButton#gradeChoice:checked { background: #eaf1ff; border-color: #94b7fa; color: #2467d8; font-weight: 600; } QPushButton#gradeClear { background: transparent; border: none; border-radius: 6px; padding: 0; color: #7b8798; } QPushButton#gradeClear:hover { background: #f1f4f9; color: #334155; }")
        self.adjustSize()

    def _choose(self, value):
        self.hide()
        self.chosen.emit(value)
        self.close()

    def popup(self, point):
        screen = QApplication.screenAt(point) or QApplication.primaryScreen()
        if screen:
            rect = screen.availableGeometry()
            point.setX(max(rect.left(), min(point.x(), rect.right() - self.width())))
            point.setY(max(rect.top(), min(point.y(), rect.bottom() - self.height())))
        self.move(point)
        self.show()
        self.grade_buttons[0].setFocus()
