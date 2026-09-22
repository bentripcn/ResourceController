"""Grouped duplicate comparison with independent preview and discard selection."""
from pathlib import Path

from PySide6.QtCore import QEvent, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QHeaderView,
                              QPlainTextEdit, QStyle, QStyledItemDelegate,
                              QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from .player import MediaPreview
from .theme import button, format_size, icon, label


class DuplicateRowDelegate(QStyledItemDelegate):
    @staticmethod
    def check_rect(rect):
        return QRectF(rect.center().x() - 8, rect.center().y() - 8, 16, 16)

    def sizeHint(self, option, index):
        resource = index.siblingAtColumn(0).data(Qt.ItemDataRole.UserRole)
        return QSize(100, 64 if resource else 38)

    def paint(self, painter, option, index):
        resource = index.siblingAtColumn(0).data(Qt.ItemDataRole.UserRole)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.fillRect(option.rect, QColor("#edf3ff" if selected else "#f7f9fc" if hovered or not resource else "#ffffff"))
        painter.setPen(QColor("#edf0f4"))
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
        rect = QRectF(option.rect).adjusted(12, 0, -12, 0)
        if not resource:
            painter.setPen(QColor("#526176"))
            font = option.font
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter, str(index.data() or ""))
        elif index.column() == 0:
            state = index.data(Qt.ItemDataRole.CheckStateRole)
            checked = state == Qt.CheckState.Checked or state == Qt.CheckState.Checked.value
            box = self.check_rect(option.rect)
            enabled = bool(index.flags() & Qt.ItemFlag.ItemIsUserCheckable)
            painter.setPen(QPen(QColor("#3478f6" if checked else "#c4cedb"), 1.2))
            painter.setBrush(QColor("#3478f6" if checked else "#ffffff" if enabled else "#f1f3f6"))
            painter.drawRoundedRect(box, 4, 4)
            if checked:
                icon("check", "#ffffff", 12).paint(painter, box.adjusted(2, 2, -2, -2).toRect())
        elif index.column() == 1:
            path = Path(resource["path"])
            painter.setPen(QColor("#26354a"))
            painter.drawText(rect.adjusted(0, 8, 0, -30), Qt.AlignmentFlag.AlignVCenter,
                             option.fontMetrics.elidedText(path.name, Qt.TextElideMode.ElideRight, int(rect.width())))
            painter.setPen(QColor("#8b95a5"))
            painter.drawText(rect.adjusted(0, 31, 0, -7), Qt.AlignmentFlag.AlignVCenter,
                             option.fontMetrics.elidedText(str(path.parent), Qt.TextElideMode.ElideMiddle, int(rect.width())))
        else:
            painter.setPen(QColor("#64748b"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter, str(index.data() or ""))
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if index.column() != 0 or not index.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            return False
        click = event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton
        key = event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Space
        if click or key:
            state = index.data(Qt.ItemDataRole.CheckStateRole)
            checked = state == Qt.CheckState.Checked or state == Qt.CheckState.Checked.value
            model.setData(index, Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked, Qt.ItemDataRole.CheckStateRole)
            return True
        return False


class DuplicateResultsDialog(QDialog):
    def __init__(self, result, parent=None):
        super().__init__(parent)
        self.result = result
        self.setWindowTitle("重复资源检查结果")
        self.resize(920, 600)
        self.setMinimumSize(620, 400)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(16)
        layout.addWidget(label(f"发现 {len(result['groups'])} 组候选重复资源", "detailTitle"))
        if result.get("temporary"):
            layout.addWidget(label("临时展开结果 · 仅供预览", "muted"))
        self.listing = QTreeWidget()
        self.listing.setObjectName("duplicateList")
        self.listing.setHeaderLabels(["", "资源名称 / 所在文件夹", "大小", "分级"])
        self.listing.setRootIsDecorated(False)
        self.listing.setIndentation(0)
        self.listing.setMouseTracking(True)
        self.listing.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.listing.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.listing.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.listing.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.listing.setItemDelegate(DuplicateRowDelegate(self.listing))
        self.listing.setStyleSheet("QTreeWidget { background: white; border: 1px solid #e5e9f0; border-radius: 10px; } QTreeWidget::item { border: none; border-radius: 0; } QHeaderView::section { background: #f7f9fc; color: #7d8898; border: none; border-bottom: 1px solid #e5e9f0; padding: 10px 12px; }")
        header = self.listing.header()
        header.setStretchLastSection(False)
        for column, width in ((0, 44), (2, 110), (3, 70)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self.listing.setColumnWidth(column, width)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.listing, 1)
        self.resource_items = []
        for number, group in enumerate(result["groups"], 1):
            heading = QTreeWidgetItem([f"第 {number} 组   ·   {len(group['resources'])} 个资源"])
            self.listing.addTopLevelItem(heading)
            heading.setFirstColumnSpanned(True)
            heading.setFlags(Qt.ItemFlag.ItemIsEnabled)
            for resource in group["resources"]:
                item = QTreeWidgetItem(["", Path(resource["path"]).name, format_size(resource["size"]), resource.get("grade") or "—"])
                item.setData(0, Qt.ItemDataRole.UserRole, resource)
                item.setToolTip(1, resource["path"])
                item.setCheckState(0, Qt.CheckState.Unchecked)
                if result.get("temporary"):
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                heading.addChild(item)
                self.resource_items.append(item)
        self.listing.expandAll()
        self.listing.itemDoubleClicked.connect(lambda item, col: self.preview_current() if col != 0 else None)
        if result.get("errors"):
            warnings = QPlainTextEdit("\n".join(result["errors"]))
            warnings.setReadOnly(True)
            warnings.setMaximumHeight(80)
            layout.addWidget(warnings)
        row = QHBoxLayout()
        self.preview_button = button("对比本组资源", self.preview_current, glyph="play")
        row.addWidget(self.preview_button)
        self.selection_label = label("未勾选淘汰项", "muted")
        row.addWidget(self.selection_label)
        row.addStretch()
        self.discard_button = button("移至待删区", self.accept)
        self.discard_button.setEnabled(False)
        row.addWidget(self.discard_button)
        row.addWidget(button("关闭", self.reject))
        layout.addLayout(row)
        self.listing.itemChanged.connect(self._update_selection)
        self.listing.itemSelectionChanged.connect(self._update_selection)
        if self.resource_items:
            self.listing.setCurrentItem(self.resource_items[0], 1)
        self._update_selection()

    def selected_ids(self):
        return [item.data(0, Qt.ItemDataRole.UserRole)["id"] for item in self.resource_items
                if item.checkState(0) == Qt.CheckState.Checked]

    def _update_selection(self, *_):
        count = len(self.selected_ids())
        self.selection_label.setText(f"已勾选 {count} 项" if count else "未勾选淘汰项")
        self.discard_button.setEnabled(bool(count) and not self.result.get("temporary"))
        item = self.listing.currentItem()
        self.preview_button.setEnabled(bool(item and item.parent()))

    def preview_current(self):
        item = self.listing.currentItem()
        if not item or not item.parent():
            return
        group = item.parent()
        resources = [group.child(i).data(0, Qt.ItemDataRole.UserRole) for i in range(group.childCount())]
        MediaPreview(resources, group.indexOfChild(item), self).exec()
