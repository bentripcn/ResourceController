"""Qt controller integration tests using a real, isolated resource library."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

try:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QFontDatabase, QImage, QColor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog
    from qt_app import MainWindow, STYLE, ReviewDialog, MediaPreview
    from rc_app.ui.player import SeekSlider
    QT_AVAILABLE = True
except ImportError:
    QT_AVAILABLE = False


@unittest.skipUnless(QT_AVAILABLE, 'PySide6 is required for Qt integration tests')
class QtWorkbenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        font = Path('C:/Windows/Fonts/msyh.ttc')
        if font.exists(): QFontDatabase.addApplicationFont(str(font))
        cls.app.setStyleSheet(STYLE)

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='.qt-test-', dir=Path.cwd())).resolve()
        self.source = self.root / 'source'; self.source.mkdir()
        picture = QImage(80, 50, QImage.Format.Format_RGB32); picture.fill(QColor('#8dac9e'))
        picture.save(str(self.source / 'sunset.png'))
        picture.save(str(self.source / 'A_coast [travel].png'))
        folder = self.source / 'collection'; folder.mkdir(); (folder / 'private.txt').write_text('Do not index or modify')
        self.window = MainWindow(data_dir=self.root / 'data')
        self.window.lib.configure(str(self.source))
        self.window.lib.scan(); self.window.refresh()
        self.window.resize(1450, 900); self.window.show(); self.app.processEvents()
        self.errors = []
        self.window.error = self.errors.append

    def tearDown(self):
        self.wait_idle()
        self.window.close(); self.app.processEvents()
        assert self.root.is_relative_to(Path.cwd().resolve())
        shutil.rmtree(self.root)

    def wait_idle(self):
        deadline = time.monotonic() + 10
        while self.window.busy and time.monotonic() < deadline:
            self.app.processEvents(); time.sleep(.01)
        self.app.processEvents()
        self.assertFalse(self.window.busy, 'background operation did not finish')

    def select(self, row=0):
        selection = self.window.grid.selectionModel()
        selection.select(self.window.model.index(row, 0), selection.SelectionFlag.ClearAndSelect | selection.SelectionFlag.Rows)
        self.app.processEvents()

    def click_row(self, row=0, modifiers=Qt.KeyboardModifier.NoModifier):
        index = self.window.model.index(row, 0)
        rect = self.window.grid.visualRect(index)
        QTest.mouseClick(self.window.grid.viewport(), Qt.MouseButton.LeftButton, modifiers, rect.center())
        self.app.processEvents()

    def test_scan_picker_uses_path_property_and_preserves_atomic_folder(self):
        with patch('qt_app.QFileDialog.getExistingDirectory', return_value=str(self.source)):
            self.window.choose_root()
            self.wait_idle()
        self.assertEqual(self.window.model.rowCount(), 3)
        self.assertEqual(self.errors, [])
        self.assertNotIn('private', [r['name'] for r in self.window.model.rows])

    def test_filters_and_grid_table_share_selection(self):
        self.window.grade_filter.setCurrentIndex(1)
        self.assertEqual(self.window.model.rowCount(), 1)
        self.assertEqual(self.window.model.rows[0]['grade'], 'A')
        self.select(); selected = self.window.selected_ids()
        self.window.change_layout(1)
        self.assertEqual(self.window.views.currentWidget(), self.window.table)
        self.assertEqual(self.window.selected_ids(), selected)
        self.assertEqual(len(self.window.table.selectionModel().selectedRows()), 1)
        self.window.search.setText('unfindable'); self.window.refresh_resources()
        self.assertEqual(self.window.model.rowCount(), 0)
        self.assertEqual(self.window.views.currentWidget(), self.window.empty)

    def test_grid_reflows_after_hidden_page_resizes(self):
        # Reproduce the intermittent blank column: resize while the empty
        # stacked page is visible, then return to the icon grid.
        for number in range(5):
            picture = QImage(40, 30, QImage.Format.Format_RGB32)
            picture.fill(QColor('#7f9fbf'))
            picture.save(str(self.source / f'extra-{number}.png'))
        self.window.lib.scan(); self.window.refresh()
        self.window.search.setText('no-results-at-all')
        self.window.refresh_resources()
        self.assertEqual(self.window.views.currentWidget(), self.window.empty)
        self.window.resize(1700, 900)
        self.app.processEvents()
        self.window.search.clear()
        self.window.refresh_resources()
        self.app.processEvents()
        self.assertEqual(self.window.views.currentWidget(), self.window.grid)
        width = self.window.grid.viewport().width()
        expected = min(self.window.model.rowCount(), max(1, width // 224))
        first_top = self.window.grid.visualRect(self.window.model.index(0, 0)).top()
        first_row = sum(
            self.window.grid.visualRect(self.window.model.index(row, 0)).top() == first_top
            for row in range(self.window.model.rowCount())
        )
        self.assertEqual(first_row, expected)

    def test_real_mouse_selection_updates_inspector_and_supports_multiselect(self):
        first = self.window.model.index(0, 0)
        second = self.window.model.index(1, 0)
        QTest.mouseClick(self.window.grid.viewport(), Qt.MouseButton.LeftButton,
                         pos=self.window.grid.visualRect(first).center())
        self.app.processEvents()
        self.assertEqual(self.window.selected_ids(), [self.window.model.rows[0]["id"]])
        self.assertEqual(self.window.detail_name.text(), self.window.model.rows[0]["name"])
        QTest.mouseClick(self.window.grid.viewport(), Qt.MouseButton.LeftButton,
                         Qt.KeyboardModifier.ControlModifier,
                         self.window.grid.visualRect(second).center())
        self.app.processEvents()
        self.assertEqual(len(self.window.selected_ids()), 2)
        self.window.grid.selectionModel().clearSelection()
        self.app.processEvents()
        self.assertEqual(self.window.selected_ids(), [])
        self.assertIn("选择一个资源", self.window.detail_name.text())

    def test_review_batch_operation_and_undo_update_files_and_view(self):
        resource = next(r for r in self.window.model.rows if r['name'] == 'sunset')
        with patch.object(ReviewDialog, 'exec', return_value=QDialog.DialogCode.Accepted):
            self.window.review('Grade', lambda preview: self.window.lib.batch_update([resource['id']], grade='B', add_tags=['sea'], preview=preview))
            self.wait_idle()
            self.assertTrue((self.source / 'B_sunset [sea].png').exists())
            self.assertFalse((self.source / 'sunset.png').exists())
            self.window.undo(); self.wait_idle()
        self.assertTrue((self.source / 'sunset.png').exists())
        self.assertEqual(self.errors, [])

    def test_non_delete_operations_run_without_confirmation(self):
        resource = next(r for r in self.window.model.rows if r['name'] == 'sunset')
        self.window.review('Grade', lambda preview: self.window.lib.batch_update([resource['id']], grade='C', preview=preview))
        self.wait_idle()
        self.assertFalse((self.source / 'sunset.png').exists())
        self.assertTrue((self.source / 'C_sunset.png').exists())

    def test_category_drop_moves_resource_after_review(self):
        self.window.lib.create_category('travel/coast'); self.window.refresh()
        resource = next(r for r in self.window.model.rows if r['name'] == 'sunset')
        with patch.object(ReviewDialog, 'exec', return_value=QDialog.DialogCode.Accepted):
            self.window.category_tree.resourcesDropped.emit([resource['id']], 'travel/coast')
            self.wait_idle()
        self.assertTrue((self.source / 'travel' / 'coast' / 'sunset.png').exists())
        self.window.navigate('all', 'travel')
        self.assertEqual(self.window.model.rowCount(), 1)
        self.assertEqual(self.errors, [])

    def test_qtest_click_updates_inspector_and_ctrl_multiselect(self):
        image_row = next(i for i, r in enumerate(self.window.model.rows) if r['type'] == 'image')
        self.click_row(image_row)
        selected = self.window.selected_resources()
        self.assertEqual(len(selected), 1)
        self.assertEqual(self.window.detail_name.text(), selected[0]['name'])
        self.assertIn('图片', self.window.detail_kind.text())
        other_row = next(i for i, r in enumerate(self.window.model.rows) if i != image_row)
        self.click_row(other_row, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(len(self.window.selected_resources()), 2)
        self.assertTrue(self.window.batchbar.isVisible())

    def test_metric_multi_toggle_preserves_category_scope(self):
        self.window.lib.create_category('travel')
        resources = self.window.lib.resources()
        self.window.lib.batch_update([r['id'] for r in resources if r['type'] == 'image'], category='travel')
        self.window.lib.scan(); self.window.navigate('all', 'travel')
        self.assertEqual(self.window.category, 'travel')
        QTest.mouseClick(self.window.metric_frames['images'], Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertEqual(self.window.category, 'travel')
        self.assertTrue(self.window.metric_filters)
        self.assertTrue(all(r['type'] == 'image' for r in self.window.model.rows))
        QTest.mouseClick(self.window.metric_frames['folders'], Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertEqual(self.window.category, 'travel')
        self.assertEqual({r['type'] for r in self.window.model.rows}, {'image', 'folder'} if any(r['type'] == 'folder' for r in self.window.lib.resources(category='travel')) else {'image'})
        QTest.mouseClick(self.window.metric_frames['images'], Qt.MouseButton.LeftButton)
        self.app.processEvents()
        self.assertEqual(self.window.category, 'travel')
        self.assertEqual({r['type'] for r in self.window.model.rows}, {'folder'} if self.window.model.rows else set())

    def test_title_and_metric_counts_follow_selected_parent_category(self):
        images = [r for r in self.window.model.rows if r['type'] == 'image']
        self.window.lib.create_category('travel')
        self.window.lib.batch_update([images[0]['id']], category='travel')
        self.window.lib.create_category('travel/coast')
        self.window.lib.batch_update([images[1]['id']], category='travel/coast')
        self.window.refresh()
        self.window.navigate('all', 'travel')
        self.assertEqual(self.window.windowTitle(), '资源库')
        self.assertEqual(self.window.metric_labels['images'].text(), '2')
        self.assertEqual(self.window.model.rowCount(), 2)

    def test_choose_target_library_after_scan(self):
        target = self.root / 'target'; target.mkdir()
        with patch('rc_app.ui.window.QFileDialog.getExistingDirectory', return_value=str(target)):
            self.window.choose_library()
            self.wait_idle()
        self.assertEqual(self.window.lib.library_root, target.resolve())
        self.assertEqual(self.errors, [])

    def test_metadata_dialog_values_survive_dialog_destruction(self):
        self.select(0)
        captured = {}
        with patch.object(self.window, 'review', side_effect=lambda title, operation: captured.setdefault('operation', operation)), \
             patch.object(QDialog, 'exec', return_value=QDialog.DialogCode.Accepted):
            self.window.edit_metadata()
        operation = captured.get('operation')
        self.assertIsNotNone(operation)
        # Calling after the modal has been destroyed catches closures that
        # retain QComboBox/QLineEdit wrappers instead of plain Python values.
        operation(True)

    def test_video_seek_clamps_at_duration_and_right_hold_restores_rate(self):
        # A tiny fixture is enough because this test replaces the decoder;
        # the service only needs the extension to classify it as video.
        (self.source / 'sample.mp4').write_bytes(b'video fixture')
        self.window.lib.scan(); self.window.refresh()
        video = next(r for r in self.window.model.rows if r['type'] == 'video')
        preview = MediaPreview([video], 0, self.window)

        class StateClass:
            PlayingState = 1

        class MediaStatusClass:
            EndOfMedia = object()

        class FakePlayer:
            PlaybackState = StateClass
            MediaStatus = MediaStatusClass
            def __init__(self): self._position = 5000; self.rate = 1.0; self.playing = False
            def duration(self): return 5000
            def position(self): return self._position
            def setPosition(self, value): self._position = value
            def playbackRate(self): return self.rate
            def setPlaybackRate(self, value): self.rate = value
            def playbackState(self): return self.PlaybackState.PlayingState if self.playing else 0
            def play(self): self.playing = True
            def pause(self): self.playing = False

        fake = FakePlayer(); preview.player = fake
        preview._seek_to(-100); self.assertEqual(fake._position, 0)
        preview._seek_to(99999); self.assertEqual(fake._position, 5000)
        preview._right_held = True; preview._start_fast_forward()
        self.assertEqual(fake.rate, 3.0)
        preview._release_right_hold(False)
        self.assertEqual(fake.rate, 1.0)
        preview.close()

    def test_video_seek_slider_supports_click_and_drag(self):
        slider = SeekSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 10000)
        slider.resize(400, 30)
        slider.show()
        self.app.processEvents()
        QTest.mousePress(slider, Qt.MouseButton.LeftButton, pos=QPoint(40, 15))
        self.assertTrue(slider.isSliderDown())
        QTest.mouseMove(slider, QPoint(300, 15))
        QTest.mouseRelease(slider, Qt.MouseButton.LeftButton, pos=QPoint(300, 15))
        self.assertFalse(slider.isSliderDown())
        self.assertGreaterEqual(slider.value(), 7000)
        slider.close()

    def test_folder_cover_picker_rejects_image_outside_atomic_folder(self):
        folder = next(r for r in self.window.model.rows if r['type'] == 'folder')
        outside = self.root / 'outside.png'
        QImage(20, 20, QImage.Format.Format_RGB32).save(str(outside))
        with patch('rc_app.ui.window.QFileDialog.getOpenFileName', return_value=(str(outside), '')):
            self.window.select_all()  # ensure the test selects only the folder below
            self.window.grid.selectionModel().clearSelection()
            index = next(i for i, r in enumerate(self.window.model.rows) if r['id'] == folder['id'])
            self.select(index)
            self.window.set_cover()
        self.assertTrue(self.errors)
        self.assertIn('文件夹资源内部', self.errors[-1])
        self.assertIsNone(self.window.lib.cover_path(folder['id']))


if __name__ == '__main__':
    unittest.main()
