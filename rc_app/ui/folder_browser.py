"""Read-only in-app browsing for an atomic folder resource."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QStyle,
    QVBoxLayout,
)

from library import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS
from rc_app.ui.player import MediaPreview
from rc_app.ui.theme import button, label
from rc_app.ui.thumbnails import ThumbnailStore


class FolderBrowserDialog(QDialog):
    """Browse a folder resource without indexing or modifying its contents."""

    def __init__(self, root: str, parent=None, cover_callback=None):
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
        self.cover_callback = cover_callback
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
        self.stats = label("", "muted")
        self.stats.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.stats.setMinimumWidth(245)
        top.addWidget(self.stats)
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
        self.listing.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.listing.customContextMenuRequested.connect(self.show_item_menu)
        layout.addWidget(self.listing, 1)

        self.thumbnails = ThumbnailStore(self)
        self.thumbnails.changed.connect(self._thumbnail_changed)
        self._style = self.style()
        self._player_windows = set()
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
            self.stats.setText("无法读取内容")
            self.listing.addItem(f"无法读取此文件夹：{exc}")
            return

        image_count = 0
        video_count = 0
        folder_count = 0
        for path in entries:
            try:
                if path.is_symlink() or not self._inside_root(path):
                    continue
                if path.is_dir():
                    folder_count += 1
                elif path.is_file():
                    suffix = path.suffix.lower()
                    if suffix in IMAGE_EXTENSIONS:
                        image_count += 1
                    elif suffix in VIDEO_EXTENSIONS:
                        video_count += 1
            except OSError:
                continue
        self.stats.setText(
            f"图片 {image_count}  ·  视频 {video_count}  ·  子文件夹 {folder_count}"
        )

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

    def show_item_menu(self, point):
        item = self.listing.itemAt(point)
        if item is None:
            return
        resource = item.data(Qt.ItemDataRole.UserRole) or {}
        path = Path(resource.get("path", "")).resolve()
        if not path or not self._inside_root(path) or path == self.root:
            return
        menu = QMenu(self)
        if resource.get("type") == "image" and self.cover_callback:
            menu.addAction("设为此文件夹资源封面", lambda: self.cover_callback(resource, None))
            menu.addSeparator()
        menu.addAction("重命名", lambda: self.rename_item(resource))
        menu.exec(self.listing.viewport().mapToGlobal(point))

    def rename_item(self, resource):
        """Rename a direct child while keeping all changes inside this viewer's root."""
        source = Path(resource.get("path", "")).resolve()
        if not source.exists() or source == self.root or not self._inside_root(source):
            return
        name, accepted = QInputDialog.getText(self, "重命名", "新的名称", text=source.name)
        if not accepted:
            return
        name = name.strip()
        if not name or name in {".", ".."} or Path(name).name != name:
            QMessageBox.warning(self, "无法重命名", "名称不能为空，且不能包含路径分隔符。")
            return
        destination = source.with_name(name)
        if destination == source:
            return
        if destination.exists():
            QMessageBox.warning(self, "无法重命名", "目标名称已存在，请换一个名称。")
            return
        try:
            source.rename(destination)
        except OSError as exc:
            QMessageBox.warning(self, "无法重命名", f"重命名失败：{exc}")
            return
        if source == self.current:
            self.current = destination
        self.refresh()

    def closeEvent(self, event):
        for player in list(self._player_windows):
            player.close()
        self._player_windows.clear()
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
        player = MediaPreview(resources, position, cover_callback=self.cover_callback)
        self._player_windows.add(player)
        player.finished.connect(lambda _result, view=player: self._player_windows.discard(view))
        player.show()
        player.raise_()
        player.activateWindow()
