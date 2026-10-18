"""Read-only in-app browsing for an atomic folder resource."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QStyle,
    QVBoxLayout,
)

from library import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS
from rc_app.ui.player import MediaPreview
from rc_app.ui.theme import button, label
from rc_app.ui.thumbnails import ThumbnailStore


class FolderBrowserDialog(QDialog):
    """Browse a folder resource without indexing or modifying its contents."""

    def __init__(self, root: str, parent=None):
        super().__init__(parent)
        # QDialog defaults to a close-only title bar on Windows. Explicitly
        # enable the standard three system controls for this top-level viewer.
        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        self.root = Path(root).expanduser().resolve()
        self.current = self.root
        self.setWindowTitle(self.root.name or str(self.root))
        self.resize(960, 680)
        self.setMinimumSize(620, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 18)
        layout.setSpacing(12)
        top = QHBoxLayout()
        self.up_button = button("返回上层", self.go_up, glyph="arrow")
        top.addWidget(self.up_button)
        self.location = label(str(self.current), "detailTitle")
        self.location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        top.addWidget(self.location, 1)
        layout.addLayout(top)

        self.listing = QListWidget()
        self.listing.setObjectName("folderBrowserList")
        self.listing.setViewMode(QListWidget.ViewMode.IconMode)
        self.listing.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.listing.setMovement(QListWidget.Movement.Static)
        self.listing.setWrapping(True)
        self.listing.setWordWrap(True)
        self.listing.setUniformItemSizes(True)
        self.listing.setSpacing(8)
        self.listing.itemDoubleClicked.connect(self.open_item)
        layout.addWidget(self.listing, 1)

        self.thumbnails = ThumbnailStore(self)
        self.thumbnails.changed.connect(self._thumbnail_changed)
        self._style = self.style()
        self.listing.setIconSize(QSize(144, 100))
        self.listing.setGridSize(QSize(176, 148))
        self.refresh()

    def _inside_root(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.root)
            return True
        except (OSError, ValueError):
            return False

    def refresh(self):
        if not self._inside_root(self.current) or not self.current.is_dir():
            self.current = self.root
        self.location.setText(str(self.current))
        self.up_button.setEnabled(self.current != self.root)
        self.listing.clear()
        media = []
        try:
            entries = sorted(self.current.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold()))
        except OSError as exc:
            self.listing.addItem(f"无法读取此文件夹：{exc}")
            return

        for path in entries:
            try:
                if path.is_symlink() or not self._inside_root(path):
                    continue
                if path.is_dir():
                    resource = {"id": str(path), "name": path.name, "path": str(path), "type": "folder"}
                    item = QListWidgetItem(self._style.standardIcon(QStyle.StandardPixmap.SP_DirIcon), path.name)
                elif path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS | VIDEO_EXTENSIONS:
                    media_type = "image" if path.suffix.lower() in IMAGE_EXTENSIONS else "video"
                    resource = {
                        "id": str(path),
                        "name": path.name,
                        "path": str(path),
                        "type": media_type,
                        "size": path.stat().st_size,
                        "extension": path.suffix,
                        "grade": "",
                        "tags": [],
                    }
                    media.append(resource)
                    item = QListWidgetItem()
                    thumbnail = self.thumbnails.image(str(path))
                    if thumbnail is not None and not thumbnail.isNull():
                        item.setIcon(QIcon())
                        item.setData(Qt.ItemDataRole.UserRole + 1, thumbnail)
                    item.setText(path.name)
                else:
                    continue
                item.setData(Qt.ItemDataRole.UserRole, resource)
                item.setToolTip(str(path))
                item.setSizeHint(self.listing.gridSize())
                self.listing.addItem(item)
            except OSError:
                continue
        self._media = media
        self._thumbnail_changed("")

    def _thumbnail_changed(self, path):
        for index in range(self.listing.count()):
            item = self.listing.item(index)
            resource = item.data(Qt.ItemDataRole.UserRole) or {}
            if resource.get("type") not in {"image", "video"}:
                continue
            if path and resource.get("path") != path:
                continue
            image = self.thumbnails.image(resource["path"])
            if image is not None and not image.isNull():
                item.setIcon(QIcon(QPixmap.fromImage(image)))
                item.setData(Qt.ItemDataRole.UserRole + 1, image)
                item.setSizeHint(self.listing.gridSize())
        self.listing.viewport().update()

    def go_up(self):
        if self.current == self.root:
            return
        parent = self.current.parent
        if self._inside_root(parent):
            self.current = parent
            self.refresh()

    def closeEvent(self, event):
        self.thumbnails.shutdown()
        super().closeEvent(event)

    def open_item(self, item):
        resource = item.data(Qt.ItemDataRole.UserRole)
        if not resource:
            return
        path = Path(resource["path"]).resolve()
        if not self._inside_root(path):
            return
        if resource["type"] == "folder":
            self.current = path
            self.refresh()
            return
        resources = self._media
        position = next((index for index, row in enumerate(resources) if row["path"] == str(path)), 0)
        MediaPreview(resources, position, self).exec()
