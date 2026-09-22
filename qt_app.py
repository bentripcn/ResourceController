"""Compatibility entry point for the modular Qt workbench."""

from __future__ import annotations

import os
import sys


def _prepare_qt_dll_search_path() -> None:
    """Register bundled Qt directories before importing any PySide6 module.

    PyInstaller's one-folder layout keeps Qt's extension modules in
    ``_internal/PySide6`` while the Qt and shiboken DLLs live beside that
    directory.  Windows does not search those sibling directories for a
    transitive DLL dependency, so register all of them explicitly.  Keeping
    this bootstrap in the entry point as well as the runtime hook makes the
    launcher resilient when a Windows loader has a different default search
    policy.
    """

    if sys.platform != "win32":
        return
    bundle_root = getattr(sys, "_MEIPASS", "")
    roots = (bundle_root, os.path.join(bundle_root, "_internal"))
    package_root = next(
        (root for root in roots if os.path.isdir(os.path.join(root, "PySide6"))),
        "",
    )
    if not package_root:
        return
    candidates = (
        package_root,
        os.path.join(package_root, "PySide6"),
        os.path.join(package_root, "shiboken6"),
    )
    handles = []
    for path in candidates:
        if os.path.isdir(path):
            try:
                handles.append(os.add_dll_directory(path))
            except (AttributeError, OSError):
                # PATH fallback below still supports older Windows builds.
                pass
    # Keep AddDllDirectory handles alive for the entire process lifetime.
    globals()["_QT_DLL_HANDLES"] = handles
    os.environ["PATH"] = os.pathsep.join(candidates) + os.pathsep + os.environ.get("PATH", "")


_prepare_qt_dll_search_path()

from PySide6.QtWidgets import QFileDialog as QFileDialog

from rc_app.bootstrap import main as main
from rc_app.ui.jobs import Job as Job
from rc_app.ui.jobs import JobSignals as JobSignals
from rc_app.ui.models import ResourceModel as ResourceModel
from rc_app.ui.player import MediaPreview as MediaPreview
from rc_app.ui.theme import BLUE as BLUE
from rc_app.ui.theme import INK as INK
from rc_app.ui.theme import MUTED as MUTED
from rc_app.ui.theme import STYLE as STYLE
from rc_app.ui.theme import TYPE_LABELS as TYPE_LABELS
from rc_app.ui.theme import button as button
from rc_app.ui.theme import format_size as format_size
from rc_app.ui.theme import icon as icon
from rc_app.ui.theme import label as label
from rc_app.ui.thumbnails import ThumbnailStore as ThumbnailStore
from rc_app.ui.widgets import CardDelegate as CardDelegate
from rc_app.ui.widgets import CategoryTree as CategoryTree
from rc_app.ui.widgets import ReviewDialog as ReviewDialog
from rc_app.ui.widgets import ModernComboBox as ModernComboBox
from rc_app.ui.widgets import MultiTagComboBox as MultiTagComboBox
from rc_app.ui.widgets import SegmentedGrade as SegmentedGrade
from rc_app.ui.widgets import TagChipView as TagChipView
from rc_app.ui.widgets import TitleBar as TitleBar
from rc_app.ui.window import MainWindow as MainWindow

if __name__ == "__main__":
    raise SystemExit(main())
