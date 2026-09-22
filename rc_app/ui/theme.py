"""rc_app.ui.theme: extracted workbench component."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QPoint, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QLabel, QPushButton

TYPE_LABELS = {"image": "图片", "video": "视频", "folder": "文件夹"}


BLUE = "#3478f6"


INK = "#202633"


MUTED = "#89909f"


STYLE = """
QWidget { color: #252b37; font-family: 'Microsoft YaHei UI', 'Segoe UI'; font-size: 13px; }
QMainWindow { background: transparent; }
QFrame#shell { background: #ffffff; border: 1px solid #d9dde4; border-radius: 13px; }
QFrame#titlebar { background: transparent; border-bottom: 1px solid #e9ebef; }
QFrame#sidebar { background: #f3f4f7; border-right: 1px solid #e9ebef; border-bottom-left-radius: 12px; }
QFrame#inspector { background: #fafbfc; border-left: 1px solid #eceef2; }
QFrame#filterbar { background: #fafbfc; border: 1px solid #eceef2; border-radius: 11px; }
QFrame#batchbar { background: #eef4ff; border: 1px solid #dce8ff; border-radius: 10px; }
QFrame#tagChip { background: #f2f6ff; border: 1px solid #d8e4ff; border-radius: 11px; }
QLabel#tagName { color: #2459b6; font-size: 13px; font-weight: 600; }
QLabel#tagCount { color: #7c8da8; font-size: 12px; }
QPushButton#tagClose { background: transparent; border: none; padding: 2px; }
QPushButton#tagClose:hover { background: #dce8ff; border-radius: 12px; }
QPushButton#pathButton { background: #f7f8fb; border: 1px solid #e1e5ec; border-radius: 8px; text-align: left; }
QPushButton#pathButton:hover { background: #eef4ff; border-color: #b9cff8; }
QLabel#title { font-size: 27px; font-weight: 700; color: #202633; }
QLabel#subtitle, QLabel#muted { color: #89909f; }
QLabel#eyebrow { color: #9197a4; font-size: 10px; font-weight: 600; }
QLabel#section { color: #777f8f; font-size: 11px; font-weight: 600; }
QLabel#detailTitle { font-weight: 600; font-size: 15px; }
QPushButton, QToolButton { background: white; border: 1px solid #e2e5eb; border-radius: 9px; padding: 8px 13px; }
QPushButton:hover, QToolButton:hover { background: #f0f4fb; border-color: #ccd7ea; }
QPushButton:pressed, QToolButton:pressed { background: #e4edfd; }
QPushButton:disabled, QToolButton:disabled { color: #a9afbb; background: #f5f6f8; border-color: #eceef2; }
QPushButton#primary { color: white; background: #3478f6; border-color: #3478f6; font-weight: 600; }
QPushButton#primary:hover { background: #2369e8; }
QPushButton#primary:disabled { background: #a4bde8; border-color: #a4bde8; }
QPushButton#quiet, QToolButton#quiet { background: transparent; border-color: transparent; }
QPushButton#quiet:hover, QToolButton#quiet:hover { background: #e9edf5; }
QPushButton#nav { text-align: left; background: transparent; border: none; padding: 10px 12px; font-weight: 500; }
QPushButton#nav:checked { background: #e3ebfa; color: #2467d8; font-weight: 600; }
QPushButton#nav:hover { background: #e9edf4; }
QPushButton#segment { background: transparent; color: #536176; border: none; padding: 0; margin: 0; }
QPushButton#segment:hover { background: #e7edf7; color: #245fc5; }
QPushButton#segment:checked { background: #ffffff; border: 1px solid #cbd9f2; color: #2467d8; }
QWidget#gradeSegments { background: #f0f3f7; border: 1px solid #e2e6ed; border-radius: 10px; }
QWidget#gradeSegments QPushButton#segment { min-width: 34px; border-radius: 7px; }
QWidget#gradeSegments QPushButton#segment:checked { background: #ffffff; color: #2467d8; border: 1px solid #bcd1f5; font-weight: 600; }
QPushButton#windowControl { background: transparent; border: none; border-radius: 5px; padding: 3px; }
QPushButton#windowControl:hover { background: #e9ebf0; }
QPushButton#closeControl { background: transparent; border: none; border-radius: 5px; padding: 3px; }
QPushButton#closeControl:hover { background: #fee6e6; color: #d63c46; }
QLineEdit, QComboBox, QPlainTextEdit, QTextEdit { background: #fff; border: 1px solid #e1e5ec; border-radius: 7px; padding: 8px 10px; selection-background-color: #dbe8ff; }
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus { border-color: #8db3ff; }
QLineEdit#search { background: #f4f5f8; border: none; border-radius: 8px; min-width: 190px; }
QComboBox#tagFilter { background: #ffffff; border: 1px solid #e1e5ec; }
QComboBox#tagFilter[hasSelection="true"] { background: #eaf1ff; border: 1px solid #8db3ff; color: #2467d8; font-weight: 600; }
QComboBox { min-width: 80px; padding-right: 21px; }
QComboBox::drop-down { border: none; width: 27px; margin-right: 2px; }
QComboBox::down-arrow { image: none; width: 0px; height: 0px; }
QComboBox QAbstractItemView { background: white; border: 1px solid #dfe4eb; border-radius: 8px; padding: 5px; selection-background-color: #e6efff; selection-color: #2467d8; color: #252b37; }
QComboBox QAbstractItemView::item { min-height: 28px; padding: 4px 8px; border-radius: 5px; }
QFrame#metric { background: #ffffff; border: 1px solid #e5e8ed; border-radius: 12px; }
QFrame#metric:hover { background: #f8faff; border-color: #c7d8f8; }
QFrame#metric[selected="true"] { background: #eaf1ff; border: 2px solid #3478f6; }
QFrame#metric[selected="true"] QLabel { color: #245fc5; }
QTreeWidget { background: transparent; border: none; outline: none; }
QTreeWidget::item { height: 33px; border-radius: 6px; }
QTreeWidget::item:selected { background: #e3ebfa; color: #2467d8; }
QTreeWidget::item:hover { background: #e9edf4; }
QListView, QTableView, QListWidget { border: none; background: transparent; outline: none; selection-background-color: #eaf1ff; selection-color: #1f4f9f; }
QListWidget#tagPicker { background: #f7f9fc; border: 1px solid #e4e8ef; border-radius: 10px; padding: 7px; }
QListWidget#tagPicker::item { background: #ffffff; color: #536176; border: 1px solid #dce3ed; border-radius: 9px; padding: 5px 10px; }
QListWidget#tagPicker::item:hover { background: #f0f5ff; border-color: #bfd2f5; }
QListWidget#tagPicker::item:selected { background: #e6efff; color: #2467d8; border: 1px solid #86aef5; }
QListWidget#tagFilterList { background: #ffffff; border: none; min-width: 230px; }
QListWidget#tagFilterList::item { min-height: 30px; padding: 3px 6px; border-radius: 6px; }
QListWidget#tagFilterList::item:hover { background: #f0f5ff; color: #2467d8; }
QPushButton#quiet:hover { background: #edf3ff; color: #2467d8; }
QListWidget#quickTagList { background: #ffffff; border: none; padding: 8px; }
QListWidget#quickTagList::item { background: #f5f7fb; color: #5b6678; border: 1px solid #e1e6ee; border-radius: 9px; padding: 5px 10px; }
QListWidget#quickTagList::item:hover { background: #edf3ff; border-color: #c4d7f8; }
QListWidget#quickTagList::item:selected { background: #3478f6; color: #ffffff; border-color: #3478f6; }
QTableView { gridline-color: #f0f1f4; }
QTableView::item { padding: 8px; border-bottom: 1px solid #f0f1f4; }
QTableView::item:selected { background: #eaf1ff; color: #1f4f9f; border-bottom: 1px solid #c4d8fb; }
QHeaderView::section { background: #fafbfc; color: #89909f; border: none; border-bottom: 1px solid #eceef2; padding: 11px; font-size: 11px; }
QScrollBar:vertical { background: transparent; width: 9px; margin: 3px 1px; }
QScrollBar::handle:vertical { background: #d4d9e2; min-height: 35px; border-radius: 3px; }
QScrollBar::handle:vertical:hover { background: #b7c0cd; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QScrollBar:horizontal { height: 8px; background: transparent; }
QScrollBar::handle:horizontal { background: #d4d9e2; border-radius: 3px; min-width: 35px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QSplitter::handle { background: #eceef2; width: 1px; }
QMenu { background: white; border: 1px solid #dfe4eb; padding: 5px; border-radius: 8px; }
QMenu::item { padding: 8px 24px; border-radius: 5px; }
QMenu::item:selected { background: #edf3ff; color: #2467d8; }
QMenu#comboMenu { background: #ffffff; border: 1px solid #dce3ef; border-radius: 10px; padding: 6px; }
QMenu#comboMenu::item { min-height: 28px; padding: 6px 12px; border-radius: 6px; color: #344054; }
QMenu#comboMenu::item:hover { background: #f1f5fb; }
QMenu#comboMenu::item:checked { background: #e8f0ff; color: #2467d8; }
QMenu::separator { height: 1px; background: #eceef2; margin: 4px 8px; }
QPushButton#playerTool { background: #222a36; border: 1px solid #394453; border-radius: 8px; padding: 4px; }
QPushButton#playerTool:hover { background: #303b4b; border-color: #62718a; }
QPushButton#playerText { background: #252d39; color: #f1f4f8; border: 1px solid #3e4958; border-radius: 8px; padding: 7px 12px; font-weight: 500; }
QPushButton#playerText:hover { background: #323d4d; border-color: #64738b; color: #ffffff; }
QPushButton#playerClose { background: transparent; border: none; border-radius: 13px; padding: 3px; }
QPushButton#playerClose:hover { background: #303946; }
QComboBox#tagFilter[hasSelection="true"] { background: #eaf1ff; border: 1px solid #80aaff; color: #2467d8; font-weight: 600; }
QDialog { background: #fafbfc; }
QDialogButtonBox { margin-top: 8px; }
QProgressBar { border: none; background: #edf2fb; border-radius: 2px; height: 3px; }
QProgressBar::chunk { background: #3478f6; border-radius: 2px; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 15px; height: 15px; border: 1px solid #cbd3e0; border-radius: 4px; background: white; }
QCheckBox::indicator:unchecked { width: 15px; height: 15px; border: 1px solid #cbd3e0; border-radius: 4px; background: #ffffff; }
QCheckBox::indicator:hover { border-color: #8db3ff; }
QCheckBox::indicator:checked { background: #3478f6; border-color: #3478f6; }
QToolTip { background: #293344; color: white; border: none; padding: 7px; }
"""


def icon(name: str, color: str = "#7c8798", size: int = 20) -> QIcon:
    """Small consistent vector icons, no external image/font dependency."""
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(2)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 24, size / 24)
    p.setPen(
        QPen(
            QColor(color),
            1.65,
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
    )
    if name in ("folder", "category"):
        path = QPainterPath()
        path.moveTo(3, 7)
        path.lineTo(3, 5)
        path.lineTo(10, 5)
        path.lineTo(12, 8)
        path.lineTo(21, 8)
        path.lineTo(21, 19)
        path.lineTo(3, 19)
        path.closeSubpath()
        p.drawPath(path)
    elif name in ("image", "all"):
        p.drawRoundedRect(QRectF(3, 3, 18, 18), 3, 3)
        p.drawEllipse(QRectF(7, 7, 3, 3))
        p.drawPolyline(
            [QPoint(4, 18), QPoint(10, 12), QPoint(14, 16), QPoint(18, 11), QPoint(21, 15)]
        )
    elif name == "video":
        p.drawRoundedRect(QRectF(3, 5, 18, 14), 3, 3)
        path = QPainterPath()
        path.moveTo(10, 9)
        path.lineTo(16, 12)
        path.lineTo(10, 15)
        path.closeSubpath()
        p.drawPath(path)
    elif name == "grid":
        for x in (4, 14):
            for y in (4, 14):
                p.drawRoundedRect(QRectF(x, y, 6, 6), 1.2, 1.2)
    elif name == "list":
        for y in (6, 12, 18):
            p.drawLine(8, y, 21, y)
            p.drawPoint(3, y)
    elif name == "tag":
        path = QPainterPath()
        path.moveTo(3, 4)
        path.lineTo(13, 4)
        path.lineTo(22, 13)
        path.lineTo(13, 22)
        path.lineTo(3, 12)
        path.closeSubpath()
        p.drawPath(path)
        p.drawEllipse(QRectF(7, 7, 2, 2))
    elif name == "inbox":
        path = QPainterPath()
        path.moveTo(3, 13)
        path.lineTo(6, 5)
        path.lineTo(18, 5)
        path.lineTo(21, 13)
        path.lineTo(21, 20)
        path.lineTo(3, 20)
        path.closeSubpath()
        p.drawPath(path)
        p.drawPolyline(
            [
                QPoint(3, 13),
                QPoint(8, 13),
                QPoint(9, 16),
                QPoint(15, 16),
                QPoint(16, 13),
                QPoint(21, 13),
            ]
        )
    elif name == "trash":
        p.drawLine(3, 6, 21, 6)
        p.drawLine(9, 3, 15, 3)
        p.drawRoundedRect(QRectF(6, 6, 12, 15), 2, 2)
        p.drawLine(10, 10, 10, 17)
        p.drawLine(14, 10, 14, 17)
    elif name == "sync":
        # Two opposing arrow heads make the toolbar action read as sync even
        # at 16px, instead of looking like a generic history arrow.
        p.drawArc(QRectF(4, 4, 16, 16), 38 * 16, 218 * 16)
        p.drawPolyline([QPoint(5, 3), QPoint(5, 9), QPoint(11, 9)])
        p.drawArc(QRectF(4, 4, 16, 16), 218 * 16, 218 * 16)
        p.drawPolyline([QPoint(19, 21), QPoint(19, 15), QPoint(13, 15)])
    elif name in ("history", "undo"):
        p.drawArc(QRectF(4, 4, 16, 16), 45 * 16, 295 * 16)
        p.drawPolyline([QPoint(4, 3), QPoint(4, 9), QPoint(10, 9)])
        if name == "history":
            p.drawLine(12, 8, 12, 12)
            p.drawLine(12, 12, 16, 14)
    elif name == "search":
        p.drawEllipse(QRectF(3, 3, 13, 13))
        p.drawLine(15, 15, 21, 21)
    elif name == "plus":
        p.drawLine(12, 5, 12, 19)
        p.drawLine(5, 12, 19, 12)
    elif name == "filter":
        for y, start, end in ((6, 3, 21), (12, 6, 18), (18, 10, 14)):
            p.drawLine(start, y, end, y)
    elif name == "settings":
        p.drawEllipse(QRectF(5, 5, 14, 14))
        p.drawEllipse(QRectF(9, 9, 6, 6))
        for x, y, xx, yy in ((12, 2, 12, 5), (12, 19, 12, 22), (2, 12, 5, 12), (19, 12, 22, 12)):
            p.drawLine(x, y, xx, yy)
    elif name == "duplicate":
        p.drawRoundedRect(QRectF(3, 3, 13, 14), 2, 2)
        p.drawRoundedRect(QRectF(8, 8, 13, 14), 2, 2)
    elif name == "edit":
        p.drawLine(5, 19, 9, 18)
        p.drawLine(9, 18, 19, 8)
        p.drawLine(16, 5, 19, 8)
        p.drawLine(5, 19, 5, 15)
    elif name == "more":
        for x in (5, 12, 19):
            p.drawEllipse(QRectF(x - 1, 11, 2, 2))
    elif name == "arrow":
        p.drawLine(5, 12, 19, 12)
        p.drawPolyline([QPoint(14, 7), QPoint(19, 12), QPoint(14, 17)])
    elif name == "play":
        path = QPainterPath()
        path.moveTo(8, 4)
        path.lineTo(20, 12)
        path.lineTo(8, 20)
        path.closeSubpath()
        p.drawPath(path)
    elif name == "pause":
        p.drawRoundedRect(QRectF(7, 5, 4, 14), 1, 1)
        p.drawRoundedRect(QRectF(14, 5, 4, 14), 1, 1)
    elif name == "previous":
        p.drawLine(6, 5, 6, 19)
        p.drawPolyline([QPoint(18, 6), QPoint(10, 12), QPoint(18, 18)])
    elif name == "next":
        p.drawLine(18, 5, 18, 19)
        p.drawPolyline([QPoint(6, 6), QPoint(14, 12), QPoint(6, 18)])
    elif name == "repeat":
        p.drawArc(QRectF(4, 6, 16, 12), 180 * 16, 180 * 16)
        p.drawPolyline([QPoint(5, 5), QPoint(5, 10), QPoint(10, 10)])
        p.drawPolyline([QPoint(19, 19), QPoint(19, 14), QPoint(14, 14)])
    elif name == "shuffle":
        p.drawPolyline([QPoint(4, 7), QPoint(8, 7), QPoint(16, 17), QPoint(20, 17)])
        p.drawPolyline([QPoint(16, 7), QPoint(20, 7), QPoint(16, 12)])
        p.drawPolyline([QPoint(17, 14), QPoint(20, 17), QPoint(17, 20)])
    elif name == "fullscreen":
        p.drawPolyline([QPoint(4, 9), QPoint(4, 4), QPoint(9, 4)])
        p.drawPolyline([QPoint(15, 4), QPoint(20, 4), QPoint(20, 9)])
        p.drawPolyline([QPoint(4, 15), QPoint(4, 20), QPoint(9, 20)])
        p.drawPolyline([QPoint(15, 20), QPoint(20, 20), QPoint(20, 15)])
    elif name == "external":
        p.drawRoundedRect(QRectF(4, 6, 13, 14), 2, 2)
        p.drawPolyline([QPoint(12, 4), QPoint(20, 4), QPoint(20, 12)])
        p.drawLine(20, 4, 11, 13)
    elif name == "minimize":
        p.drawLine(5, 17, 19, 17)
    elif name == "maximize":
        p.drawRoundedRect(QRectF(5, 5, 14, 14), 1.5, 1.5)
    elif name == "close":
        p.drawLine(6, 6, 18, 18)
        p.drawLine(18, 6, 6, 18)
    elif name == "check":
        p.drawPolyline([QPoint(5, 12), QPoint(10, 17), QPoint(19, 7)])
    p.end()
    return QIcon(pixmap)


def label(text: str, name: str = "") -> QLabel:
    result = QLabel(text)
    if name:
        result.setObjectName(name)
    return result


def button(
    text: str, callback: Callable | None = None, *, glyph: str = "", kind: str = ""
) -> QPushButton:
    result = QPushButton(text)
    result.setCursor(Qt.CursorShape.PointingHandCursor)
    if kind:
        result.setObjectName(kind)
    if glyph:
        result.setIcon(icon(glyph, "white" if kind == "primary" else "#758196"))
        result.setIconSize(QSize(17, 17))
    if callback:
        result.clicked.connect(callback)
    return result


def format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{size} B"
        value /= 1024
    return ""


PALETTE = {
    "canvas": "#f5f5f7",
    "surface": "#ffffff",
    "surface_subtle": "#fafbfc",
    "ink": "#202633",
    "muted": "#89909f",
    "line": "#e5e8ed",
    "accent": "#3478f6",
    "accent_soft": "#eaf1ff",
    "sidebar": "#f3f4f7",
}


def apply_palette(app):
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(PALETTE["canvas"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(PALETTE["surface"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(PALETTE["ink"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(PALETTE["surface"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(PALETTE["accent_soft"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(PALETTE["accent"]))
    app.setPalette(palette)
