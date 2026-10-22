"""rc_app.ui.window: extracted workbench component."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, QSignalBlocker, QSize, Qt, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QLayout,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QPushButton,
    QScrollArea,
    QSizeGrip,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStyle,
    QTableView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from library import IMAGE_EXTENSIONS, Library, LibraryError
from media_tools import make_video_poster
from rc_app.controller import LibraryController
from rc_app.models import FilterState
from rc_app.ui.duplicate_results import DuplicateResultsDialog
from rc_app.ui.folder_browser import FolderBrowserDialog
from rc_app.ui.interactions import GradePopup, SmoothScroll
from rc_app.ui.jobs import Job
from rc_app.ui.models import ResourceModel
from rc_app.ui.player import MediaPreview
from rc_app.ui.theme import BLUE, TYPE_LABELS, app_logo, button, format_size, icon, label
from rc_app.ui.thumbnails import ThumbnailStore
from rc_app.ui.widgets import CardDelegate, CategoryTree, ModernComboBox, MultiTagComboBox, ResourceGrid, ReviewDialog, SegmentedGrade, TagChipView, TitleBar


class MainWindow(QMainWindow):
    def __init__(self, data_dir=None, library=None):
        super().__init__()
        self.lib = library or (Library(data_dir) if data_dir else Library.unbound())
        self.controller = LibraryController(self.lib)
        self.setWindowTitle("资源整理器")
        self.setWindowIcon(app_logo())
        self.setWindowFlags(Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        screen = QApplication.primaryScreen()
        available = screen.availableGeometry() if screen else None
        self.setMinimumSize(1080, 690)
        self.resize(
            min(1450, available.width() - 70) if available else 1450,
            min(920, available.height() - 65) if available else 920,
        )
        self.view = "all"
        self.category = None
        self.busy = False
        self._jobs = set()
        self._folder_browsers = set()
        self._player_windows = set()
        self._closed = False
        self._refreshing = False
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.card_layout_timer = QTimer(self)
        self.card_layout_timer.setSingleShot(True)
        self.card_layout_timer.setInterval(0)
        self.card_layout_timer.timeout.connect(self.adjust_cards)
        self.thumbnails = ThumbnailStore(
            self,
            cache_dir=(self.lib.data_dir / "cache" / "thumbnails") if self.lib.data_dir else None,
        )
        self.model = ResourceModel(self)
        self._build()
        self._restore_last_library()
        self.repaint_timer = QTimer(self)
        self.repaint_timer.setSingleShot(True)
        self.repaint_timer.setInterval(24)
        self.repaint_timer.timeout.connect(self._paint_thumbnails)
        self.thumbnails.changed.connect(self.thumbnail_changed)
        self._shortcuts()
        self.refresh()
        self.status_label.setText(
            "请选择原始文件夹开始整理"
            if not self.lib.source_root
            else "资源库已就绪 · 按 F5 同步文件夹"
        )

    def _build(self):
        self.shell = QFrame()
        self.shell.setObjectName("shell")
        self.setCentralWidget(self.shell)
        outer = QVBoxLayout(self.shell)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)
        outer.addWidget(TitleBar(self))
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(3)
        self.progress.hide()
        outer.addWidget(self.progress)
        self.workspace = QWidget()
        outer.addWidget(self.workspace, 1)
        body = QHBoxLayout(self.workspace)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._sidebar())
        splitter = QSplitter(Qt.Orientation.Horizontal)
        body.addWidget(splitter, 1)
        splitter.addWidget(self._content())
        splitter.addWidget(self._inspector())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setSizes([940, 255])
        footer = QHBoxLayout()
        footer.setContentsMargins(20, 6, 5, 4)
        self.status_label = label("就绪", "muted")
        self.status_label.setStyleSheet("font-size: 11px; color: #8791a1;")
        footer.addWidget(self.status_label)
        footer.addStretch()
        footer.addWidget(QSizeGrip(self))
        outer.addLayout(footer)

    def _sidebar(self):
        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(220)
        layout = QVBoxLayout(side)
        layout.setContentsMargins(15, 24, 15, 14)
        layout.setSpacing(5)
        row = QHBoxLayout()
        row.addWidget(label("我的资源库", "detailTitle"))
        row.addStretch()
        layout.addLayout(row)
        self.library_path = label("尚未连接文件夹", "muted")
        self.library_path.setWordWrap(True)
        self.library_path.setMaximumHeight(47)
        layout.addWidget(self.library_path)
        layout.addSpacing(24)
        layout.addWidget(label("工作空间", "section"))
        layout.addSpacing(7)
        self.nav_buttons = {}
        for key, text, glyph in [
            ("all", "全部资源", "all"),
            ("inbox", "收件箱", "inbox"),
            ("trash", "待删区", "trash"),
        ]:
            nav = button(
                text, lambda checked=False, v=key: self.navigate(v), glyph=glyph, kind="nav"
            )
            nav.setCheckable(True)
            layout.addWidget(nav)
            self.nav_buttons[key] = nav
        layout.addSpacing(23)
        cat_row = QHBoxLayout()
        cat_row.addWidget(label("自定义分类", "section"))
        cat_row.addStretch()
        create = button("", self.new_category, glyph="plus", kind="quiet")
        create.setFixedSize(27, 27)
        create.setToolTip("新建分类")
        cat_row.addWidget(create)
        layout.addLayout(cat_row)
        self.category_tree = CategoryTree()
        self.category_tree.setMinimumHeight(90)
        self.category_tree.itemClicked.connect(
            lambda item, _: self.navigate("all", item.data(0, Qt.ItemDataRole.UserRole))
        )
        self.category_tree.resourcesDropped.connect(
            lambda ids, category: self.review(
                "移动到分类",
                lambda preview: self.lib.batch_update(ids, category=category, preview=preview),
            )
        )
        self.category_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.category_tree.customContextMenuRequested.connect(self.category_menu)
        layout.addWidget(self.category_tree, 1)
        layout.addSpacing(14)
        layout.addWidget(label("资源工具", "section"))
        layout.addSpacing(6)
        layout.addWidget(button("标签管理", self.manage_tags, glyph="tag", kind="nav"))
        layout.addWidget(button("重复资源检查", self.duplicates, glyph="duplicate", kind="nav"))
        layout.addSpacing(13)
        settings_btn = button("资源库设置", self.settings, glyph="settings")
        settings_btn.setToolTip("设置原始文件夹、导入导出和数据备份")
        layout.addWidget(settings_btn)
        return side

    def _content(self):
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(28, 26, 25, 10)
        layout.setSpacing(18)
        top = QHBoxLayout()
        self.breadcrumb = label("资源整理器  /  全部资源", "muted")
        top.addWidget(self.breadcrumb)
        top.addStretch()
        self.search = QLineEdit()
        self.search.setObjectName("search")
        self.search.setPlaceholderText("搜索名称、标签、分类")
        self.search.setClearButtonEnabled(True)
        self.search.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.setFixedWidth(258)
        top.addWidget(self.search)
        self.search_timer = QTimer(self)
        self.search_timer.setSingleShot(True)
        self.search_timer.setInterval(180)
        self.search_timer.timeout.connect(self.refresh_resources)
        self.search.textChanged.connect(lambda: self.search_timer.start())
        layout.addLayout(top)
        heading = QHBoxLayout()
        title_col = QVBoxLayout()
        self.page_title = label("全部资源", "title")
        title_col.addWidget(self.page_title)
        heading.addLayout(title_col)
        heading.addStretch()
        self.filter_toggle = button("隐藏筛选", self.toggle_filters, glyph="filter", kind="quiet")
        self.filter_toggle.setCheckable(True)
        self.filter_toggle.setChecked(True)
        self.filters_expanded = True
        heading.addWidget(self.filter_toggle)
        heading.addWidget(button("同步", self.scan, glyph="sync"))
        self.delete_selected_button = button("永久删除所选", self.permanently_delete_selected, glyph="trash")
        self.empty_trash_button = button("清空待删区", self.empty_trash, glyph="trash")
        self.delete_selected_button.hide()
        self.empty_trash_button.hide()
        heading.addWidget(self.delete_selected_button)
        heading.addWidget(self.empty_trash_button)
        layout.addLayout(heading)
        self.filter_panel = QWidget()
        self.filter_panel.setMinimumHeight(0)
        filter_layout = QVBoxLayout(self.filter_panel)
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(12)
        filter_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        metrics = QHBoxLayout()
        metrics.setSpacing(12)
        self.metric_labels = {}
        self.metric_frames = {}
        self.metric_filters = set()
        for key, title, glyph, color in [
            ("images", "图片", "image", "#608df1"),
            ("videos", "视频", "video", "#9a79da"),
            ("folders", "文件夹", "folder", "#b08b54"),
        ]:
            frame = QFrame()
            frame.setObjectName("metric")
            frame.setCursor(Qt.CursorShape.PointingHandCursor)
            frame.setCursor(Qt.CursorShape.PointingHandCursor)
            frame.mousePressEvent = lambda _event, k=key: self.filter_metric(k)
            row = QHBoxLayout(frame)
            row.setContentsMargins(15, 13, 15, 13)
            glyph_label = QLabel()
            glyph_label.setPixmap(icon(glyph, color, 23).pixmap(23, 23))
            row.addWidget(glyph_label)
            row.addSpacing(5)
            text_label = label(title, "muted")
            text_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            glyph_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            row.addWidget(text_label)
            row.addStretch()
            number = label("0")
            number.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            number.setStyleSheet("font-size: 21px; font-weight: 600; color: #303b4e;")
            row.addWidget(number)
            self.metric_labels[key] = number
            metrics.addWidget(frame)
            self.metric_frames[key] = frame
        filter_layout.addLayout(metrics)
        filters = QFrame()
        filters.setObjectName("filterbar")
        row = QHBoxLayout(filters)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(8)
        self.grade_filter = SegmentedGrade()
        self.grade_filter.setObjectName("gradeSegments")
        self.tag_filter = MultiTagComboBox()
        self.tag_filter.setObjectName("tagFilter")
        self.tag_filter.setMinimumWidth(180)
        self.tag_filter.setMaximumWidth(300)
        row.addWidget(self.grade_filter)
        self.grade_filter.currentIndexChanged.connect(self.refresh_resources)
        row.addWidget(self.tag_filter)
        self.tag_match = "any"
        self.tag_match_button = button("匹配任意标签", self.toggle_tag_match, kind="segment")
        self.tag_match_button.setFixedHeight(38)
        row.addWidget(self.tag_match_button)
        self.tag_filter.selectionChanged.connect(self.refresh_resources)
        row.addStretch()
        self.sort_filter = ModernComboBox()
        self.sort_filter.addItems(["名称排序", "大小排序", "分级排序"])
        self.sort_filter.setFixedWidth(180)
        self.sort_filter.currentIndexChanged.connect(self.refresh_resources)
        row.addWidget(self.sort_filter)
        self.grid_button = button("", lambda: self.change_layout(0), glyph="grid", kind="segment")
        self.grid_button.setFixedSize(52, 42)
        self.grid_button.setCheckable(True)
        self.grid_button.setChecked(True)
        self.grid_button.setToolTip("网格视图")
        self.table_button = button("", lambda: self.change_layout(1), glyph="list", kind="segment")
        self.table_button.setFixedSize(52, 42)
        self.table_button.setCheckable(True)
        self.table_button.setToolTip("列表视图")
        row.addWidget(self.grid_button)
        row.addWidget(self.table_button)
        filter_layout.addWidget(filters)
        layout.addWidget(self.filter_panel)
        self.filter_animation = QPropertyAnimation(self.filter_panel, b"maximumHeight", self)
        self.filter_animation.setDuration(180)
        self.filter_animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.filter_animation.finished.connect(self._filters_animation_finished)
        self.views = QStackedWidget()
        layout.addWidget(self.views, 1)
        self.grid = ResourceGrid()
        self.grid.setModel(self.model)
        self.grid.setViewMode(QListView.ViewMode.IconMode)
        self.grid.setResizeMode(QListView.ResizeMode.Adjust)
        self.grid.setMovement(QListView.Movement.Static)
        self.grid.setWrapping(True)
        self.grid.setSpacing(0)
        self.grid.setGridSize(QSize(224, 220))
        self.grid.setUniformItemSizes(True)
        self.grid.setItemDelegate(CardDelegate(self.thumbnails, self.grid))
        self.grid.gradeRequested.connect(self.quick_grade)
        self.grid.setMouseTracking(True)
        self.grid.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.grid.setDragEnabled(True)
        self.grid.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        # The grid's viewport can change without a QMainWindow resize: the
        # stacked view may switch from its empty page, a scrollbar may appear,
        # or the details splitter may move. Listen to the actual viewport so
        # column wrapping is recalculated from the final usable width.
        self.grid.viewport().installEventFilter(self)
        self.views.addWidget(self.grid)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setDragEnabled(True)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(49)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 65)
        self.table.setColumnWidth(2, 55)
        self.table.setColumnWidth(4, 115)
        self.table.setColumnWidth(5, 85)
        self.table.setSelectionModel(self.grid.selectionModel())
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.views.addWidget(self.table)
        for view in (self.grid, self.table):
            view.smooth_scroll = SmoothScroll(view)
            view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            view.doubleClicked.connect(lambda index: self.open_or_preview(index.row()))
            view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            view.customContextMenuRequested.connect(
                lambda point, v=view: self.resource_menu(v, point)
            )
        self.grid.selectionModel().selectionChanged.connect(self.selection_changed)
        self.empty = QWidget()
        empty_layout = QVBoxLayout(self.empty)
        empty_layout.addStretch()
        empty_icon = QLabel()
        empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_icon.setPixmap(icon("inbox", "#c0ccdf", 70).pixmap(70, 70))
        empty_layout.addWidget(empty_icon)
        self.empty_title = label("让每一份影像，都井然有序")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_title.setStyleSheet("font-size: 20px; font-weight: 600; margin-top: 15px;")
        empty_layout.addWidget(self.empty_title)
        self.empty_hint = label("选择原始文件夹，开始建立属于你的资源库。", "muted")
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.setWordWrap(True)
        empty_layout.addWidget(self.empty_hint)
        empty_row = QHBoxLayout()
        empty_row.addStretch()
        self.empty_action = button("选择原始文件夹", self.choose_root, glyph="plus", kind="primary")
        empty_row.addWidget(self.empty_action)
        empty_row.addStretch()
        empty_layout.addLayout(empty_row)
        empty_layout.addStretch()
        self.views.addWidget(self.empty)
        self.result_count = label("0 个资源", "muted")
        # Keep the count model-side for accessibility/status updates, but do
        # not render the detached footer visible in the empty inbox state.
        return content

    def _inspector(self):
        outer = QFrame()
        outer.setObjectName("inspector")
        outer.setMinimumWidth(220)
        outer.setMaximumWidth(310)
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        frame = QWidget()
        frame.setStyleSheet("background: transparent;")
        outer_layout.addWidget(scroll)
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 29, 20, 20)
        layout.setSpacing(15)
        row = QHBoxLayout()
        row.addWidget(label("资源详情", "detailTitle"))
        row.addStretch()
        layout.addLayout(row)
        self.detail_image = QLabel()
        self.detail_image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_image.setFixedHeight(178)
        self.detail_image.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed
        )
        self.detail_image.setStyleSheet("background: #edf0f5; border-radius: 10px; color: #b3bece;")
        layout.addWidget(self.detail_image)
        self.detail_name = label("选择一个资源")
        self.detail_name.setWordWrap(True)
        self.detail_name.setMinimumWidth(0)
        self.detail_name.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.detail_name.setObjectName("detailTitle")
        layout.addWidget(self.detail_name)
        self.detail_kind = label("在这里查看详细信息", "muted")
        self.detail_kind.setMinimumWidth(0)
        self.detail_kind.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(self.detail_kind)
        self.detail_grade = label("—")
        self.detail_category = label("—")
        self.detail_tags = label("—")
        self.detail_size = label("—")
        for caption, value in [
            ("分级", self.detail_grade),
            ("所在分类", self.detail_category),
            ("标签", self.detail_tags),
            ("文件大小", self.detail_size),
        ]:
            layout.addWidget(label(caption, "section"))
            value.setWordWrap(True)
            value.setMinimumWidth(0)
            value.setSizePolicy(
                QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
            )
            layout.addWidget(value)
        layout.addWidget(label("文件位置", "section"))
        self.detail_path = label("—", "muted")
        self.detail_path.setWordWrap(True)
        self.detail_path.setMinimumWidth(0)
        self.detail_path.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        self.detail_path.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.detail_path)
        layout.addStretch()
        self.cover_button = button("设置文件夹封面", self.set_cover, glyph="image", kind="quiet")
        self.cover_button.hide()
        layout.addWidget(self.cover_button)
        self.batchbar = QFrame()
        self.batchbar.setObjectName("batchbar")
        batch = QVBoxLayout(self.batchbar)
        batch.setContentsMargins(10, 10, 10, 10)
        batch.setSpacing(6)
        self.selection_count = label("已选择 0 项", "section")
        batch.addWidget(self.selection_count)
        for text, callback, glyph in [("分级 / 标签", self.edit_metadata, "tag"), ("移动到分类", self.move_resources, "folder"), ("复制到分类", self.copy_resources, "duplicate"), ("修改原名", self.rename_resources, "edit"), ("移至待删区", self.trash_resources, "trash")]:
            btn = button(text, callback, glyph=glyph, kind="quiet")
            btn.setStyleSheet("text-align: left; padding: 7px 8px;")
            batch.addWidget(btn)
        self.batchbar.hide()
        layout.addWidget(self.batchbar)
        # QScrollArea needs a fully laid-out child before taking ownership.
        scroll.setWidget(frame)
        return outer

    def _shortcuts(self):
        for key, callback in [
            ("F5", self.scan),
            ("Ctrl+Z", self.undo),
            ("Ctrl+A", self.select_all),
            ("Ctrl+F", self.search.setFocus),
            ("Delete", self.trash_resources),
            ("F2", self.rename_resources),
            ("Space", lambda: self.preview_selected()),
        ]:
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.activated.connect(callback)

    def toggle_maximized(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def showEvent(self, event):
        super().showEvent(event)
        self._enable_windows_snap()

    def _enable_windows_snap(self):
        """Keep the custom title bar while restoring Win11 snap affordances."""
        if not __import__("sys").platform.startswith("win"):
            return
        try:
            import ctypes

            hwnd = int(self.winId())
            get_style = ctypes.windll.user32.GetWindowLongPtrW
            set_style = ctypes.windll.user32.SetWindowLongPtrW
            style = get_style(hwnd, -16)  # GWL_STYLE
            WS_THICKFRAME = 0x00040000
            WS_MAXIMIZEBOX = 0x00010000
            WS_MINIMIZEBOX = 0x00020000
            set_style(hwnd, -16, style | WS_THICKFRAME | WS_MAXIMIZEBOX | WS_MINIMIZEBOX)
        except Exception:
            pass

    def _remember_paths(self):
        if not getattr(self.lib, "global_db", None):
            return
        self.lib.global_db.executemany(
            "INSERT OR REPLACE INTO app_settings VALUES (?,?)",
            [
                ("last_source_root", json.dumps(str(self.lib.source_root) if self.lib.source_root else "")),
                ("last_library_root", json.dumps(str(self.lib.library_root) if self.lib.library_root else "")),
            ],
        )
        self.lib.global_db.commit()

    def _restore_last_library(self):
        settings = self.lib.settings()
        target = str(settings.get("last_library_root") or "")
        source = str(settings.get("last_source_root") or "")
        if not target or not Path(target).is_dir():
            return
        try:
            library = self._open_library_root(target)
            if library is None:
                return
            if library.source_root and library.source_root.is_dir():
                self._remember_paths()
            elif source and Path(source).is_dir():
                library.configure(source, target)
                self._remember_paths()
        except Exception:
            # A moved or disconnected drive should not prevent the app from
            # starting; the user can choose a new library from Settings.
            return

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "grid"):
            self.schedule_card_layout()

    def eventFilter(self, watched, event):
        if (
            hasattr(self, "grid")
            and watched is self.grid.viewport()
            and event.type() in (QEvent.Type.Resize, QEvent.Type.Show)
        ):
            self.schedule_card_layout()
        return super().eventFilter(watched, event)

    def schedule_card_layout(self):
        if not self._closed:
            self.card_layout_timer.start()

    def adjust_cards(self):
        width = self.grid.viewport().width()
        if width <= 0:
            return
        # QListView lays out IconMode items against a width that reserves a
        # potential vertical scrollbar even while the public viewport still
        # reports the full width. Around a column boundary this makes Qt wrap
        # one item earlier (for example: we calculate five columns, Qt places
        # four), producing the large blank strip seen in the grid. Use the
        # style's real scrollbar extent so our column count and Qt's agree.
        scrollbar = self.grid.style().pixelMetric(
            QStyle.PixelMetric.PM_ScrollBarExtent, None, self.grid
        )
        available = max(1, width - scrollbar)
        columns = max(1, available // 224)
        card_width = max(190, available // columns)
        self.grid.setSpacing(0)
        self.grid.setGridSize(QSize(card_width, 220))
        self.grid.doItemsLayout()

    def change_layout(self, index):
        self.grid_button.setChecked(index == 0)
        self.table_button.setChecked(index == 1)
        if self.model.rows:
            self.views.setCurrentIndex(index)
        self.schedule_card_layout()

    def toggle_filters(self, checked=None):
        self.filters_expanded = not self.filters_expanded if checked is None else bool(checked)
        self.filter_animation.stop()
        start = self.filter_panel.height() if self.filter_panel.isVisible() else 0
        self.filter_panel.show()
        self.filter_panel.setMaximumHeight(start)
        self.filter_animation.setStartValue(start)
        self.filter_animation.setEndValue(self.filter_panel.sizeHint().height() if self.filters_expanded else 0)
        self._update_filter_toggle()
        self.filter_animation.start()

    def _filters_animation_finished(self):
        if self.filters_expanded:
            self.filter_panel.setMaximumHeight(16777215)
        else:
            self.filter_panel.hide()
        self.schedule_card_layout()

    def _update_filter_toggle(self):
        count = len(self.metric_filters) + len(self.grade_filter.selectedData()) + len(self.tag_filter.selected_tags())
        text = "隐藏筛选" if self.filters_expanded else "显示筛选"
        if count:
            text += f" · {count}"
        self.filter_toggle.setText(text)
        self.filter_toggle.setChecked(self.filters_expanded)

    def navigate(self, view, category=None):
        self.view, self.category = view, category
        self.refresh()

    def filter_metric(self, key):
        if key in self.metric_filters:
            self.metric_filters.remove(key)
        else:
            self.metric_filters.add(key)
        self.update_metric_styles()
        self.refresh_resources()

    def toggle_tag_match(self):
        self.tag_match = "all" if self.tag_match == "any" else "any"
        self.tag_match_button.setText(
            "匹配全部标签" if self.tag_match == "all" else "匹配任意标签"
        )
        self.refresh_resources()

    def update_metric_styles(self):
        for key, frame in getattr(self, "metric_frames", {}).items():
            frame.setProperty("selected", "true" if key in self.metric_filters else "false")
            frame.style().unpolish(frame)
            frame.style().polish(frame)
            frame.update()

    def refresh(self):
        if self._closed:
            return
        self._refreshing = True
        try:
            stats = self.lib.stats(category=self.category, view=self.view)
            nav_stats = self.lib.stats()
            for key, number in self.metric_labels.items():
                number.setText(f"{stats[key]:,}")
            root = self.lib.source_root
            target_root = self.lib.library_root
            self.library_path.setText(target_root.name if target_root else "尚未设置目标库")
            self.library_path.setToolTip(str(target_root) if target_root else "点击下方设置目标库")
            for key, nav in self.nav_buttons.items():
                text = {"all": "全部资源", "inbox": "收件箱", "trash": "待删区"}[key]
                count = nav_stats[{"all": "total", "inbox": "inbox", "trash": "trash"}[key]]
                nav.setText(f"{text}    {count:,}")
                nav.setChecked(key == self.view and self.category is None)
            self.category_tree.clear()
            category_items = {}
            categories = self.lib.categories()
            if self.category and self.category not in {c["path"] for c in categories}:
                self.category = None
            for cat in categories:
                item = QTreeWidgetItem([f"{cat['name']}  {cat['count']}"])
                item.setIcon(0, icon("folder"))
                item.setData(0, Qt.ItemDataRole.UserRole, cat["path"])
                if cat["parent"] in category_items:
                    category_items[cat["parent"]].addChild(item)
                else:
                    self.category_tree.addTopLevelItem(item)
                category_items[cat["path"]] = item
                if self.category == cat["path"]:
                    self.category_tree.setCurrentItem(item)
            self.category_tree.expandAll()
            if not categories:
                placeholder = QTreeWidgetItem(["点击 + 创建你的分类"])
                placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
                self.category_tree.addTopLevelItem(placeholder)
            selected_tags = self.tag_filter.selected_tags()
            self.tag_filter.set_tags(self.lib.tags(), selected_tags)
            title = (
                self.category.rsplit("/", 1)[-1]
                if self.category
                else {"all": "全部资源", "inbox": "收件箱", "trash": "待删区"}[self.view]
            )
            self.page_title.setText(title)
            self.delete_selected_button.setVisible(self.view == "trash")
            self.empty_trash_button.setVisible(self.view == "trash")
            self.breadcrumb.setText(
                "资源整理器  /  " + (self.category.replace("/", "  /  ") if self.category else title)
            )
        except Exception as exc:
            self.error(str(exc))
        finally:
            self._refreshing = False
        self.refresh_resources()

    def refresh_resources(self, *_):
        if self._refreshing or self.busy or self._closed:
            return
        self._update_filter_toggle()
        selected = set(self.selected_ids()) if hasattr(self, "grid") else set()
        metric_types = {"images": "image", "videos": "video", "folders": "folder"}
        selected_types = {metric_types[key] for key in self.metric_filters}
        sort = (
            "size"
            if self.sort_filter.currentIndex() == 1
            else "grade"
            if self.sort_filter.currentIndex() == 2
            else "name"
        )
        rows = self.controller.query(
            FilterState(
                category=self.category,
                view=self.view,
                grade=self.grade_filter.selectedData(),
                tags=self.tag_filter.selected_tags(),
                tag_match=self.tag_match,
                types=selected_types,
                query=self.search.text().strip(),
                sort=sort,
            )
        )
        for r in rows:
            if r["type"] == "folder":
                r["_cover_path"] = self.folder_cover_path(r)
            elif r["type"] == "video":
                r["_cover_path"] = self.lib.cover_path(r["id"])
        selection = self.grid.selectionModel()
        scroll = self.grid.verticalScrollBar().value()
        with QSignalBlocker(selection):
            self.model.replace(rows)
            for index, r in enumerate(rows):
                if r["id"] in selected:
                    selection.select(
                        self.model.index(index, 0),
                        selection.SelectionFlag.Select | selection.SelectionFlag.Rows,
                    )
        self.grid.verticalScrollBar().setValue(scroll)
        self.result_count.setText(
            f"{len(rows):,} 个资源" + ("  ·  包含子分类" if self.category else "")
        )
        self.views.setCurrentIndex((0 if self.grid_button.isChecked() else 1) if rows else 2)
        configured = bool(self.lib.source_root)
        self.empty_title.setText("这里还没有资源" if configured else "让每一份影像，都井然有序")
        self.empty_hint.setText(
            "尝试调整筛选条件，或同步原始文件夹。"
            if configured
            else "选择原始文件夹，开始建立属于你的资源库。"
        )
        self.empty_action.setVisible(not configured)
        self.selection_changed()
        self.schedule_card_layout()

    def _selected_indexes(self):
        # Icon-mode QListView selects column 0 only; selectedRows() requires all
        # six table columns and silently misses real mouse selections.
        rows = sorted({index.row() for index in self.grid.selectionModel().selectedIndexes()})
        return [self.model.index(row, 0) for row in rows if 0 <= row < self.model.rowCount()]

    def selected_ids(self):
        return [
            self.model.rows[index.row()]["id"]
            for index in self._selected_indexes()
            if index.row() < len(self.model.rows)
        ]

    def selected_resources(self):
        return [
            self.model.rows[index.row()]
            for index in self._selected_indexes()
            if index.row() < len(self.model.rows)
        ]

    def select_all(self):
        if not self.busy:
            (self.grid if self.grid_button.isChecked() else self.table).selectAll()

    def selection_changed(self, *_):
        resources = self.selected_resources()
        count = len(resources)
        self.selection_count.setText(f"已选择 {count} 项")
        self.batchbar.setVisible(count > 0 and self.view != "trash")
        self.delete_selected_button.setEnabled(count > 0 and self.view == "trash")
        self.cover_button.setVisible(
            count == 1 and resources[0]["type"] == "folder" and self.view != "trash"
        )
        if count != 1:
            self.detail_name.setText(f"已选择 {count} 个资源" if count else "选择一个资源")
            self.detail_kind.setText("使用右侧操作批量整理" if count else "在这里查看详细信息")
            for field in (
                self.detail_grade,
                self.detail_category,
                self.detail_tags,
                self.detail_size,
                self.detail_path,
            ):
                field.setText("—")
            self.detail_image.setPixmap(icon("all", "#bdc7d7", 52).pixmap(52, 52))
            return
        r = resources[0]
        self.detail_name.setText(r["name"])
        self.detail_kind.setText(
            TYPE_LABELS[r["type"]]
            + ("  /  " + r["extension"].lstrip(".").upper() if r["extension"] else "  /  原子资源")
        )
        self.detail_grade.setText(r["grade"] + " 级" if r["grade"] else "未分级")
        self.detail_category.setText(r["category"] or "收件箱")
        self.detail_tags.setText(" · ".join(r["tags"]) or "暂无标签")
        self.detail_size.setText(
            "保持内部结构" if r["type"] == "folder" else format_size(r["size"])
        )
        self.detail_path.setText(r["path"])
        source = r.get("_cover_path") or (
            self.folder_cover_path(r)
            if r["type"] == "folder"
            else (r["path"] if r["type"] in {"image", "video"} else None)
        )
        image = self.thumbnails.image(source, str(r.get("mtime", "")))
        if image is not None and not image.isNull():
            self.detail_image.setPixmap(
                QPixmap.fromImage(image).scaled(
                    self.detail_image.size() - QSize(12, 12),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            self.detail_image.setPixmap(icon(r["type"], "#b6c1d2", 52).pixmap(52, 52))

    def thumbnail_changed(self, _):
        if self._closed:
            return
        if not self.repaint_timer.isActive():
            self.repaint_timer.start()

    def _paint_thumbnails(self):
        if self._closed:
            return
        self.grid.viewport().update()
        self.selection_changed()

    def folder_cover_path(self, resource):
        """Return a display-only poster; folder contents remain unindexed."""
        try:
            cover = self.lib.cover_path(resource["id"])
            if cover:
                return cover
            # The thumbnail worker chooses a display image without scanning
            # folder contents on the GUI thread or adding them to the index.
            return resource["path"]
        except (OSError, LibraryError):
            pass
        return None

    def error(self, message):
        QMessageBox.warning(self, "操作未完成", message)

    def run_job(self, text, function, done=None, *, context=False):
        if self.busy:
            return
        self.busy = True
        self.workspace.setEnabled(False)
        self.progress.show()
        self.status_label.setText(text)
        job = Job(function, with_context=context)
        self._jobs.add(job)

        def finish(result=None, error=None):
            self._jobs.discard(job)
            self.busy = False
            self.workspace.setEnabled(True)
            self.progress.hide()
            if error:
                self.status_label.setText("操作未完成")
                self.error(error)
            else:
                self.status_label.setText("操作完成 · " + time.strftime("%H:%M"))
                self.refresh()
                if done:
                    done(result)

        job.signals.done.connect(lambda result: finish(result=result))
        job.signals.failed.connect(lambda error: finish(error=error))
        self.pool.start(job)

    def run_cancelable_job(self, text, function, done=None):
        """Run a long scan with a visible progress/cancel control."""
        if self.busy:
            return
        cancel_event = threading.Event()
        dialog = QProgressDialog(text, "中止", 0, 0, self)
        dialog.setWindowTitle("正在检查重复资源")
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        dialog.canceled.connect(cancel_event.set)
        dialog.show()
        self.busy = True
        self.workspace.setEnabled(False)
        self.progress.show()
        self.status_label.setText(text)
        job = Job(function, cancel_event=cancel_event, with_context=True)
        self._jobs.add(job)

        def update_progress(value):
            if not isinstance(value, dict):
                return
            total = int(value.get("total") or 0)
            done_value = min(total, int(value.get("done") or 0)) if total else 0
            if total:
                dialog.setRange(0, total)
                dialog.setValue(done_value)
            phase = value.get("phase") or text
            dialog.setLabelText(phase + (" · 正在中止…" if cancel_event.is_set() else ""))
            self.status_label.setText(phase)

        def finish(result=None, error=None):
            self._jobs.discard(job)
            self.busy = False
            self.workspace.setEnabled(True)
            self.progress.hide()
            dialog.close()
            dialog.deleteLater()
            if error:
                self.status_label.setText("操作未完成")
                self.error(error)
            else:
                self.status_label.setText("操作完成 · " + time.strftime("%H:%M"))
                self.refresh()
                if done:
                    done(result)

        job.signals.progress.connect(update_progress)
        job.signals.done.connect(lambda result: finish(result=result))
        job.signals.failed.connect(lambda error: finish(error=error))
        self.pool.start(job)

    def review(self, title, operation, *, confirm=False):
        if self.busy:
            return
        # Ordinary edits remain reversible during this session. Do not compute
        # a duplicate preview just to show a second
        # dialog; this keeps rename, tag and classification actions fluid.
        # Destructive actions still display their concrete file plan.
        if not confirm:
            self.run_job(title + "…", lambda: operation(False))
            return
        try:
            plan = operation(True)
        except Exception as exc:
            self.error(str(exc))
            return
        if confirm and ReviewDialog(title, plan, self).exec() != QDialog.DialogCode.Accepted:
            return
        self.run_job(title + "…", lambda: operation(False))

    def _select_item(self, title, prompt, options, current=0, parent=None):
        dialog = QDialog(parent or self)
        dialog.setWindowTitle(title)
        dialog.setMinimumWidth(400)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(22, 22, 22, 20)
        layout.setSpacing(14)
        heading = label(prompt, "detailTitle")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        selector = None
        listing = None
        if len(options) > 24:
            search = QLineEdit(dialog)
            search.setPlaceholderText("搜索名称或路径")
            layout.addWidget(search)
            listing = QListWidget(dialog)
            listing.setMaximumHeight(430)
            for option in options:
                item = QListWidgetItem(option)
                item.setToolTip(option)
                listing.addItem(item)
            listing.setCurrentRow(max(0, min(current, len(options) - 1)))
            search.textChanged.connect(
                lambda value: [
                    listing.item(i).setHidden(value.casefold() not in listing.item(i).text().casefold())
                    for i in range(listing.count())
                ]
            )
            layout.addWidget(listing, 1)
        else:
            selector = ModernComboBox(dialog)
            selector.addItems(options)
            selector.setCurrentIndex(max(0, min(current, len(options) - 1)))
            layout.addWidget(selector)
        actions = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        actions.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        actions.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        actions.accepted.connect(dialog.accept)
        actions.rejected.connect(dialog.reject)
        layout.addWidget(actions)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return "", False
        selected = listing.currentItem().text() if listing and listing.currentItem() else ""
        return (selected if listing else selector.currentText()), bool(selected or selector)

    def _select_multiple_items(self, title, prompt, options, minimum=2, maximum=None):
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.setMinimumSize(520, 430)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(22, 22, 22, 20)
        heading = label(prompt, "detailTitle")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        listing = QListWidget()
        listing.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        for option in options:
            listing.addItem(option)
        layout.addWidget(listing, 1)
        actions = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        actions.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        actions.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        actions.accepted.connect(dialog.accept)
        actions.rejected.connect(dialog.reject)
        layout.addWidget(actions)
        def update_selection_state():
            count = len(listing.selectedItems())
            actions.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
                count >= minimum and (maximum is None or count <= maximum)
            )

        listing.itemSelectionChanged.connect(update_selection_state)
        actions.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return [], False
        return [item.text() for item in listing.selectedItems()], True

    @staticmethod
    def _library_data_path(root):
        return Path(root).expanduser().resolve() / ".resource-controller-data"

    def _activate_library(self, library):
        """Replace the active repository without rebuilding the window."""
        previous = self.lib
        self.lib = library
        self.controller = LibraryController(library)
        self.thumbnails.cache.clear()
        self.thumbnails.pending.clear()
        self.thumbnails.cache_dir = (
            library.data_dir / "cache" / "thumbnails" if library.data_dir else None
        )
        self.view = "all"
        self.category = None
        if previous is not library:
            try:
                previous.close()
            except Exception:
                pass
        # A category can be removed directly in Explorer.  Repair only the
        # stale catalog rows on open; media and user-selected covers stay put.
        library.prune_stale_categories()
        self.refresh()

    def _open_library_root(self, root, expected_source=None):
        """Open an existing portable library stored inside *root*."""
        data_path = self._library_data_path(root)
        database = data_path / "library.sqlite3"
        if not database.is_file():
            return None
        library = Library(data_path)
        library._data_dir_explicit = False
        # A settings reset intentionally removes root bindings while keeping
        # the portable database. Reopening the target directory reattaches it.
        if not library.library_root:
            # The database lives at ``root/.resource-controller-data``; when
            # the user selects this folder again, restore the target binding
            # before the settings dialog reads its button text.
            library.set_library_root(root)
        if expected_source and library.source_root:
            selected = Path(expected_source).expanduser().resolve()
            if library.source_root != selected:
                library.close()
                raise LibraryError(
                    "该资源库已经绑定其他原始目录，请选择对应原始目录或新建目标库。"
                )
        self._activate_library(library)
        return library

    def choose_root(self, dialog_parent=None):
        if self.busy:
            return
        parent = dialog_parent if isinstance(dialog_parent, QWidget) else self
        previous_source = self.lib.source_root
        previous_library = self.lib.library_root
        source = QFileDialog.getExistingDirectory(
            parent, "选择原始资源文件夹", str(self.lib.source_root or Path.home())
        )
        if not source:
            return
        try:
            # Keep an explicitly configured target library when users replace
            # the source folder.  On a fresh library (or when source and target
            # were the same), configure() will continue to use the new source
            # as the target by default.
            target = (
                str(previous_library)
                if previous_library
                and previous_library.is_dir()
                and previous_library != Path(source).resolve()
                else None
            )
            managed = Path(target or source).resolve()
            if self.lib.data_dir is None:
                existing = self._open_library_root(managed, expected_source=source)
                if existing:
                    if not existing.source_root:
                        existing.configure(source, str(managed))
                    self._activate_library(existing)
                else:
                    library = Library(self._library_data_path(managed))
                    library._data_dir_explicit = False
                    library.configure(source, str(managed))
                    self._activate_library(library)
            else:
                self.lib.configure(source, target)
                self.thumbnails.cache_dir = (
                    self.lib.data_dir / "cache" / "thumbnails" if self.lib.data_dir else None
                )
        except Exception as exc:
            self.error(str(exc))
            return
        if self.lib.source_root:
            self.scan()
        else:
            self.refresh()
        self._remember_paths()

    def choose_library(self, dialog_parent=None):
        """Choose the directory that will contain user-created categories."""
        if self.busy:
            return
        parent = dialog_parent if isinstance(dialog_parent, QWidget) else self
        folder = QFileDialog.getExistingDirectory(
            parent,
            "选择或打开资源库文件夹",
            str(self.lib.library_root or self.lib.source_root or Path.home()),
        )
        if not folder:
            return
        try:
            existing = self._open_library_root(folder)
            if not existing:
                # A target library may be selected before the original folder.
                # Start its repository directly inside the selected directory;
                # configure() will attach the source later.
                if not self.lib.source_root:
                    library = Library(self._library_data_path(folder))
                    library._data_dir_explicit = False
                    library.set_library_root(folder)
                    self._activate_library(library)
                else:
                    self.lib.configure(str(self.lib.source_root), folder)
                    if self.lib.data_dir != self._library_data_path(folder):
                        self.lib._relocate_data_dir(Path(folder))
                    self.thumbnails.cache_dir = (
                        self.lib.data_dir / "cache" / "thumbnails" if self.lib.data_dir else None
                    )
        except Exception as exc:
            self.error(str(exc))
            return
        if self.lib.source_root:
            self.scan()
        else:
            self.refresh()
        self._remember_paths()

    def scan(self):
        if self.busy:
            return
        if not self.lib.source_root:
            self.status_label.setText("请选择原始文件夹后再同步")
            self.refresh()
            return

        def done(result):
            errors = result.get("errors", [])
            self.status_label.setText(
                f"同步完成 · 已索引 {result['count']} 个资源"
                + (f" · {len(errors)} 项异常" if errors else "")
            )
            if errors:
                QMessageBox.warning(self, "同步完成，部分资源无法读取", "\n".join(errors[:30]))

        self.run_job("正在同步文件夹…", self.lib.scan, done)

    def require_selection(self):
        ids = self.selected_ids()
        if not ids:
            self.status_label.setText("请先选择一个或多个资源")
        return ids

    def new_category(self):
        if self.busy:
            return
        if not self.lib.source_root:
            self.choose_root()
            return
        default = self.category + "/" if self.category else ""
        name, ok = QInputDialog.getText(
            self, "新建分类", "分类路径（使用 / 创建子分类）", text=default
        )
        if ok and name.strip():
            self.review(
                "创建分类文件夹",
                lambda preview: self.lib.create_category(name.strip(), preview=preview),
            )

    def category_menu(self, point):
        item = self.category_tree.itemAt(point)
        if not item:
            return
        category = item.data(0, Qt.ItemDataRole.UserRole)
        if category is None:
            return
        menu = QMenu(self)
        menu.addAction("新建子分类", lambda: self._new_subcategory(category))
        menu.addAction("重命名 / 移动分类", lambda: self.rename_category(category))
        menu.addSeparator()
        menu.addAction(
            "将分类移至待删区",
            lambda: self.review(
                "将分类及所属资源移至待删区",
                lambda preview: self.lib.delete_category(category, preview=preview),
                confirm=True,
            ),
        )
        menu.exec(self.category_tree.viewport().mapToGlobal(point))

    def _new_subcategory(self, category):
        self.category = category
        self.new_category()

    def rename_category(self, category):
        name, ok = QInputDialog.getText(self, "重命名分类", "新的完整分类路径", text=category)
        if ok and name.strip():
            self.review(
                "重命名分类",
                lambda preview: self.lib.rename_category(category, name.strip(), preview=preview),
            )

    def edit_metadata(self):
        ids = self.require_selection()
        if not ids or self.busy:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("批量设置分级与标签")
        dialog.resize(860, 720)
        dialog.setMinimumSize(760, 620)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(25, 25, 25, 25)
        layout.addWidget(label(f"整理 {len(ids)} 个资源", "detailTitle"))
        form = QFormLayout()
        form.setSpacing(16)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        grade = ModernComboBox()
        grade.addItem("保留当前分级", None)
        [grade.addItem(g + " 级", g) for g in "ABC"]
        grade.addItem("取消分级", "")
        tag_picker = QListWidget()
        tag_picker.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        tag_picker.setViewMode(QListView.ViewMode.IconMode)
        tag_picker.setFlow(QListView.Flow.LeftToRight)
        tag_picker.setWrapping(True)
        tag_picker.setResizeMode(QListView.ResizeMode.Adjust)
        tag_picker.setMovement(QListView.Movement.Static)
        tag_picker.setSpacing(7)
        tag_picker.setMinimumWidth(600)
        tag_picker.setMinimumHeight(260)
        tag_picker.setMaximumHeight(430)
        tag_picker.setObjectName("tagPicker")
        selected_rows = self.selected_resources()
        common_tags = set(selected_rows[0].get("tags", [])) if selected_rows else set()
        for resource in selected_rows[1:]:
            common_tags.intersection_update(resource.get("tags", []))
        for tag in self.lib.tags():
            item = QListWidgetItem(f"#{tag['name']}   {tag['count']}")
            item.setData(Qt.ItemDataRole.UserRole, tag["name"])
            item.setSizeHint(QSize(min(190, max(120, len(tag["name"]) * 12 + 48)), 38))
            tag_picker.addItem(item)
            # QListWidget selection only becomes effective after the item has
            # entered the model. This also makes existing common tags visible
            # when editing one resource or a multi-selection.
            item.setSelected(tag["name"] in common_tags)
        add = QLineEdit()
        add.setPlaceholderText("多个标签用中文或英文逗号分隔")
        remove = QLineEdit()
        remove.setPlaceholderText("要从所选资源移除的标签")
        form.addRow("分级", grade)
        form.addRow("选择标签（可多选）", tag_picker)
        form.addRow("添加标签", add)
        form.addRow("移除标签", remove)
        layout.addLayout(form)
        actions = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        actions.button(QDialogButtonBox.StandardButton.Ok).setText("完成")
        actions.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        actions.accepted.connect(dialog.accept)
        actions.rejected.connect(dialog.reject)
        layout.addWidget(actions)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        def split(text):
            return [t.strip() for t in text.replace("，", ",").split(",") if t.strip()]

        # Capture dialog values before it is destroyed. The review/worker runs
        # after the dialog closes; retaining the QComboBox here caused
        # "Internal C++ object QComboBox already deleted".
        grade_value = grade.currentData()
        add_values = split(add.text()) + [
            item.data(Qt.ItemDataRole.UserRole)
            for item in tag_picker.selectedItems()
        ]

        remove_values = split(remove.text())
        self.review(
            "更新分级与标签",
            lambda preview: self.lib.batch_update(
                ids,
                grade=grade_value,
                add_tags=add_values,
                remove_tags=remove_values,
                preview=preview,
            ),
        )

    def move_resources(self):
        ids = self.require_selection()
        if not ids or self.busy:
            return
        categories = self.lib.categories()
        paths = [c["path"] for c in categories]
        options = ["收件箱（未分类）"] + paths
        name, ok = self._select_item("移动资源", "选择最终分类文件夹", options)
        if ok:
            self.review(
                "移动资源",
                lambda preview: self.lib.batch_update(
                    ids, category="" if name == options[0] else name, preview=preview
                ),
            )

    def copy_resources(self):
        ids = self.require_selection()
        if not ids or self.busy:
            return
        categories = self.lib.categories()
        paths = [c["path"] for c in categories]
        options = ["收件箱（未分类）"] + paths
        name, ok = self._select_item("复制资源", "选择目标分类文件夹", options)
        if ok:
            self.review(
                "复制资源",
                lambda preview: self.lib.copy_resources(
                    ids, category="" if name == options[0] else name, preview=preview
                ),
            )

    def rename_resources(self):
        ids = self.require_selection()
        if not ids or self.busy:
            return
        default = self.selected_resources()[0]["name"] if len(ids) == 1 else "{name}_{n}"
        name, ok = QInputDialog.getText(
            self,
            "修改资源原名",
            "仅修改原名，保留分级、标签和扩展名。\n批量模板支持 {name} 原名与 {n} 序号。",
            text=default,
        )
        if ok and name.strip():
            self.review(
                "重命名资源",
                lambda preview: self.lib.batch_update(ids, name=name.strip(), preview=preview),
            )

    def trash_resources(self):
        ids = self.require_selection()
        if ids and not self.busy:
            self.review(
                "将所选资源移至待删区",
                lambda preview: self.lib.batch_update(ids, trash=True, preview=preview),
                confirm=True,
            )

    def permanently_delete_selected(self):
        ids = self.require_selection()
        if not ids or self.view != "trash" or self.busy:
            return
        answer = QMessageBox.question(
            self, "永久删除资源", f"确定永久删除选中的 {len(ids)} 项？此操作无法撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.run_job(
            "正在永久删除资源…",
            lambda: self.lib.permanently_delete(ids),
            self._permanent_delete_finished,
        )

    def _permanent_delete_finished(self, result):
        errors = result.get("errors", [])
        if errors:
            self.status_label.setText(f"已删除 {result.get('count', 0)} 项，另有 {len(errors)} 项未能删除")
            self.error("部分资源未能永久删除：\n" + "\n".join(errors))
        else:
            self.status_label.setText(f"已永久删除 {result.get('count', 0)} 项")

    def empty_trash(self):
        if self.view != "trash" or self.busy:
            return
        count = len(self.lib.resources(view="trash"))
        if not count:
            self.status_label.setText("待删区为空")
            return
        answer = QMessageBox.question(
            self, "清空待删区", f"确定永久删除待删区中的全部 {count} 项？此操作无法撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.run_job(
            "正在清空待删区…",
            lambda: self.lib.permanently_delete(),
            self._permanent_delete_finished,
        )

    def set_cover(self):
        resources = self.selected_resources()
        if len(resources) != 1 or resources[0]["type"] != "folder":
            return
        r = resources[0]
        path, _ = QFileDialog.getOpenFileName(
            self,
            "从该文件夹内部选择封面图片",
            r["path"],
            "图片 (*.jpg *.jpeg *.png *.webp *.bmp *.tif *.tiff *.gif *.heic *.heif *.arw *.cr2 *.cr3 *.nef *.dng *.orf *.rw2 *.raw);;所有文件 (*)",
        )
        if not path:
            return
        # QFileDialog starts in the resource folder, but users can navigate
        # elsewhere.  Validate the selection here so an invalid choice is
        # rejected immediately with a useful message instead of launching a
        # background job that fails after the confirmation dialog.
        try:
            chosen = Path(path).expanduser().resolve()
            folder = Path(r["path"]).expanduser().resolve()
            chosen.relative_to(folder)
            valid = (
                chosen.is_file()
                and chosen.suffix.lower() in IMAGE_EXTENSIONS
            )
        except (OSError, ValueError):
            valid = False
        if not valid:
            self.error("请选择该文件夹资源内部的一张图片作为封面。")
            return
        self.run_job("正在设置封面…", lambda: self.lib.set_cover(r["id"], path))

    def set_video_cover_from_preview(self, resource, seconds=0.0):
        """Extract the selected video frame into app cache and persist its path."""
        if self.busy or resource.get("type") != "video":
            return
        cache = Path(self.lib.data_dir) / "cache" / "video-covers"

        def work():
            poster = make_video_poster(
                resource["path"], cache, seek=max(0, float(seconds)), size=(960, 540)
            )
            self.lib.set_video_cover(resource["id"], poster)
            return poster

        def done(poster):
            resource["_cover_path"] = poster
            self.thumbnails.changed.emit(resource["path"])
            self.status_label.setText("视频封面已保存到程序缓存")

        self.run_job("正在保存视频当前帧…", work, done)

    def set_folder_video_cover_from_preview(self, folder_id, resource, seconds=0.0):
        """Use a folder-browser video frame as the parent folder cover."""
        if self.busy or resource.get("type") != "video":
            return
        cache = Path(self.lib.data_dir) / "cache" / "video-covers"

        def work():
            poster = make_video_poster(
                resource["path"], cache, seek=max(0, float(seconds)), size=(960, 540)
            )
            self.lib.set_cover(folder_id, poster)
            return poster

        def done(_poster):
            self.refresh()
            self.status_label.setText("文件夹资源封面已保存到程序缓存")

        self.run_job("正在保存文件夹视频当前帧…", work, done)

    def set_folder_cover_from_browser(self, folder_id, resource, seconds=None):
        """Persist an image or a generated video frame as its outer folder cover."""
        if resource.get("type") == "image":
            self.run_job(
                "正在设置文件夹封面…",
                lambda: self.lib.set_cover(folder_id, resource["path"]),
                lambda _result: (self.refresh(), self.status_label.setText("文件夹封面已更新")),
            )
            return
        self.set_folder_video_cover_from_preview(folder_id, resource, seconds or 0.0)

    def open_selected(self):
        resources = self.selected_resources()
        if len(resources) == 1:
            QDesktopServices.openUrl(QUrl.fromLocalFile(resources[0]["path"]))

    def open_or_preview(self, index):
        if 0 <= index < len(self.model.rows) and self.model.rows[index]["type"] == "folder":
            # Folder resources open in their own non-modal top-level window.
            # Keeping a strong reference prevents the dialog from being
            # garbage-collected while the user browses its contents.
            # Do not parent this viewer to the main window. A true top-level
            # window receives its own taskbar entry/preview and minimizes and
            # restores independently on Windows.
            resource = self.model.rows[index]
            dialog = FolderBrowserDialog(
                resource["path"],
                cover_callback=lambda inner, seconds, rid=resource["id"]: self.set_folder_cover_from_browser(
                    rid, inner, seconds
                ),
            )
            self._folder_browsers.add(dialog)
            dialog.finished.connect(lambda _result, view=dialog: self._folder_browsers.discard(view))
            dialog.setWindowModality(Qt.WindowModality.NonModal)
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
        else:
            self.preview(index)

    def preview_selected(self):
        indexes = self._selected_indexes()
        if indexes:
            self.preview(indexes[0].row())

    def preview(self, index):
        if self.model.rows and not self.busy:
            selected = self.model.rows[index]
            if selected["type"] == "folder":
                self.status_label.setText("文件夹不参与资源欣赏，可双击使用系统打开")
                return
            media = [resource for resource in self.model.rows if resource["type"] != "folder"]
            start = next(i for i, resource in enumerate(media) if resource["id"] == selected["id"])
            player = MediaPreview(media, start, cover_callback=self.set_video_cover_from_preview)
            self._player_windows.add(player)
            player.finished.connect(lambda _result, view=player: self._player_windows.discard(view))
            player.show()
            player.raise_()
            player.activateWindow()

    def resource_menu(self, view, point):
        index = view.indexAt(point)
        if not index.isValid():
            return
        if not view.selectionModel().isSelected(index):
            view.selectionModel().select(
                index,
                view.selectionModel().SelectionFlag.ClearAndSelect
                | view.selectionModel().SelectionFlag.Rows,
            )
        menu = QMenu(self)
        selected = self.selected_resources()
        if self.view != "trash":
            self._add_quick_tags(menu, selected)
            menu.addSeparator()
        menu.addAction("系统应用打开", self.open_selected)
        menu.addSeparator()
        if self.view != "trash":
            for text, callback in [
                ("移动到分类", self.move_resources),
                ("修改原名", self.rename_resources),
            ]:
                menu.addAction(text, callback)
            menu.addSeparator()
            menu.addAction("移至待删区", self.trash_resources)
        else:
            menu.addAction("永久删除所选", self.permanently_delete_selected)
        menu.exec(view.viewport().mapToGlobal(point))

    def _add_quick_tags(self, menu, resources):
        tags = self.lib.tags()
        if not tags or not resources:
            action = menu.addAction("暂无标签 · 请先在标签管理中创建")
            action.setEnabled(False)
            return
        panel = QListWidget(menu)
        panel.setObjectName("quickTagList")
        panel.setViewMode(QListView.ViewMode.IconMode)
        panel.setFlow(QListView.Flow.LeftToRight)
        panel.setWrapping(True)
        panel.setResizeMode(QListView.ResizeMode.Adjust)
        panel.setMovement(QListView.Movement.Static)
        panel.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        panel.setSpacing(6)
        panel.setFixedSize(330, min(250, max(58, ((len(tags) + 2) // 3) * 42 + 16)))
        resource_tags = [set(resource.get("tags", [])) for resource in resources]
        active = {
            tag["name"] for tag in tags if all(tag["name"] in current for current in resource_tags)
        }
        for tag in tags:
            item = QListWidgetItem("#" + tag["name"])
            item.setData(Qt.ItemDataRole.UserRole, tag["name"])
            item.setSizeHint(QSize(min(150, max(90, len(tag["name"]) * 14 + 30)), 34))
            panel.addItem(item)
            # Set selection after insertion so existing tags are highlighted.
            item.setSelected(tag["name"] in active)
        action = QWidgetAction(menu)
        action.setDefaultWidget(panel)
        menu.addAction(action)

        def apply_tag(item):
            name = item.data(Qt.ItemDataRole.UserRole)
            ids = [resource["id"] for resource in resources]
            try:
                if name in active:
                    active.discard(name)
                    item.setSelected(False)
                    self.lib.batch_update(ids, remove_tags=[name])
                else:
                    active.add(name)
                    item.setSelected(True)
                    self.lib.batch_update(ids, add_tags=[name])
                self.refresh()
            except Exception as exc:
                self.error(str(exc))

        panel.itemClicked.connect(apply_tag)

    def manage_tags(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("标签管理")
        dialog.resize(720, 430)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.addWidget(label("标签管理", "detailTitle"))
        chips = TagChipView(dialog)
        layout.addWidget(chips, 1)

        def delete_tag(name):
            answer = QMessageBox.question(
                dialog, "确认删除标签", f"删除“{name}”会同步更新相关资源文件名，是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            try:
                self.lib.change_tag(name, None, preview=False)
                self.refresh()
                render_tags()
            except Exception as exc:
                self.error(str(exc))

        def render_tags():
            chips.set_tags(self.lib.tags())

        render_tags()
        chips.deleteRequested.connect(delete_tag)
        row = QHBoxLayout()

        def add_tag():
            text, ok = QInputDialog.getText(dialog, "新增标签", "标签名称")
            if ok and text.strip():
                try:
                    self.lib.add_tag(text.strip())
                    self.refresh()
                    render_tags()
                except Exception as exc:
                    self.error(str(exc))

        def change():
            tags = self.lib.tags()
            if not tags:
                return
            old, ok = self._select_item(
                "重命名 / 合并标签", "选择要修改的标签", [t["name"] for t in tags], parent=dialog
            )
            if not ok:
                return
            new = None
            new, ok = QInputDialog.getText(
                dialog, "重命名 / 合并标签", "新标签名称（已存在的标签会合并）", text=old
            )
            if not ok or not new.strip():
                return
            new = new.strip()
            try:
                self.lib.change_tag(old, new, preview=False)
                self.refresh()
                render_tags()
            except Exception as exc:
                self.error(str(exc))

        row.addWidget(button("新增标签", add_tag, glyph="plus"))
        row.addWidget(button("重命名 / 合并", change))
        row.addStretch()
        row.addWidget(button("关闭", dialog.reject))
        layout.addLayout(row)
        dialog.exec()

    def undo(self, operation_id=None):
        self.review("撤销操作", lambda preview: self.lib.undo(operation_id, preview=preview))

    def duplicates(self):
        if not self.lib.source_root:
            self.choose_root()
            return
        duplicate_kwargs = self._duplicate_wizard()
        if duplicate_kwargs is None:
            return
        self.run_cancelable_job(
            "正在检查重复资源…",
            lambda report, cancel_event, kwargs=duplicate_kwargs: self.lib.duplicates(
                **kwargs, progress=report, cancel_event=cancel_event
            ),
            self.show_duplicates,
        )

    def _duplicate_wizard(self):
        """Collect duplicate mode and scope in one navigable dialog.

        The old implementation opened three unrelated dialogs in sequence.
        Apart from making the flow hard to understand, that also caused the
        native QListWidget check indicator to render as a black square on
        some Windows styles.  This wizard uses explicit controls and keeps
        the user's folder choices while filtering the list.
        """
        dialog = QDialog(self)
        dialog.setWindowTitle("重复资源检查")
        dialog.setMinimumSize(620, 400)
        dialog.resize(740, 480)
        dialog.setStyleSheet(
            "QPushButton[duplicateChoice='true'] { text-align: left; padding: 10px 14px; min-height: 42px; "
            "color: #465469; background: #fbfcfe; border: 1px solid #e3e8f0; border-radius: 9px; }"
            "QPushButton[duplicateChoice='true']:hover { background: #f4f7fc; border-color: #cbd8ea; }"
            "QPushButton[duplicateChoice='true']:checked { color: #245fc5; background: #edf4ff; "
            "border-color: #8db3ff; font-weight: 600; }"
        )
        if hasattr(dialog, "setSizeGripEnabled"):
            dialog.setSizeGripEnabled(False)
        root = QVBoxLayout(dialog)
        root.setContentsMargins(24, 22, 24, 18)
        root.setSpacing(12)

        pages = QStackedWidget(dialog)
        pages.setObjectName("duplicatePages")
        root.addWidget(pages, 1)
        footer = QHBoxLayout()
        footer.setSpacing(8)
        back = QPushButton("上一步", dialog)
        cancel = QPushButton("取消", dialog)
        next_button = QPushButton("下一步", dialog)
        start = QPushButton("开始检查", dialog)
        back.setObjectName("duplicateBack")
        cancel.setObjectName("duplicateCancel")
        next_button.setObjectName("duplicateNext")
        start.setObjectName("duplicateStart")
        start.setStyleSheet(
            "QPushButton#duplicateStart { color: white; background: #3478f6; "
            "border: 1px solid #3478f6; border-radius: 8px; font-weight: 600; padding: 8px 13px; }"
            "QPushButton#duplicateStart:hover { background: #2369e8; }"
            "QPushButton#duplicateStart:disabled { background: #a4bde8; border-color: #a4bde8; }"
        )
        footer.addWidget(back)
        footer.addStretch(1)
        footer.addWidget(cancel)
        footer.addWidget(next_button)
        footer.addWidget(start)
        root.addLayout(footer)

        # Page 1: mode.
        mode_page = QWidget()
        mode_layout = QVBoxLayout(mode_page)
        mode_layout.setContentsMargins(4, 4, 4, 4)
        mode_layout.setSpacing(8)
        mode_layout.addWidget(label("检查方式", "detailTitle"))
        mode_group = QButtonGroup(mode_page)
        mode_group.setExclusive(True)

        def choice(text, parent, object_name, group):
            control = QPushButton(parent)
            control.setCheckable(True)
            control.setObjectName(object_name)
            control.setProperty("duplicateChoice", True)
            control.setProperty("choiceText", text)
            control.setText("○  " + text)
            group.addButton(control)
            control.toggled.connect(
                lambda checked, item=control, title=text: item.setText(
                    f"{'✓' if checked else '○'}  {title}"
                )
            )
            return control

        exact = choice("完全重复 · SHA-256（全库）", mode_page, "duplicateModeExact", mode_group)
        exact.setToolTip("按文件内容哈希检查，范围固定为整个资源库")
        similar = choice("相似图片 / 视频 · 感知哈希", mode_page, "duplicateModeSimilar", mode_group)
        similar.setToolTip("按图片或视频内容特征检查相似资源")
        exact.setChecked(True)
        mode_layout.addWidget(exact)
        mode_layout.addWidget(similar)
        mode_layout.addStretch(1)
        pages.addWidget(mode_page)

        # Page 2: similar scope.  Exact mode skips this page on Next.
        scope_page = QWidget()
        scope_layout = QVBoxLayout(scope_page)
        scope_layout.setContentsMargins(4, 4, 4, 4)
        scope_layout.setSpacing(8)
        scope_layout.addWidget(label("检查范围", "detailTitle"))
        scope_box = QVBoxLayout()
        scope_box.setContentsMargins(0, 4, 0, 0)
        scope_box.setSpacing(8)
        scope_layout.addLayout(scope_box)
        scope_buttons = []
        scope_group = QButtonGroup(scope_page)
        scope_group.setExclusive(True)

        def scope_option(text, enabled=True, object_name=""):
            radio = choice(text, scope_page, object_name or "duplicateScopeChoice", scope_group)
            radio.setEnabled(enabled)
            if enabled:
                scope_buttons.append(radio)
                scope_box.addWidget(radio)
            else:
                radio.hide()
            return radio

        inbox = self.lib.resources(view="inbox")
        categories = self.lib.categories()
        inbox_scope = scope_option("收件箱与其他资源互检", object_name="duplicateScopeInboxOther") if inbox else None
        inbox_target = ModernComboBox(scope_page)
        inbox_target.setObjectName("duplicateInboxTarget")
        inbox_target.setEnabled(bool(inbox_scope))
        inbox_target.addItem("全部资源", "all")
        for category in categories:
            inbox_target.addItem(f"分类：{category['path']}", category["path"])
        if inbox_scope:
            scope_box.addWidget(inbox_target)
        inbox_only = scope_option("收件箱内互检", object_name="duplicateScopeInboxOnly") if inbox else None
        current_scope = scope_option(
            "当前目录内互检（含子分类）", object_name="duplicateScopeCurrent"
        )
        folder_scope = scope_option("选择多个文件夹内部互检", object_name="duplicateScopeFolders")
        if scope_buttons:
            scope_buttons[0].setChecked(True)
        scope_layout.addStretch(1)
        pages.addWidget(scope_page)

        # Page 3: checkable buttons provide a consistent full-row selection
        # state independent of the Windows item-view checkbox style.
        folder_page = QWidget()
        folder_layout = QVBoxLayout(folder_page)
        folder_layout.setContentsMargins(4, 4, 4, 4)
        folder_layout.setSpacing(8)
        folder_layout.addWidget(label("文件夹", "detailTitle"))
        folder_search = QLineEdit(folder_page)
        folder_search.setObjectName("duplicateFolderSearch")
        folder_search.setPlaceholderText("搜索文件夹名称或路径")
        folder_layout.addWidget(folder_search)
        folder_count = label("已选择 0 个", "muted")
        folder_layout.addWidget(folder_count)
        folder_scroll = QScrollArea(folder_page)
        folder_scroll.setWidgetResizable(True)
        folder_scroll.setFrameShape(QFrame.Shape.NoFrame)
        folder_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        folder_content = QWidget()
        folder_rows = QVBoxLayout(folder_content)
        folder_rows.setContentsMargins(4, 4, 4, 4)
        folder_rows.setSpacing(5)
        folder_scroll.setWidget(folder_content)
        folder_layout.addWidget(folder_scroll, 1)
        folder_resources = [r for r in self.lib.resources() if r["type"] == "folder"]
        folder_checks = []
        for resource in folder_resources:
            check = QPushButton(folder_content)
            check.setCheckable(True)
            check.setObjectName("duplicateFolderChoice")
            check.setText(f"○  {resource['name']}  ·  {resource['path']}")
            check.setStyleSheet(
                "QPushButton#duplicateFolderChoice { text-align: left; padding: 8px 12px; "
                "background: #ffffff; border: 1px solid #e1e5ec; border-radius: 8px; }"
                "QPushButton#duplicateFolderChoice:hover { background: #f2f6fd; border-color: #b8c9e4; }"
                "QPushButton#duplicateFolderChoice:checked { color: #245fc5; background: #eaf1ff; "
                "border-color: #80aaff; font-weight: 600; }"
            )
            check.setToolTip(resource["path"])
            check.setProperty("resourcePath", resource["path"])
            check.setMinimumHeight(34)
            check.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            folder_rows.addWidget(check)
            folder_checks.append(check)
        folder_rows.addStretch(1)
        folder_search.textChanged.connect(
            lambda value: [
                check.setVisible(
                    not value.strip() or value.casefold() in check.toolTip().casefold()
                )
                for check in folder_checks
            ]
        )
        pages.addWidget(folder_page)

        selected = {"mode": "exact", "scope": None}

        def update_page():
            page = pages.currentIndex()
            back.setEnabled(page > 0)
            selecting_folders = page == 1 and folder_scope and folder_scope.isChecked()
            next_button.setVisible(page == 0)
            start.setVisible(page > 0)
            if page == 2:
                checked_count = sum(check.isChecked() for check in folder_checks)
                folder_count.setText(f"已选择 {checked_count} 个")
                start.setText("开始检查")
                start.setEnabled(checked_count >= 2)
            elif page == 1:
                start.setText("选择文件夹" if selecting_folders else "开始检查")
                start.setEnabled(any(radio.isChecked() for radio in scope_buttons))
            else:
                start.setEnabled(True)
            if page == 0:
                next_button.setText("选择范围" if similar.isChecked() else "开始检查")

        def next_page():
            page = pages.currentIndex()
            if page == 0:
                if exact.isChecked():
                    selected["mode"] = "exact"
                    dialog.accept()
                    return
                selected["mode"] = "similar"
                pages.setCurrentIndex(1)
            elif page == 1:
                if folder_scope and folder_scope.isChecked():
                    pages.setCurrentIndex(2)
                else:
                    dialog.accept()
            update_page()

        def previous_page():
            if pages.currentIndex() == 2:
                pages.setCurrentIndex(1)
            elif pages.currentIndex() == 1:
                pages.setCurrentIndex(0)
            update_page()

        def start_check():
            page = pages.currentIndex()
            if page == 2 and sum(check.isChecked() for check in folder_checks) < 2:
                return
            if page == 1 and folder_scope and folder_scope.isChecked():
                pages.setCurrentIndex(2)
                update_page()
                return
            dialog.accept()

        exact.toggled.connect(lambda _checked: update_page())
        similar.toggled.connect(lambda _checked: update_page())
        for scope_button in scope_buttons:
            scope_button.toggled.connect(lambda _checked: update_page())
        back.clicked.connect(previous_page)
        next_button.clicked.connect(next_page)
        start.clicked.connect(start_check)
        cancel.clicked.connect(dialog.reject)
        for check in folder_checks:
            resource_name = next(
                resource["name"]
                for resource in folder_resources
                if resource["path"] == check.property("resourcePath")
            )
            check.toggled.connect(
                lambda checked, item=check, name=resource_name: item.setText(
                    f"{'✓' if checked else '○'}  {name}  ·  {item.toolTip()}"
                )
            )
            check.toggled.connect(update_page)
        update_page()
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None

        if selected["mode"] == "exact":
            return {
                "mode": "exact",
                "category": self.category,
                "expand_folder": None,
                "folder_pair": None,
                "recursive_category": False,
                "compare_all": True,
            }

        if pages.currentIndex() == 2 or (folder_scope and folder_scope.isChecked()):
            paths = [check.property("resourcePath") for check in folder_checks if check.isChecked()]
            if len(paths) < 2:
                return None
            return {"mode": "similar", "expand_folders": paths, "expanded_only": True}
        if inbox_scope and inbox_scope.isChecked():
            ids = [r["id"] for r in inbox]
            target = inbox_target.currentData()
            if target == "all":
                return {"mode": "similar", "ids": ids, "candidate_ids": [r["id"] for r in self.lib.resources()], "source_ids": ids}
            candidates = self.lib.resources(category=target)
            return {"mode": "similar", "ids": ids, "candidate_ids": [r["id"] for r in candidates], "source_ids": ids}
        if inbox_only and inbox_only.isChecked():
            ids = [r["id"] for r in inbox]
            return {"mode": "similar", "ids": ids, "source_ids": ids}
        if current_scope and current_scope.isChecked():
            return {"mode": "similar", "category": self.category}
        return None

    def _select_resource_folders(self, title, prompt, resources, minimum=1):
        """Compatibility helper for callers outside the duplicate wizard."""
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(760, 560)
        if hasattr(dialog, "setSizeGripEnabled"):
            dialog.setSizeGripEnabled(False)
        layout = QVBoxLayout(dialog)
        layout.addWidget(label(prompt, "detailTitle"))
        search = QLineEdit(dialog)
        search.setPlaceholderText("搜索文件夹名称或路径")
        layout.addWidget(search)
        count_label = label(f"已选择 0 个文件夹（至少 {minimum} 个）", "muted")
        layout.addWidget(count_label)
        scroll = QScrollArea(dialog)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        content = QWidget()
        rows_layout = QVBoxLayout(content)
        rows_layout.setContentsMargins(4, 4, 4, 4)
        rows_layout.setSpacing(5)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        actions = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        actions.button(QDialogButtonBox.StandardButton.Ok).setText("确定")
        actions.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        layout.addWidget(actions)
        choices = []

        def update_state():
            selected_count = sum(choice.isChecked() for choice in choices)
            count_label.setText(f"已选择 {selected_count} 个文件夹（至少 {minimum} 个）")
            actions.button(QDialogButtonBox.StandardButton.Ok).setEnabled(selected_count >= minimum)

        for resource in resources:
            choice = QPushButton(f"○  {resource['name']}  ·  {resource['path']}", content)
            choice.setCheckable(True)
            choice.setObjectName("duplicateFolderChoice")
            choice.setToolTip(resource["path"])
            choice.setProperty("resource", resource)
            choice.setMinimumHeight(34)
            choice.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
            choice.toggled.connect(
                lambda checked, item=choice: item.setText(
                    f"{'✓' if checked else '○'}  {item.property('resource')['name']}  ·  {item.toolTip()}"
                )
            )
            choice.toggled.connect(update_state)
            rows_layout.addWidget(choice)
            choices.append(choice)
        rows_layout.addStretch(1)
        search.textChanged.connect(
            lambda value: [
                choice.setVisible(not value.strip() or value.casefold() in choice.toolTip().casefold())
                for choice in choices
            ]
        )
        update_state()
        actions.accepted.connect(dialog.accept)
        actions.rejected.connect(dialog.reject)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return [], False
        return [choice.property("resource") for choice in choices if choice.isChecked()], True

    def quick_grade(self, row):
        if row < 0 or row >= len(self.model.rows) or self.busy:
            return
        resource = self.model.rows[row]
        old = getattr(self, "_grade_popup", None)
        if old is not None:
            old.close()
            old.deleteLater()
        popup = GradePopup(resource.get("grade", ""), self)
        self._grade_popup = popup
        popup.chosen.connect(
            lambda grade, rid=resource["id"]: self.review(
                "设置分级", lambda preview: self.lib.batch_update([rid], grade=grade, preview=preview)
            )
        )
        rect = self.grid.visualRect(self.model.index(row, 0))
        popup.popup(self.grid.viewport().mapToGlobal(rect.topLeft() + QPoint(16, 49)))

    def show_duplicates(self, result):
        dialog = DuplicateResultsDialog(result, self, self.thumbnails)

        def discard(resources):
            if self.busy or result.get("read_only_temporary"):
                return
            try:
                plan = self.lib.discard_duplicate_resources(resources, preview=True)
            except Exception as exc:
                self.error(str(exc))
                return
            if ReviewDialog("淘汰所选重复资源", plan, self).exec() != QDialog.DialogCode.Accepted:
                return
            dialog.set_actions_enabled(False)
            selected_ids = [resource["id"] for resource in resources]
            self.run_job(
                "正在将重复资源移至待删区…",
                lambda: self.lib.discard_duplicate_resources(resources, preview=False),
                lambda _result, selected=selected_ids: (
                    dialog.remove_resources(selected),
                    dialog.set_actions_enabled(True),
                ),
            )

        dialog.discardRequested.connect(discard)
        dialog.mergeRequested.connect(self.merge_duplicate_folders)
        dialog.exec()

    def merge_duplicate_folders(self, pair):
        if self.busy or len(pair) != 2:
            return
        targets = [str(Path(path)) for path in pair]
        selected_target, ok = self._select_item(
            "选择合并目标",
            "请选择保留为目标的文件夹，另一个文件夹中的内容将复制到这里。",
            targets,
        )
        if not ok:
            return
        destination = selected_target
        source = pair[1] if selected_target == pair[0] else pair[0]
        answer = QMessageBox.question(
            self,
            "合并两个文件夹",
            f"将“{Path(source).name}”中的文件复制到“{Path(destination).name}”。内容完全相同的文件会跳过，"
            "同名但内容不同的文件会自动改名；来源文件夹会保留。继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.run_job(
            "正在合并文件夹内容…",
            lambda: self.lib.merge_folder_pair(destination, source),
            lambda result: self.status_label.setText(
                f"文件夹合并完成 · 新增 {result['copied']} 项，跳过 {result['skipped']} 项"
            ),
        )

    def clear_cache(self, parent=None):
        """Clear generated cache and reset the remembered library selection."""
        if self.busy:
            return
        answer = QMessageBox.question(
            parent or self,
            "清除缓存并重置资源库",
            "将清理当前资源库的自动缩略图、海报和重复检查哈希，并清除已记住的原始库、目标库路径。\n"
            "下次启动会像首次打开一样要求重新选择资源库。资源文件、分类数据和手动设置的封面/缩略图都会保留。继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            # Stop workers before removing files they may still be writing.
            self.thumbnails.shutdown()
            result = self.lib.clear_rebuildable_cache() if self.lib.data_dir else {
                "removed_files": 0,
                "preserved_covers": 0,
            }
            self.lib.clear_library_selection()
            self._activate_library(Library.unbound())
            self.thumbnails.cache.clear()
            self.thumbnails.pending.clear()
            self.thumbnails.jobs.clear()
            self.thumbnails.cache_dir = None
            self.status_label.setText("缓存已清理，资源库路径已重置")
            QMessageBox.information(
                parent or self,
                "资源库已重置",
                "自动缓存和已记住的原始库、目标库路径已清理。\n"
                f"保留 {result['preserved_covers']} 个手动封面，以及所有资源与分类数据。",
            )
            if parent:
                parent.accept()
        except Exception as exc:
            self.error(str(exc))

    def settings(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("资源库设置")
        dialog.resize(660, 430)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(26, 26, 26, 26)
        layout.setSpacing(14)
        layout.addWidget(label("资源库设置", "detailTitle"))
        layout.addWidget(label("请先选择目标库再选择原始库。", "muted"))
        path_buttons = {}
        for caption, value, callback in [
            ("原始库", self.lib.source_root, self.choose_root),
            ("目标库", self.lib.library_root, self.choose_library),
        ]:
            layout.addWidget(label(caption, "section"))
            path_button = button(str(value) if value else "点击选择文件夹", kind="pathButton")
            path_button.setToolTip(str(value) if value else "")
            path_button.setStyleSheet("text-align: left; padding: 9px 10px;")
            path_buttons[caption] = path_button

            def choose_path(_checked=False, cb=callback, btn=path_button, title=caption):
                cb(dialog)
                current = self.lib.source_root if title == "原始库" else self.lib.library_root
                btn.setText(str(current) if current else "点击选择文件夹")
                btn.setToolTip(str(current) if current else "")

            path_button.clicked.connect(choose_path)
            layout.addWidget(path_button)
        def export():
            dialog.accept()
            self.export_data()

        def import_data():
            dialog.accept()
            self.import_data()

        def backup():
            dialog.accept()
            self.run_job(
                "正在备份程序数据…",
                self.lib.backup,
                lambda path: QMessageBox.information(self, "备份完成", str(path)),
            )

        def manage_backups():
            self.manage_backups()

        def import_backup():
            file, _ = QFileDialog.getOpenFileName(
                dialog, "导入 SQLite 备份", "", "SQLite 备份 (*.sqlite3)"
            )
            if not file:
                return
            answer = QMessageBox.question(
                dialog,
                "导入并恢复备份",
                "恢复会替换当前资源库的数据库信息；不会回退磁盘上的文件移动或重命名。\n"
                "恢复前会自动创建当前数据库备份。继续吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            try:
                result = self.lib.import_backup_file(file)
                dialog.accept()
                self.refresh()
                self.status_label.setText("备份已导入并恢复；恢复前快照：" + result["safety_backup"])
            except Exception as exc:
                self.error(str(exc))

        actions = [
            ("导出 JSON", export),
            ("导入 JSON", import_data),
            ("备份数据", backup),
            ("管理备份", manage_backups),
            ("导入备份", import_backup),
        ]
        action_grid = QGridLayout()
        action_grid.setHorizontalSpacing(8)
        action_grid.setVerticalSpacing(8)
        for index, (text, callback) in enumerate(actions):
            action_grid.addWidget(button(text, callback), index // 3, index % 3)
        # Keep cache maintenance with the other settings actions.  The icon
        # is intentionally compact; the tooltip carries the full action name.
        cache_button = button("清除缓存", lambda: self.clear_cache(dialog), glyph="trash")
        cache_button.setToolTip("清理自动生成缓存并清除已记住的原始库、目标库路径")
        action_grid.addWidget(cache_button, len(actions) // 3, len(actions) % 3)
        layout.addLayout(action_grid)
        layout.addStretch()
        layout.addWidget(button("完成", dialog.accept, kind="primary"))
        dialog.exec()

    def manage_backups(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("管理资源库备份")
        dialog.resize(760, 500)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.addWidget(label("当前资源库备份", "detailTitle"))
        listing = QListWidget()
        listing.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        backups = self.lib.list_backups()
        for backup in backups:
            item = QListWidgetItem(
                f"{backup['name']}  ·  {format_size(backup['size'])}  ·  "
                f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(backup['created']))}"
            )
            item.setData(Qt.ItemDataRole.UserRole, backup["path"])
            item.setToolTip(backup["path"])
            listing.addItem(item)
        if not backups:
            empty = QListWidgetItem("暂无备份。点击“备份数据”创建当前资源库快照。")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            listing.addItem(empty)
        layout.addWidget(listing, 1)
        actions = QHBoxLayout()

        def restore():
            items = listing.selectedItems()
            if len(items) != 1:
                self.error("请选择一个备份进行恢复。")
                return
            path = items[0].data(Qt.ItemDataRole.UserRole)
            answer = QMessageBox.question(
                dialog,
                "恢复资源库备份",
                "恢复会替换当前资源库的数据库信息；不会回退磁盘上的文件移动或重命名。\n"
                "恢复前会自动创建当前数据库备份。继续吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            try:
                result = self.lib.restore_backup(path)
                dialog.accept()
                self.refresh()
                self.status_label.setText("备份已恢复；恢复前快照：" + result["safety_backup"])
            except Exception as exc:
                self.error(str(exc))

        def delete():
            items = listing.selectedItems()
            paths = [item.data(Qt.ItemDataRole.UserRole) for item in items if item.data(Qt.ItemDataRole.UserRole)]
            if not paths:
                self.error("请选择要删除的备份。")
                return
            answer = QMessageBox.question(
                dialog,
                "删除备份",
                f"将永久删除选中的 {len(paths)} 个备份文件。此操作无法撤销，继续吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            try:
                self.lib.delete_backups(paths)
                for item in items:
                    listing.takeItem(listing.row(item))
            except Exception as exc:
                self.error(str(exc))

        actions.addWidget(button("恢复所选", restore, kind="primary"))
        actions.addWidget(button("删除所选", delete, glyph="trash"))
        actions.addStretch()
        actions.addWidget(button("关闭", dialog.reject))
        layout.addLayout(actions)
        dialog.exec()

    def export_data(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("导出分类与标签")
        dialog.resize(560, 510)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(label("选择要导出的内容", "detailTitle"))
        all_categories = QCheckBox("导出全部分类")
        all_categories.setChecked(True)
        all_tags = QCheckBox("导出全部标签")
        all_tags.setChecked(True)
        cats = QListWidget()
        tags = QListWidget()
        for cat in self.lib.categories():
            item = QListWidgetItem(cat["path"])
            item.setCheckState(Qt.CheckState.Unchecked)
            cats.addItem(item)
        for tag in self.lib.tags():
            item = QListWidgetItem(tag["name"])
            item.setCheckState(Qt.CheckState.Unchecked)
            tags.addItem(item)
        cats.setEnabled(False)
        tags.setEnabled(False)
        all_categories.toggled.connect(lambda checked: cats.setEnabled(not checked))
        all_tags.toggled.connect(lambda checked: tags.setEnabled(not checked))
        row = QHBoxLayout()
        for check, listing in [(all_categories, cats), (all_tags, tags)]:
            col = QVBoxLayout()
            col.addWidget(check)
            col.addWidget(listing)
            row.addLayout(col)
        layout.addLayout(row)
        resources = QCheckBox("包含资源元数据（不会复制资源文件）")
        resources.setChecked(True)
        layout.addWidget(resources)
        actions = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        actions.button(QDialogButtonBox.StandardButton.Ok).setText("导出")
        actions.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        actions.accepted.connect(dialog.accept)
        actions.rejected.connect(dialog.reject)
        layout.addWidget(actions)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        file, _ = QFileDialog.getSaveFileName(
            self, "保存导出文件", "资源库元数据.json", "JSON (*.json)"
        )
        if not file:
            return

        def chosen(listing):
            return [
                listing.item(i).text()
                for i in range(listing.count())
                if listing.item(i).checkState() == Qt.CheckState.Checked
            ]

        try:
            payload = self.lib.export_data(
                categories=None if all_categories.isChecked() else chosen(cats),
                tags=None if all_tags.isChecked() else chosen(tags),
                include_resources=resources.isChecked(),
            )
            Path(file).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            self.status_label.setText("导出完成：" + file)
        except Exception as exc:
            self.error(str(exc))

    def import_data(self):
        file, _ = QFileDialog.getOpenFileName(self, "导入分类与标签", "", "JSON (*.json)")
        if not file:
            return
        try:
            payload = json.loads(Path(file).read_text(encoding="utf-8"))
        except Exception as exc:
            self.error(str(exc))
            return
        choice, ok = self._select_item(
            "导入模式",
            "合并保留现有资源；替换会按导入 JSON 应用分类与元数据，并将未包含资源移入待删区。",
            ["合并到现有分类与标签", "替换当前分类与资源元数据"],
        )
        if ok:
            self.review(
                "导入分类与标签",
                lambda preview: self.lib.import_data(
                    payload,
                    mode="merge" if choice.startswith("合并") else "replace",
                    preview=preview,
                ),
            )

    def closeEvent(self, event):
        if self._closed:
            event.accept()
            return
        if self.busy:
            self.status_label.setText("操作正在执行，请完成后再关闭窗口")
            event.ignore()
            return
        self._closed = True
        self.search_timer.stop()
        self.repaint_timer.stop()
        self.thumbnails.pool.waitForDone()
        for view in list(self._folder_browsers):
            view.close()
        self._folder_browsers.clear()
        for player in list(self._player_windows):
            player.close()
        self._player_windows.clear()
        # Persist the active source/target pair even when the user closes the
        # app without opening Settings again.
        self._remember_paths()
        self.lib.close()
        event.accept()

