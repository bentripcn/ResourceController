"""Interaction regressions for the player and the duplicate-check entry point."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QFontDatabase, QImage, QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget, QPushButton

from library import Library
from media_tools import resolve_ffmpeg
from rc_app.ui.player import MediaPreview
from rc_app.ui.theme import STYLE
from rc_app.ui.window import MainWindow


class PlayerRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")
        font = Path("C:/Windows/Fonts/msyh.ttc")
        if font.exists():
            QFontDatabase.addApplicationFont(str(font))
        cls.app.setStyleSheet(STYLE)

    def setUp(self):
        self.owner = QWidget()
        self.owner.set_video_cover_from_preview = Mock()
        # Start empty so keyboard/layout checks need no decoder or database.
        self.preview = MediaPreview([], 0, self.owner)
        self.preview.resources = [
            {"id": str(i), "name": str(i), "type": "image", "path": "unused.png"}
            for i in range(3)
        ]
        self.preview.control_bar.setEnabled(True)
        self.preview.show()
        self.preview._pointer_timer.stop()
        self.app.processEvents()

    def tearDown(self):
        self.preview.close()
        self.owner.close()
        self.app.processEvents()

    def test_up_down_navigate_once_even_with_child_focus(self):
        with patch.object(self.preview, "show_resource") as show:
            for child in (self.preview, self.preview.seek, self.preview.video):
                QTest.keyClick(child, Qt.Key.Key_Down)
                self.assertEqual(self.preview.position, 1)
                QTest.keyClick(child, Qt.Key.Key_Up)
                self.assertEqual(self.preview.position, 0)
            self.assertEqual(show.call_count, 6)

    def test_cover_visibility_preserves_button_positions_and_height(self):
        self.preview.resize(1080, 750)
        self.preview.cover_button.show()
        self.app.processEvents()
        buttons = [b for b in self.preview.control_bar.findChildren(QPushButton)
                   if b is not self.preview.cover_button]
        positions = [b.mapTo(self.preview, QPoint()) for b in buttons]
        self.preview.cover_button.hide()
        self.app.processEvents()
        self.assertEqual(positions, [b.mapTo(self.preview, QPoint()) for b in buttons])
        self.assertTrue(all(b.height() == 34 for b in buttons))
        self.assertLess(self.preview.cover_slot.mapTo(self.preview, QPoint()).x(),
                        self.preview.play_button.mapTo(self.preview, QPoint()).x())
        center = self.preview.play_button.mapTo(self.preview, self.preview.play_button.rect().center())
        self.assertLessEqual(abs(center.x() - self.preview.rect().center().x()), 2)
        self.assertFalse(hasattr(self.preview, "mode_button"))

    def test_fullscreen_only_bottom_edge_opens_and_exit_hides_immediately(self):
        self.preview.toggle_fullscreen()
        self.preview._pointer_timer.stop()
        self.app.processEvents()
        p = self.preview
        for y in (10, p.height() // 2, p.height() - 4, p.height() - 58):
            p._update_fullscreen_pointer(QPoint(50, y))
            self.assertTrue(p.control_bar.isHidden())
        p._update_fullscreen_pointer(QPoint(50, p.height() - 1))
        self.assertFalse(p.control_bar.isHidden())
        p._update_fullscreen_pointer(p.control_bar.mapTo(p, p.control_bar.rect().center()))
        self.assertFalse(p.control_bar.isHidden())
        p._update_fullscreen_pointer(QPoint(50, p.controls_panel.geometry().top() - 1))
        self.assertTrue(p.control_bar.isHidden())
        p._update_fullscreen_pointer(QPoint(50, p.height() - 10))
        self.assertTrue(p.control_bar.isHidden())
        QTest.keyClick(p, Qt.Key.Key_Escape)
        self.assertFalse(p.isFullScreen())
        self.assertTrue(p.isVisible())

    def test_autoplay_remains_sequential_and_loops_to_start(self):
        with patch.object(self.preview, "show_resource"):
            self.preview.slideshow = True
            self.preview.step()
            self.assertEqual(self.preview.position, 1)
            self.preview.step()
            self.assertEqual(self.preview.position, 2)
            self.preview.step()
            self.assertEqual(self.preview.position, 0)
            self.assertTrue(self.preview.slideshow)

    def test_cover_label_and_canvas_drag_after_zoom(self):
        self.assertEqual(self.preview.cover_button.text(), "设当前帧为封面")
        from rc_app.ui.media_canvas import MediaCanvas
        canvas = MediaCanvas()
        canvas.resize(500, 350); canvas.show()
        self.addCleanup(canvas.close)
        image = QImage(1200, 800, QImage.Format.Format_RGB32)
        image.fill(QColor("#6e9db6"))
        canvas.set_image(image)
        self.app.processEvents()
        canvas.zoom_at(QPoint(120, 100), 4)
        before = canvas.mapToScene(canvas.viewport().rect().center())
        QTest.mousePress(canvas.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(150, 140))
        QTest.mouseMove(canvas.viewport(), QPoint(205, 180), 80)
        QTest.mouseRelease(canvas.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(205, 180))
        after = canvas.mapToScene(canvas.viewport().rect().center())
        self.assertGreater((after - before).manhattanLength(), 1)

    def test_real_video_progress_and_keys_after_mouse_pause(self):
        ffmpeg = resolve_ffmpeg()
        if not ffmpeg:
            self.skipTest("FFmpeg fixture generator is unavailable")
        with tempfile.TemporaryDirectory(prefix="rc-player-") as folder:
            video = Path(folder) / "sample.mp4"
            subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                            "-i", "testsrc2=size=160x90:rate=15", "-t", "6", "-c:v", "libx264",
                            "-pix_fmt", "yuv420p", str(video)], check=True, capture_output=True,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            p = self.preview
            p.resources = [{"id": "clip", "name": "clip", "type": "video", "path": str(video)}]
            p.position = 0
            p.show_resource()
            deadline = time.monotonic() + 8
            while p.seek.value() < 300 and time.monotonic() < deadline:
                QTest.qWait(50)
            self.assertGreater(p.seek.maximum(), 5000)
            self.assertGreater(p.seek.value(), 0)
            QTest.mouseClick(p.video, Qt.MouseButton.LeftButton)
            self.assertEqual(p.player.playbackState(), p.player.PlaybackState.PausedState)
            before = p.player.position()
            QTest.keyClick(p, Qt.Key.Key_Right)
            self.assertGreaterEqual(p.player.position(), before + 2900)
            QTest.keyClick(p, Qt.Key.Key_Left)
            self.assertLessEqual(p.player.position(), before + 100)
            # Real pointer events target the graphics viewport, not its frame.
            QTest.mouseClick(p.video.viewport(), Qt.MouseButton.LeftButton)
            self.assertEqual(p.player.playbackState(), p.player.PlaybackState.PlayingState)
            self.assertFalse(p.video.content_size.isEmpty())
            self.assertTrue(p.video_item.videoSink().videoFrame().isValid())
            before = p.player.position()
            p.video.zoom_at(QPoint(60, 40), 1)
            self.assertAlmostEqual(p.video.zoom, 1.1)
            self.assertGreaterEqual(p.player.position(), before)
            # Loading the same video again must restore its fit and dimensions.
            p.show_resource()
            deadline = time.monotonic() + 5
            while (p.video.content_size.isEmpty() or p.seek.value() < 200) and time.monotonic() < deadline:
                QTest.qWait(50)
            self.assertFalse(p.video.content_size.isEmpty())
            self.assertGreater(p.seek.value(), 0)
            self.assertEqual(p.video.zoom, 1)
            still = Path(folder) / "large.png"
            image = QImage(2560, 1600, QImage.Format.Format_RGB32)
            image.fill(QColor("#729aab"))
            image.save(str(still))
            p.resources.append({"id": "still", "name": "still", "type": "image", "path": str(still)})
            p.toggle_fullscreen()
            p._pointer_timer.stop()
            self.app.processEvents()
            size = p.size()
            for _ in range(2):
                QTest.keyClick(p, Qt.Key.Key_Down)
                self.app.processEvents()
                p._show_fullscreen_controls()
                self.assertEqual(p.size(), size)
                self.assertTrue(p.rect().contains(p.controls_panel.geometry()))
                QTest.keyClick(p, Qt.Key.Key_Up)
                deadline = time.monotonic() + 5
                while p.seek.value() < 200 and time.monotonic() < deadline:
                    QTest.qWait(50)
                p._show_fullscreen_controls()
                self.assertGreater(p.seek.value(), 0)
                self.assertEqual(p.size(), size)
                self.assertTrue(p.rect().contains(p.controls_panel.geometry()))
                self.assertTrue(p.video_controls.isVisible())
                self.assertFalse(p.video.content_size.isEmpty())
            p.close()  # Release the decoder before the fixture is removed.


class DuplicateEntryRegressions(unittest.TestCase):
    def make_owner(self, folders=()):
        owner = SimpleNamespace(lib=Mock(), category="travel", show_duplicates=Mock(),
                                _select_item=Mock(), run_job=Mock())
        owner.lib.source_root = Path("source")
        owner.lib.resources.return_value = list(folders)
        return owner

    def test_both_modes_start_job_and_deliver_results(self):
        for title, mode in (("完全重复 · SHA-256", "exact"), ("相似图片 / 视频 · 感知哈希", "similar")):
            owner = self.make_owner()
            owner._select_item.return_value = (title, True)
            MainWindow.duplicates(owner)
            owner.run_job.assert_called_once()
            _, operation, done = owner.run_job.call_args.args
            done(operation())
            owner.lib.duplicates.assert_called_once_with(mode=mode, category="travel", expand_folder=None)
            owner.show_duplicates.assert_called_once_with(owner.lib.duplicates.return_value)

    def test_cancel_does_not_start_job(self):
        owner = self.make_owner()
        owner._select_item.return_value = ("", False)
        MainWindow.duplicates(owner)
        owner.run_job.assert_not_called()

    def test_folders_stay_atomic_by_default(self):
        owner = self.make_owner([{"type": "folder", "name": "opaque", "path": "opaque"}])
        owner._select_item.side_effect = [("完全重复 · SHA-256", True), ("不展开（文件夹按黑盒处理）", True)]
        MainWindow.duplicates(owner)
        owner.run_job.call_args.args[1]()
        owner.lib.duplicates.assert_called_once_with(mode="exact", category="travel", expand_folder=None)

    def test_detection_reads_actual_files_and_returns_results_via_entry(self):
        with tempfile.TemporaryDirectory(prefix="rc-dedup-") as folder:
            root = Path(folder)
            media = root / "media"
            media.mkdir()
            picture = QImage(30, 20, QImage.Format.Format_RGB32)
            picture.fill(QColor("#5b87a2"))
            picture.save(str(media / "one.png"))
            (media / "two.png").write_bytes((media / "one.png").read_bytes())
            with patch("library.global_data_path", return_value=root / "global.sqlite3"):
                lib = Library(root / "data")
                try:
                    lib.configure(str(media))
                    lib.scan()
                    owner = self.make_owner()
                    owner.lib, owner.category = lib, None
                    for title in ("完全重复 · SHA-256", "相似图片 / 视频 · 感知哈希"):
                        owner._select_item.return_value = (title, True)
                        MainWindow.duplicates(owner)
                        result = owner.run_job.call_args.args[1]()
                        self.assertEqual(len(result["groups"]), 1)
                        self.assertEqual(len(result["groups"][0]["resources"]), 2)
                        self.assertEqual(result["errors"], [])
                finally:
                    lib.close()


if __name__ == "__main__":
    unittest.main()
