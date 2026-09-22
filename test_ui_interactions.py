"""Regression checks for grouped comparison, canvas geometry and view interactions."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QFontDatabase, QImage, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QListWidget, QAbstractItemView

from library import Library
from rc_app.ui.duplicate_results import DuplicateResultsDialog
from rc_app.ui.interactions import GradePopup, SmoothScroll
from rc_app.ui.media_canvas import MediaCanvas
from rc_app.ui.player import MediaPreview
from rc_app.ui.theme import STYLE
from rc_app.ui.window import MainWindow


def wheel(widget, delta, position=None):
    point = position or widget.rect().center()
    event = QWheelEvent(QPointF(point), QPointF(widget.mapToGlobal(point)), QPoint(),
                        QPoint(0, delta), Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(widget, event)


class InteractionRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")
        QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
        cls.app.setStyleSheet(STYLE)

    def test_zoom_anchors_cursor_and_resets_at_fit(self):
        canvas = MediaCanvas()
        self.addCleanup(canvas.close)
        canvas.resize(900, 600)
        canvas.show()
        image = QImage(2400, 1600, QImage.Format.Format_RGB32)
        image.fill(QColor("#839db7"))
        canvas.set_image(image)
        self.app.processEvents()
        point = QPoint(270, 210)
        before = canvas.mapToScene(point)
        wheel(canvas.viewport(), 120, point)
        self.assertAlmostEqual(canvas.zoom, 1.1)
        after = canvas.mapToScene(point)
        self.assertLess((after - before).manhattanLength(), 8)
        wheel(canvas.viewport(), -120, point)
        self.assertEqual(canvas.zoom, 1)
        wheel(canvas.viewport(), -120, point)
        self.assertEqual(canvas.zoom, 1)
        for _ in range(30):
            wheel(canvas.viewport(), 120, point)
        self.assertEqual(canvas.zoom, 8)
        canvas.set_image(image)
        self.assertEqual(canvas.zoom, 1)

    def test_large_images_do_not_grow_fullscreen_or_displace_controls(self):
        p = MediaPreview([], 0)
        self.addCleanup(p.close)
        p.resources = [{"id": str(i), "name": "风景" * 50, "type": "image", "path": "unused"}
                       for i in range(3)]
        p.show()
        large = QImage(2560, 1600, QImage.Format.Format_RGB32)
        large.fill(QColor("#839db7"))
        with patch.object(p, "_read_image", return_value=large):
            p.show_resource()
            p.toggle_fullscreen()
            p._pointer_timer.stop()
            self.app.processEvents()
            size = p.size()
            for key in (Qt.Key.Key_Down, Qt.Key.Key_Down, Qt.Key.Key_Up, Qt.Key.Key_Up):
                QTest.keyClick(p, key)
                self.app.processEvents()
                p._show_fullscreen_controls()
                self.app.processEvents()
                self.assertEqual(p.size(), size)
                self.assertTrue(p.rect().contains(p.controls_panel.geometry()))
                for widget in p.control_bar.findChildren(type(p.play_button)):
                    if widget.isVisible():
                        self.assertTrue(p.rect().contains(widget.mapTo(p, widget.rect().bottomRight())))
                p._hide_fullscreen_controls()
            QTest.keyClick(p, Qt.Key.Key_Escape)
            self.app.processEvents()
            self.assertTrue(p.controls_panel.isVisible())
            self.assertFalse(p.isFullScreen())

    def test_duplicate_checks_are_independent_of_selection_and_preview_is_grouped(self):
        resources = [{"id": str(i), "name": f"图片 {i}", "type": "image",
                      "path": f"D:/资源库/风景/图片 {i}.jpg", "size": 123456, "grade": "A"}
                     for i in range(3)]
        dialog = DuplicateResultsDialog({"groups": [{"resources": resources[:2]},
                                                    {"resources": resources[2:]}]})
        self.addCleanup(dialog.close)
        dialog.show()
        self.app.processEvents()
        item = dialog.resource_items[1]
        rect = dialog.listing.visualItemRect(item)
        QTest.mouseClick(dialog.listing.viewport(), Qt.MouseButton.LeftButton,
                         pos=QPoint(22, rect.center().y()))
        self.assertEqual(dialog.selected_ids(), ["1"])
        QTest.mouseClick(dialog.listing.viewport(), Qt.MouseButton.LeftButton,
                         pos=QPoint(22, rect.center().y()))
        self.assertEqual(dialog.selected_ids(), [])
        QTest.mouseClick(dialog.listing.viewport(), Qt.MouseButton.LeftButton,
                         pos=QPoint(22, rect.center().y()))
        self.assertEqual(dialog.selected_ids(), ["1"])
        self.assertTrue(dialog.discard_button.isEnabled())
        self.assertIn("1", dialog.selection_label.text())
        with patch("rc_app.ui.duplicate_results.MediaPreview") as preview:
            QTest.mouseClick(dialog.listing.viewport(), Qt.MouseButton.LeftButton,
                             pos=QPoint(150, rect.center().y()))
            QTest.mouseDClick(dialog.listing.viewport(), Qt.MouseButton.LeftButton,
                              pos=QPoint(150, rect.center().y()))
            preview.assert_called_once_with(resources[:2], 1, dialog)
            preview.return_value.exec.assert_called_once()
        self.assertEqual(dialog.selected_ids(), ["1"])
        dialog.listing.setCurrentItem(dialog.resource_items[2], 1)
        self.assertEqual(dialog.selected_ids(), ["1"])

    def test_temporary_duplicates_cannot_be_discarded(self):
        dialog = DuplicateResultsDialog({"temporary": True, "groups": [{"resources": [
            {"id": "1", "path": "D:/资源库/图片.jpg", "size": 20, "type": "image"}]}]})
        self.addCleanup(dialog.close)
        item = dialog.resource_items[0]
        self.assertFalse(item.flags() & Qt.ItemFlag.ItemIsUserCheckable)
        self.assertFalse(dialog.discard_button.isEnabled())

    def test_grade_popup_select_and_clear(self):
        popup = GradePopup("B")
        self.addCleanup(popup.close)
        values = []
        popup.chosen.connect(values.append)
        popup.popup(QPoint(100, 100))
        self.assertTrue(popup.grade_buttons[1].isChecked())
        QTest.mouseClick(popup.grade_buttons[0], Qt.MouseButton.LeftButton)
        self.assertEqual(values, ["A"])
        self.assertFalse(popup.isVisible())
        popup.popup(QPoint(100, 100))
        QTest.mouseClick(popup.clear_button, Qt.MouseButton.LeftButton)
        self.assertEqual(values, ["A", ""])

    def test_scroll_is_interpolated_reversible_and_clamped(self):
        view = QListWidget()
        self.addCleanup(view.close)
        view.addItems([str(i) for i in range(120)])
        view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        view.resize(400, 350)
        view.show()
        smooth = SmoothScroll(view)
        self.app.processEvents()
        wheel(view.viewport(), -120)
        self.assertEqual(view.verticalScrollBar().value(), 0)
        QTest.qWait(70)
        self.assertGreater(view.verticalScrollBar().value(), 0)
        self.assertLess(view.verticalScrollBar().value(), smooth.target)
        wheel(view.viewport(), 120)
        QTest.qWait(200)
        self.assertEqual(view.verticalScrollBar().value(), 0)
        wheel(view.viewport(), -120000)
        QTest.qWait(200)
        self.assertEqual(view.verticalScrollBar().value(), view.verticalScrollBar().maximum())

    def test_filter_animation_preserves_results_and_survives_rapid_toggle(self):
        with tempfile.TemporaryDirectory(prefix="rc-filter-") as folder:
            root = Path(folder)
            source = root / "source"
            source.mkdir()
            image = QImage(80, 50, QImage.Format.Format_RGB32)
            image.fill(QColor("#9babc4"))
            image.save(str(source / "A_风景 [旅行].png"))
            with patch("library.global_data_path", return_value=root / "global.sqlite3"):
                lib = Library(root / "data")
                lib.configure(str(source))
                lib.scan()
                window = MainWindow(library=lib)
                try:
                    window.show()
                    self.app.processEvents()
                    window.filter_metric("images")
                    count = window.model.rowCount()
                    QTest.mouseClick(window.filter_toggle, Qt.MouseButton.LeftButton)
                    QTest.qWait(240)
                    self.assertTrue(window.filter_panel.isHidden())
                    self.assertEqual(window.model.rowCount(), count)
                    self.assertEqual(window.metric_filters, {"images"})
                    self.assertIn("1", window.filter_toggle.text())
                    for _ in range(3):
                        QTest.mouseClick(window.filter_toggle, Qt.MouseButton.LeftButton)
                        QTest.qWait(35)
                    QTest.qWait(240)
                    self.assertTrue(window.filter_panel.isVisible())
                    self.assertGreaterEqual(window.filter_panel.height(), window.filter_panel.sizeHint().height())
                    self.assertEqual(window.model.rowCount(), count)
                finally:
                    window.close()
                    self.app.processEvents()


if __name__ == "__main__":
    unittest.main()
