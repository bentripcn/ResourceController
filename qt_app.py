"""Compatibility entry point for the modular Qt workbench."""

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
