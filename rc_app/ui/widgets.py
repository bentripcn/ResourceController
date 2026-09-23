"""rc_app.ui.widgets: extracted workbench component."""

from __future__ import annotations

import json

from PySide6.QtCore import QEvent, QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QDrag, QFont, QPainter, QPainterPath, QPen, QPixmap, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QStyle,
    QStyledItemDelegate,
    QTreeWidget,
    QWidget,
    QWidgetAction,
    QPushButton,
    QVBoxLayout,
)

from rc_app.ui.theme import BLUE, INK, TYPE_LABELS, app_logo, button, format_size, icon, label


class CardDelegate(QStyledItemDelegate):
    def __init__(self, thumbnails, parent=None):
        super().__init__(parent)
        self.thumbnails = thumbnails

    def sizeHint(self, option, index):
        return QSize(224, 220)

    def paint(self, p, option, index):
        r = index.data(Qt.ItemDataRole.UserRole)
        if not r:
            return
        p.save()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(option.rect).adjusted(6, 6, -6, -6)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        p.setPen(
            QPen(
                QColor("#83adfc" if selected else "#dfe5ed" if hover else "#e8ebf0"),
                1.4 if selected else 1,
            )
        )
        p.setBrush(QColor("#f7faff" if selected else "#ffffff"))
        p.drawRoundedRect(box, 11, 11)
        image_box = box.adjusted(5, 5, -5, -64)
        path = QPainterPath()
        path.addRoundedRect(image_box, 8, 8)
        p.setClipPath(path)
        p.fillRect(
            image_box, QColor({"folder": "#f0f2f8", "video": "#ecf0f7"}.get(r["type"], "#edf0f4"))
        )
        source = r.get("_cover_path") or (r["path"] if r["type"] in {"image", "video"} else None)
        picture = self.thumbnails.image(source, str(r.get("mtime", "")))
        if picture is not None and not picture.isNull():
            scaled = picture.scaled(
                image_box.size().toSize(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            p.drawImage(
                QPoint(
                    int(image_box.center().x() - scaled.width() / 2),
                    int(image_box.center().y() - scaled.height() / 2),
                ),
                scaled,
            )
        else:
            glyph = icon(r["type"], "#b4becf", 44)
            glyph.paint(
                p, int(image_box.center().x() - 22), int(image_box.center().y() - 22), 44, 44
            )
            p.setPen(QColor("#a2acbe"))
            p.setFont(QFont("Microsoft YaHei UI", 8))
            text = "文件夹" if r["type"] == "folder" else r["extension"].lstrip(".").upper()
            p.drawText(image_box.adjusted(0, 55, 0, 0), Qt.AlignmentFlag.AlignCenter, text)
        p.setClipping(False)
        badge = QRectF(image_box.left() + 9, image_box.top() + 9, 27, 24)
        p.setPen(QPen(QColor("#dce2eb"), 1))
        p.setBrush(QColor("#ffffff"))
        p.drawRoundedRect(badge, 7, 7)
        p.setPen(QColor({"A": "#298165", "B": "#4a73b4", "C": "#a98449"}.get(r["grade"], "#9aa4b3")))
        font = QFont("Segoe UI", 9)
        font.setBold(True)
        p.setFont(font)
        p.drawText(badge, Qt.AlignmentFlag.AlignCenter, r["grade"] or "—")
        if selected:
            # Keep a persistent accent edge in addition to the check mark;
            # this remains visible for keyboard selection and low-contrast
            # thumbnails where a white check badge can otherwise disappear.
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(BLUE))
            p.drawRoundedRect(QRectF(box.left(), box.top() + 20, 3, 48), 1.5, 1.5)
            circle = QRectF(image_box.right() - 31, image_box.top() + 9, 22, 22)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(BLUE))
            p.drawEllipse(circle)
            icon("check", "#ffffff", 16).paint(p, int(circle.x() + 3), int(circle.y() + 3), 16, 16)
        font = QFont("Microsoft YaHei UI", 9)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor(INK))
        title_box = QRectF(box.left() + 13, image_box.bottom() + 9, box.width() - 26, 23)
        p.drawText(
            title_box,
            Qt.AlignmentFlag.AlignVCenter,
            p.fontMetrics().elidedText(
                r["name"], Qt.TextElideMode.ElideRight, int(title_box.width())
            ),
        )
        p.setFont(QFont("Microsoft YaHei UI", 8))
        p.setPen(QColor("#9199a7"))
        detail = TYPE_LABELS[r["type"]]
        if r["tags"]:
            detail += "  ·  " + "  ".join(f"[{tag}]" for tag in r["tags"])
        if r["type"] != "folder":
            detail += "  ·  " + format_size(r["size"])
        detail_box = title_box.translated(0, 24)
        p.drawText(
            detail_box,
            Qt.AlignmentFlag.AlignVCenter,
            p.fontMetrics().elidedText(
                detail, Qt.TextElideMode.ElideRight, int(detail_box.width())
            ),
        )
        p.restore()


class ModernComboBox(QComboBox):
    """Compact menu-backed selector with predictable cross-platform rendering."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(38)
        self._popup_menu = None

    def showPopup(self):
        if self._popup_menu is not None:
            self._popup_menu.hide()
        menu = QMenu(self)
        menu.setObjectName("comboMenu")
        menu.setMinimumWidth(self.width())
        for row in range(self.count()):
            action = menu.addAction(self.itemText(row))
            action.setCheckable(True)
            action.setChecked(row == self.currentIndex())
            action.setEnabled(bool(self.model().flags(self.model().index(row, 0)) & Qt.ItemFlag.ItemIsEnabled))

        def choose(action):
            try:
                index = menu.actions().index(action)
            except ValueError:
                return
            if action.isEnabled():
                self.setCurrentIndex(index)

        menu.triggered.connect(choose)
        menu.aboutToHide.connect(lambda: setattr(self, "_popup_menu", None))
        self._popup_menu = menu
        menu.popup(self.mapToGlobal(QPoint(0, self.height() + 4)))

    def hidePopup(self):
        if self._popup_menu is not None:
            self._popup_menu.hide()
            self._popup_menu = None
        else:
            super().hidePopup()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isEnabled():
            self.showPopup()
            event.accept()
            return
        super().mousePressEvent(event)


class MultiTagComboBox(ModernComboBox):
    """A searchable, checkable tag filter that keeps the popup open."""

    selectionChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tag_items = []
        self._selected = set()

    def set_tags(self, tags, selected=None):
        self._tag_items = [(str(t["name"]), int(t.get("count", 0))) for t in tags]
        self._selected = set(selected or ()) & {name for name, _ in self._tag_items}
        self._update_text()

    def selected_tags(self):
        return sorted(self._selected, key=str.casefold)

    def _update_text(self):
        if not self._selected:
            text = "全部标签"
        elif len(self._selected) == 1:
            text = "#" + next(iter(self._selected))
        else:
            text = f"已选 {len(self._selected)} 个标签"
        blocked = self.blockSignals(True)
        self.clear()
        self.addItem(text)
        self.setCurrentIndex(0)
        self.blockSignals(blocked)
        self.setProperty("hasSelection", bool(self._selected))
        self.style().unpolish(self)
        self.style().polish(self)

    def showPopup(self):
        menu = QMenu(self)
        menu.setObjectName("comboMenu")
        menu.setMinimumWidth(max(260, self.width()))
        panel = QWidget(menu)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(8, 8, 8, 8)
        panel_layout.setSpacing(7)
        listing = QListWidget(panel)
        listing.setObjectName("tagFilterList")
        listing.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        listing.setMaximumHeight(320)
        all_item = QListWidgetItem("全部标签")
        all_item.setSelected(not self._selected)
        listing.addItem(all_item)
        for name, count in self._tag_items:
            item = QListWidgetItem(f"#{name}   {count}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            item.setSelected(name in self._selected)
            listing.addItem(item)
        panel_layout.addWidget(listing)
        action = QWidgetAction(menu)
        action.setDefaultWidget(panel)
        menu.addAction(action)

        def toggle(item):
            if item is all_item:
                self._selected.clear()
                listing.clearSelection()
                all_item.setSelected(True)
            else:
                all_item.setSelected(False)
                name = str(item.data(Qt.ItemDataRole.UserRole))
                if name in self._selected:
                    self._selected.discard(name)
                    item.setSelected(False)
                else:
                    self._selected.add(name)
                    item.setSelected(True)
                if not self._selected:
                    all_item.setSelected(True)
            self._update_text()
            self.selectionChanged.emit()

        listing.itemClicked.connect(toggle)
        menu.aboutToHide.connect(lambda: setattr(self, "_popup_menu", None))
        self._popup_menu = menu
        menu.popup(self.mapToGlobal(QPoint(0, self.height() + 4)))


class SegmentedGrade(QWidget):
    currentIndexChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._buttons = []
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        for index, text in enumerate(("A", "B", "C")):
            btn = QPushButton(text, self)
            btn.setCheckable(True)
            btn.setObjectName("segment")
            # Match the roomy iOS segmented control proportions: the text
            # remains centered while every segment keeps the same hit area.
            btn.setFixedSize(49, 40)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.clicked.connect(lambda _=False, i=index: self._choose(i))
            row.addWidget(btn)
            self._buttons.append(btn)
        self.setFixedWidth(153)
        self.setFixedHeight(46)
        self._selected = set()

    def _choose(self, index):
        if index in self._selected:
            self._selected.remove(index)
        else:
            self._selected.add(index)
        for i, btn in enumerate(self._buttons):
            btn.setChecked(i in self._selected)
        self.currentIndexChanged.emit(index)

    def currentData(self):
        return ",".join(self.selectedData())

    def selectedData(self):
        return [("A", "B", "C")[i] for i in sorted(self._selected)]

    def currentIndex(self):
        return next(iter(sorted(self._selected)), 0)

    def setCurrentIndex(self, index):
        self._selected.clear()
        if index is not None and int(index) >= 0:
            self._selected.add(max(0, min(2, int(index))))
        for i, btn in enumerate(self._buttons):
            btn.setChecked(i in self._selected)

    def setSelectedData(self, values):
        self._selected = {"ABC".index(value) for value in values if value in "ABC"}
        for i, btn in enumerate(self._buttons):
            btn.setChecked(i in self._selected)

class TagChipDelegate(QStyledItemDelegate):
    deleteRequested = Signal(str)

    def sizeHint(self, option, index):
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        width = min(220, max(118, option.fontMetrics.horizontalAdvance(text) + 78))
        return QSize(width, 38)

    @staticmethod
    def close_rect(rect):
        return QRectF(rect.right() - 25, rect.top() + 10, 18, 18)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(option.rect).adjusted(1, 1, -1, -1)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.setPen(QPen(QColor("#c9dafb" if hovered else "#d7e3fa"), 1))
        painter.setBrush(QColor("#edf4ff" if hovered else "#f4f7fc"))
        painter.drawRoundedRect(box, 11, 11)
        name = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        count = str(index.data(Qt.ItemDataRole.UserRole + 1) or 0)
        name_box = QRectF(box.left() + 12, box.top(), box.width() - 77, box.height())
        painter.setPen(QColor("#2459b6"))
        font = QFont("Microsoft YaHei UI", 9)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            name_box,
            Qt.AlignmentFlag.AlignVCenter,
            painter.fontMetrics().elidedText("#" + name, Qt.TextElideMode.ElideRight, int(name_box.width())),
        )
        count_box = QRectF(box.right() - 60, box.top(), 25, box.height())
        painter.setPen(QColor("#7d8ca4"))
        painter.setFont(QFont("Microsoft YaHei UI", 8))
        painter.drawText(count_box, Qt.AlignmentFlag.AlignCenter, count)
        close = self.close_rect(box)
        painter.setPen(QPen(QColor("#6f7d92" if hovered else "#9aa6b8"), 1.15, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(int(close.left() + 5), int(close.top() + 5), int(close.right() - 5), int(close.bottom() - 5))
        painter.drawLine(int(close.right() - 5), int(close.top() + 5), int(close.left() + 5), int(close.bottom() - 5))
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if (
            event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
            and self.close_rect(QRectF(option.rect)).contains(event.position())
        ):
            self.deleteRequested.emit(str(index.data(Qt.ItemDataRole.DisplayRole)))
            return True
        return False


class TagChipView(QListView):
    deleteRequested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._model = QStandardItemModel(self)
        self.setModel(self._model)
        delegate = TagChipDelegate(self)
        delegate.deleteRequested.connect(self.deleteRequested)
        self.setItemDelegate(delegate)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setUniformItemSizes(False)
        self.setSpacing(7)
        self.setMouseTracking(True)
        self.setStyleSheet("QListView { background: transparent; border: none; }")

    def set_tags(self, tags):
        self._model.clear()
        for tag in tags:
            item = QStandardItem(tag["name"])
            item.setData(tag["count"], Qt.ItemDataRole.UserRole + 1)
            item.setEditable(False)
            self._model.appendRow(item)


class CategoryTree(QTreeWidget):
    resourcesDropped = Signal(list, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setIndentation(15)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-resource-controller-ids"):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item and item.data(0, Qt.ItemDataRole.UserRole) is not None:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if item and event.mimeData().hasFormat("application/x-resource-controller-ids"):
            ids = json.loads(bytes(event.mimeData().data("application/x-resource-controller-ids")))
            self.resourcesDropped.emit(ids, item.data(0, Qt.ItemDataRole.UserRole))
            event.acceptProposedAction()


class ResourceGrid(QListView):
    """Resource grid with a compact drag preview."""

    gradeRequested = Signal(int)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            index = self.indexAt(event.position().toPoint())
            if index.isValid():
                rect = self.visualRect(index)
                point = event.position().toPoint()
                if QRectF(rect.left() + 16, rect.top() + 16, 35, 32).contains(point):
                    self.gradeRequested.emit(index.row())
                    event.accept()
                    return
        super().mousePressEvent(event)

    def startDrag(self, supported_actions):
        indexes = self.selectionModel().selectedIndexes()
        if not indexes or not self.model():
            return
        mime = self.model().mimeData(indexes)
        if mime is None:
            return
        count = len({index.row() for index in indexes})
        pixmap = QPixmap(112, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor("#c9dcff"), 1))
        painter.setBrush(QColor("#f2f7ff"))
        painter.drawRoundedRect(QRectF(0.5, 0.5, 111, 31), 9, 9)
        painter.setPen(QColor("#2467d8"))
        painter.setFont(QFont("Microsoft YaHei UI", 10))
        painter.drawText(QRectF(10, 0, 92, 32), Qt.AlignmentFlag.AlignVCenter, f"移动 {count} 项")
        painter.end()
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(pixmap)
        drag.setHotSpot(QPoint(12, 16))
        drag.exec(Qt.DropAction.MoveAction)


class TitleBar(QFrame):
    def __init__(self, window):
        super().__init__()
        self.window = window
        self.setObjectName("titlebar")
        self.setFixedHeight(42)
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 2, 10, 2)
        row.setSpacing(7)
        mark = QLabel()
        mark.setFixedSize(28, 28)
        mark.setPixmap(app_logo().pixmap(28, 28))
        mark.setScaledContents(True)
        row.addWidget(mark)
        row.addWidget(label("资源整理器", "detailTitle"))
        row.addStretch()
        row.addSpacing(8)
        for glyph, callback, name, tip in [
            ("minimize", window.showMinimized, "windowControl", "最小化"),
            ("maximize", window.toggle_maximized, "windowControl", "最大化"),
            ("close", window.close, "closeControl", "关闭"),
        ]:
            btn = button("", callback, glyph=glyph, kind=name)
            btn.setToolTip(tip)
            btn.setFixedSize(31, 27)
            row.addWidget(btn)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.window.windowHandle():
            self.window.windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.window.toggle_maximized()


class ReviewDialog(QDialog):
    def __init__(self, title, plan, parent=None):
        super().__init__(parent)
        self.setWindowTitle("确认操作")
        self.resize(760, 460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(25, 24, 25, 24)
        layout.setSpacing(14)
        layout.addWidget(label(title, "detailTitle"))
        count = plan.get("count", len(plan.get("changes", [])))
        summary = label(f"即将影响 {count} 项。确认后执行，完成后可从操作记录撤销。", "muted")
        summary.setWordWrap(True)
        layout.addWidget(summary)
        listing = QPlainTextEdit()
        listing.setReadOnly(True)
        lines = []
        for change in plan.get("changes", []):
            if "from" in change:
                lines.append(f"{change['from']}\n    → {change['to']}")
            elif change.get("action") == "mkdir":
                lines.append(f"创建文件夹  {change.get('path', '')}")
            else:
                lines.append(f"更新记录  {change.get('path', '')}")
        listing.setPlainText("\n\n".join(lines) or "本次操作只更新程序中的记录。")
        layout.addWidget(listing)
        actions = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        actions.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        actions.button(QDialogButtonBox.StandardButton.Ok).setText("确认执行")
        actions.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primary")
        actions.accepted.connect(self.accept)
        actions.rejected.connect(self.reject)
        layout.addWidget(actions)
