"""Grouped duplicate comparison with persistent, reversible discard actions."""

from pathlib import Path

from PySide6.QtCore import QEvent, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QPlainTextEdit,
    QStyle,
    QStyledItemDelegate,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from .player import MediaPreview
from .theme import button, format_size, icon, label
from .thumbnails import ThumbnailStore


class DuplicateRowDelegate(QStyledItemDelegate):
    @staticmethod
    def check_rect(rect):
        return QRectF(rect.center().x() - 8, rect.center().y() - 8, 16, 16)

    def sizeHint(self, option, index):
        resource = index.siblingAtColumn(0).data(Qt.ItemDataRole.UserRole)
        return QSize(100, 90 if resource else 38)

    def paint(self, painter, option, index):
        resource = index.siblingAtColumn(0).data(Qt.ItemDataRole.UserRole)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.fillRect(
            option.rect,
            QColor("#edf3ff" if selected else "#f7f9fc" if hovered or not resource else "#ffffff"),
        )
        painter.setPen(QColor("#edf0f4"))
        painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())
        rect = QRectF(option.rect).adjusted(10, 0, -10, 0)
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
            image = index.siblingAtColumn(0).data(Qt.ItemDataRole.UserRole + 1)
            if image is not None and not image.isNull():
                pixmap = QPixmap.fromImage(image)
                target = QRectF(option.rect).adjusted(7, 7, -7, -7)
                scaled = pixmap.scaled(
                    target.size().toSize(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                painter.drawPixmap(
                    QRectF(
                        target.center().x() - scaled.width() / 2,
                        target.center().y() - scaled.height() / 2,
                        scaled.width(),
                        scaled.height(),
                    ),
                    scaled,
                    QRectF(scaled.rect()),
                )
        elif index.column() == 2:
            path = Path(resource["path"])
            painter.setPen(QColor("#26354a"))
            painter.drawText(
                rect.adjusted(0, 15, 0, -43),
                Qt.AlignmentFlag.AlignVCenter,
                option.fontMetrics.elidedText(
                    path.name, Qt.TextElideMode.ElideRight, int(rect.width())
                ),
            )
            painter.setPen(QColor("#8b95a5"))
            painter.drawText(
                rect.adjusted(0, 43, 0, -14),
                Qt.AlignmentFlag.AlignVCenter,
                option.fontMetrics.elidedText(
                    str(path.parent), Qt.TextElideMode.ElideMiddle, int(rect.width())
                ),
            )
        else:
            painter.setPen(QColor("#64748b"))
            painter.drawText(rect, Qt.AlignmentFlag.AlignVCenter, str(index.data() or "—"))
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if index.column() != 0 or not index.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            return False
        click = (
            event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
        )
        key = event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Space
        if click or key:
            state = index.data(Qt.ItemDataRole.CheckStateRole)
            checked = state == Qt.CheckState.Checked or state == Qt.CheckState.Checked.value
            model.setData(
                index,
                Qt.CheckState.Unchecked if checked else Qt.CheckState.Checked,
                Qt.ItemDataRole.CheckStateRole,
            )
            return True
        return False


class DuplicateResultsDialog(QDialog):
    discardRequested = Signal(object)
    mergeRequested = Signal(object)

    def __init__(self, result, parent=None, thumbnail_store=None):
        super().__init__(parent)
        self.result = result
        self._owns_thumbnail_store = thumbnail_store is None
        self.thumbnail_store = thumbnail_store or ThumbnailStore(self)
        self.setWindowTitle("重复资源检查结果")
        self.resize(1120, 690)
        self.setMinimumSize(720, 460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 20)
        layout.setSpacing(14)
        self.heading = label("", "detailTitle")
        layout.addWidget(self.heading)
        self.status = label("", "muted")
        if result.get("temporary") or result.get("cancelled"):
            layout.addWidget(self.status)
        self.listing = QTreeWidget()
        self.listing.setObjectName("duplicateList")
        self.listing.setHeaderLabels(["", "预览", "资源名称 / 所在位置", "文件大小", "媒体属性", "分级", "操作"])
        self.listing.setRootIsDecorated(False)
        self.listing.setIndentation(0)
        self.listing.setMouseTracking(True)
        self.listing.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.listing.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.listing.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.listing.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.listing.setItemDelegate(DuplicateRowDelegate(self.listing))
        self.listing.setStyleSheet(
            "QTreeWidget { background: white; border: 1px solid #e5e9f0; border-radius: 10px; }"
            " QTreeWidget::item { border: none; border-radius: 0; }"
            " QHeaderView::section { background: #f7f9fc; color: #7d8898; border: none;"
            " border-bottom: 1px solid #e5e9f0; padding: 10px 8px; }"
        )
        header = self.listing.header()
        header.setStretchLastSection(False)
        for column, width in ((0, 42), (1, 94), (3, 102), (4, 205), (5, 58), (6, 118)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
            self.listing.setColumnWidth(column, width)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.listing, 1)

        if result.get("errors"):
            warnings = QPlainTextEdit("\n".join(result["errors"]))
            warnings.setReadOnly(True)
            warnings.setMaximumHeight(74)
            layout.addWidget(warnings)
        row = QHBoxLayout()
        self.preview_button = button("对比本组资源", self.preview_current, glyph="play")
        row.addWidget(self.preview_button)
        self.selection_label = label("未勾选淘汰项", "muted")
        row.addWidget(self.selection_label)
        row.addStretch()
        self.keep_one_button = button("每组仅保留一项", self.select_all_but_one, glyph="check")
        self.keep_one_button.setToolTip("每组保留列表中的第一项，其余资源加入待删选择")
        row.addWidget(self.keep_one_button)
        self.discard_button = button("移至待删区", self.discard_selected)
        self.discard_button.setEnabled(False)
        row.addWidget(self.discard_button)
        self.merge_button = button("合并两个文件夹", self.merge_folders, glyph="folder")
        self.merge_button.setVisible(bool(result.get("folder_pair")))
        row.addWidget(self.merge_button)
        row.addWidget(button("关闭", self.reject))
        layout.addLayout(row)

        self.resource_items = []
        self._build_rows()
        self.listing.itemChanged.connect(self._update_selection)
        self.listing.itemSelectionChanged.connect(self._update_selection)
        self.listing.itemDoubleClicked.connect(self._preview_item)
        self.thumbnail_store.changed.connect(self._thumbnail_changed)
        if self.resource_items:
            self.listing.setCurrentItem(self.resource_items[0], 2)
        self._update_status()
        self._update_selection()

    def closeEvent(self, event):
        if self._owns_thumbnail_store:
            self.thumbnail_store.shutdown()
        super().closeEvent(event)

    @staticmethod
    def _media_text(resource):
        details = resource.get("media_info") or {}
        width, height = details.get("width"), details.get("height")
        dimensions = f"{width} × {height}" if width and height else ""
        if resource.get("type") == "video":
            duration = details.get("duration")
            parts = [f"时长 {DuplicateResultsDialog._duration(duration)}" if duration is not None else ""]
            if dimensions:
                parts.append(dimensions)
            rate = details.get("frame_rate")
            if rate:
                parts.append(f"{rate:g} fps")
            return " · ".join(parts) or "视频属性不可用"
        return dimensions or (resource.get("type", "").upper() + " 图片")

    @staticmethod
    def _duration(seconds):
        seconds = max(0, int(float(seconds)))
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"

    def _build_rows(self):
        self.listing.clear()
        self.resource_items.clear()
        for number, group in enumerate(self.result.get("groups", []), 1):
            heading = QTreeWidgetItem([f"第 {number} 组   ·   {len(group['resources'])} 个资源"])
            heading.setData(0, Qt.ItemDataRole.UserRole, group)
            self.listing.addTopLevelItem(heading)
            heading.setFirstColumnSpanned(True)
            heading.setFlags(Qt.ItemFlag.ItemIsEnabled)
            for resource in group["resources"]:
                item = QTreeWidgetItem(
                    ["", "", "", format_size(resource.get("size", 0)), self._media_text(resource), resource.get("grade") or "—", ""]
                )
                item.setData(0, Qt.ItemDataRole.UserRole, resource)
                item.setToolTip(2, resource["path"])
                if self._is_discardable(resource):
                    item.setCheckState(0, Qt.CheckState.Unchecked)
                else:
                    # Do not call setCheckState for read-only temporary rows:
                    # Qt adds ItemIsUserCheckable automatically when a check
                    # state is assigned, even if the flag is removed later.
                    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                heading.addChild(item)
                self.resource_items.append(item)
                thumbnail = self.thumbnail_store.image(resource.get("path"))
                if thumbnail is not None:
                    item.setData(0, Qt.ItemDataRole.UserRole + 1, thumbnail)
                if self._is_discardable(resource):
                    remove = button("移至待删区", lambda _=False, row=item: self.discard_item(row), glyph="trash")
                    remove.setFixedHeight(30)
                    self.listing.setItemWidget(item, 6, remove)
        self.listing.expandAll()
        self._update_heading()

    def _is_discardable(self, resource):
        if self.result.get("read_only_temporary"):
            return False
        if resource.get("temporary"):
            return bool(self.result.get("recursive_category"))
        return True

    def _preview_item(self, item, column):
        if item.parent() and column != 0:
            self.preview_current()

    def _update_heading(self):
        count = len(self.result.get("groups", []))
        self.heading.setText(f"发现 {count} 组候选重复资源")

    def _update_status(self):
        messages = []
        temporary_kind = self.result.get("temporary_kind")
        if temporary_kind == "folder_pair":
            messages.append("双文件夹比较 · 结果只读；合并会将第二个文件夹的内容复制到第一个")
        elif temporary_kind == "recursive_category":
            messages.append("分类递归结果 · 文件夹内部的选中重复文件会单独移入待删区，可撤销")
        elif temporary_kind == "single_folder":
            messages.append("高级展开结果 · 文件夹内部资源只供预览，不能单独整理")
        if self.result.get("cancelled"):
            messages.append(f"扫描已中止 · 已检查 {self.result.get('processed', 0)} / {self.result.get('scanned', 0)} 项，当前显示已发现的重复内容")
        self.status.setText("\n".join(messages))
        self.status.setVisible(bool(messages))

    def _thumbnail_changed(self, path):
        for item in self.resource_items:
            resource = item.data(0, Qt.ItemDataRole.UserRole) or {}
            if path and resource.get("path") != path:
                continue
            image = self.thumbnail_store.image(resource.get("path"))
            if image is not None:
                item.setData(0, Qt.ItemDataRole.UserRole + 1, image)
        self.listing.viewport().update()

    def selected_resources(self):
        return [
            item.data(0, Qt.ItemDataRole.UserRole)
            for item in self.resource_items
            if item.checkState(0) == Qt.CheckState.Checked
            and self._is_discardable(item.data(0, Qt.ItemDataRole.UserRole) or {})
        ]

    def selected_ids(self):
        return [resource["id"] for resource in self.selected_resources()]

    def select_all_but_one(self):
        self.listing.blockSignals(True)
        try:
            for group_index in range(self.listing.topLevelItemCount()):
                group = self.listing.topLevelItem(group_index)
                discardable = [
                    group.child(child_index)
                    for child_index in range(group.childCount())
                    if self._is_discardable(
                        group.child(child_index).data(0, Qt.ItemDataRole.UserRole) or {}
                    )
                ]
                for index, child in enumerate(discardable):
                    child.setCheckState(
                        0, Qt.CheckState.Unchecked if index == 0 else Qt.CheckState.Checked
                    )
        finally:
            self.listing.blockSignals(False)
        self._update_selection()

    def _update_selection(self, *_):
        count = len(self.selected_ids())
        self.selection_label.setText(f"已选择 {count} 项移至待删区" if count else "未勾选淘汰项")
        self.discard_button.setEnabled(bool(count))
        item = self.listing.currentItem()
        self.preview_button.setEnabled(bool(item and item.parent()))
        has_discardable = any(
            self._is_discardable(item.data(0, Qt.ItemDataRole.UserRole) or {})
            for item in self.resource_items
        )
        self.keep_one_button.setEnabled(bool(self.result.get("groups")) and has_discardable)

    def set_actions_enabled(self, enabled):
        self.keep_one_button.setEnabled(
            enabled and bool(self.result.get("groups")) and any(
                self._is_discardable(item.data(0, Qt.ItemDataRole.UserRole) or {})
                for item in self.resource_items
            )
        )
        self.discard_button.setEnabled(enabled and bool(self.selected_ids()))
        self.preview_button.setEnabled(
            enabled and self.listing.currentItem() is not None and self.listing.currentItem().parent() is not None
        )
        for item in self.resource_items:
            widget = self.listing.itemWidget(item, 6)
            if widget:
                widget.setEnabled(enabled)

    def discard_selected(self):
        resources = self.selected_resources()
        if resources:
            self.discardRequested.emit(resources)

    def merge_folders(self):
        pair = self.result.get("folder_pair")
        if pair and len(pair) == 2:
            self.mergeRequested.emit(pair)

    def discard_item(self, item):
        resource = item.data(0, Qt.ItemDataRole.UserRole)
        if resource and self._is_discardable(resource):
            self.discardRequested.emit([resource])

    def remove_resources(self, ids):
        removed = set(ids)
        kept_groups = []
        for group in self.result.get("groups", []):
            group["resources"] = [resource for resource in group["resources"] if resource.get("id") not in removed]
            if len(group["resources"]) > 1:
                kept_groups.append(group)
        self.result["groups"] = kept_groups
        self._build_rows()
        if self.resource_items:
            self.listing.setCurrentItem(self.resource_items[0], 2)
        self._update_heading()
        self._update_selection()

    def preview_current(self):
        item = self.listing.currentItem()
        if not item or not item.parent():
            return
        group = item.parent()
        resources = [
            group.child(i).data(0, Qt.ItemDataRole.UserRole) for i in range(group.childCount())
        ]
        MediaPreview(resources, group.indexOfChild(item), self).exec()
