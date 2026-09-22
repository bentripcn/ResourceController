"""rc_app.ui.models: extracted workbench component."""

from __future__ import annotations

import json

from PySide6.QtCore import QAbstractTableModel, QMimeData, QModelIndex, Qt

from rc_app.ui.theme import TYPE_LABELS, format_size, icon


class ResourceModel(QAbstractTableModel):
    HEADERS = ("资源名称", "类型", "分级", "标签", "分类", "大小")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list[dict] = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(self.HEADERS)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.rows):
            return None
        resource = self.rows[index.row()]
        if role == Qt.ItemDataRole.UserRole:
            return resource
        if role == Qt.ItemDataRole.ToolTipRole:
            return resource["path"]
        if role == Qt.ItemDataRole.DisplayRole:
            return (
                resource["name"],
                TYPE_LABELS.get(resource["type"], ""),
                resource["grade"] or "—",
                " · ".join(resource["tags"]) or "—",
                resource["category"] or "收件箱",
                "—" if resource["type"] == "folder" else format_size(resource["size"]),
            )[index.column()]
        if role == Qt.ItemDataRole.DecorationRole and index.column() == 0:
            return icon(resource["type"])
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def flags(self, index):
        return super().flags(index) | Qt.ItemFlag.ItemIsDragEnabled

    def mimeTypes(self):
        return ["application/x-resource-controller-ids"]

    def mimeData(self, indexes):
        mime = QMimeData()
        ids = list(dict.fromkeys(self.rows[i.row()]["id"] for i in indexes))
        mime.setData(self.mimeTypes()[0], json.dumps(ids).encode())
        return mime

    def supportedDragActions(self):
        return Qt.DropAction.MoveAction

    def replace(self, rows):
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()
