"""rc_app.ui.player: extracted workbench component."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QCursor, QDesktopServices, QImage, QImageReader, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QApplication,
    QFrame,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QSlider,
    QStyle,
    QStackedWidget,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from rc_app.ui.theme import button, icon, label
from rc_app.ui.media_canvas import MediaCanvas


class SeekSlider(QSlider):
    """A media timeline that jumps directly to the clicked position."""

    def _value_at(self, x):
        span = max(1, self.width())
        position = max(0, min(span, int(x)))
        return QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), position, span)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.maximum() > self.minimum():
            value = self._value_at(event.position().x())
            self.setValue(value)
            self.setSliderDown(True)
            self.sliderPressed.emit()
            self.sliderMoved.emit(value)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.isSliderDown():
            value = self._value_at(event.position().x())
            self.setValue(value)
            self.sliderMoved.emit(value)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isSliderDown():
            value = self._value_at(event.position().x())
            self.setValue(value)
            self.sliderMoved.emit(value)
            self.setSliderDown(False)
            self.sliderReleased.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class MediaPreview(QDialog):
    """Image/video viewer; external opening remains available for uncommon codecs."""

    def __init__(self, resources, start, parent=None):
        super().__init__(parent)
        requested = resources[start] if resources and 0 <= start < len(resources) else None
        self.resources = [resource for resource in resources if resource.get("type") != "folder"]
        self.position = next(
            (i for i, resource in enumerate(self.resources) if requested and resource.get("id") == requested.get("id")),
            0,
        )
        self.player = None
        self._centered = False
        self.slideshow = False
        self.setWindowTitle("资源欣赏")
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.resize(1020, 750)
        self.setStyleSheet("QDialog { background: #15191f; } QLabel { color: #f4f6f9; }")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 18)
        self.heading = label("")
        self.heading.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.heading.setObjectName("previewHeading")
        self.heading.setCursor(Qt.CursorShape.OpenHandCursor)
        self.heading.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        layout.addWidget(self.heading)
        self.stack = QStackedWidget()
        self.stack.setMinimumSize(0, 0)
        self.stack.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        layout.addWidget(self.stack, 1)
        self.picture = MediaCanvas()
        self.stack.addWidget(self.picture)
        self.image = QImage()
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            from PySide6.QtMultimediaWidgets import QGraphicsVideoItem

            self.video = MediaCanvas()
            self.video_item = QGraphicsVideoItem()
            self.video.set_video_item(self.video_item)
            self.video.setMouseTracking(True)
            self.stack.addWidget(self.video)
            self.player = QMediaPlayer(self)
            self.audio = QAudioOutput(self)
            self.audio.setVolume(0.7)
            self.player.setAudioOutput(self.audio)
            self.player.setVideoOutput(self.video_item)
            self.player.errorOccurred.connect(lambda *_: self._video_error())
            self.player.mediaStatusChanged.connect(self._media_status)
            self.player.playbackStateChanged.connect(self._update_play_button)
        except ImportError:
            self.video = None
        self.controls_panel = QFrame(self)
        self.controls_panel.setObjectName("playerControls")
        self.controls_panel.setStyleSheet("QFrame#playerControls { background: #15191f; }")
        panel_layout = QVBoxLayout(self.controls_panel)
        panel_layout.setContentsMargins(12, 8, 12, 8)
        panel_layout.setSpacing(4)
        self.video_controls = QFrame()
        self.video_controls.setFixedHeight(28)
        controls = QHBoxLayout(self.video_controls)
        controls.setContentsMargins(0, 4, 0, 4)
        self.elapsed = QLabel("00:00")
        self.seek = SeekSlider(Qt.Orientation.Horizontal)
        self.seek.setRange(0, 0)
        self.seek.setSingleStep(1000)
        self.seek.setPageStep(3000)
        self.seek.sliderPressed.connect(self._seek_started)
        self.seek.sliderMoved.connect(self._seek_to)
        self.seek.sliderReleased.connect(self._seek_finished)
        self.total = QLabel("00:00")
        self.seek.setStyleSheet(
            "QSlider::groove:horizontal {height: 5px; background: #404957; border-radius: 2px;} QSlider::sub-page:horizontal {background: #5997ff; border-radius: 2px;} QSlider::handle:horizontal {background: white; width: 13px; margin: -4px 0; border-radius: 6px;}"
        )
        self.speed_label = QLabel("")
        self.speed_label.setMinimumWidth(50)
        controls.addWidget(self.elapsed)
        controls.addWidget(self.seek, 1)
        controls.addWidget(self.total)
        controls.addWidget(self.speed_label)
        self.video_controls.hide()
        panel_layout.addWidget(self.video_controls)
        self._seek_hold = QTimer(self)
        self._seek_hold.setSingleShot(True)
        self._seek_hold.timeout.connect(self._start_fast_forward)
        self._fast_forward = False
        self._right_held = False
        self._previous_rate = 1.0
        self._was_playing = False
        self._ended = False
        self._current_media_path = None
        self._seek_was_playing = False
        self._scrub_pause = QTimer(self)
        self._scrub_pause.setSingleShot(True)
        self._scrub_pause.timeout.connect(self._pause_after_scrub)
        if self.player:
            self.player.positionChanged.connect(self._position_changed)
            self.player.durationChanged.connect(self._duration_changed)
        # A few Windows backends do not emit positionChanged consistently
        # while the video surface is being resized or after a seek. Polling
        # keeps the timeline visually in sync without changing playback.
        self._progress_timer = QTimer(self)
        self._progress_timer.setInterval(120)
        self._progress_timer.timeout.connect(self._sync_progress)
        row = QGridLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(7)
        left_panel = QWidget()
        left = QHBoxLayout(left_panel)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(5)
        self.slide_button = button("自动播放", self.toggle_slideshow, kind="playerText")
        self.slide_button.setFixedWidth(110)
        left.addWidget(self.slide_button)
        center = QHBoxLayout(); center.setSpacing(5)
        previous = button("", lambda: self._manual_step(-1), glyph="previous", kind="playerTool")
        self.play_button = button("", self.toggle_play, glyph="play", kind="playerTool")
        following = button("", lambda: self._manual_step(1), glyph="next", kind="playerTool")
        center.addWidget(previous); center.addWidget(self.play_button); center.addWidget(following)
        right = QHBoxLayout(); right.setSpacing(5)
        self.cover_slot = QWidget()
        self.cover_slot.setFixedWidth(146)
        cover_layout = QHBoxLayout(self.cover_slot)
        cover_layout.setContentsMargins(0, 0, 0, 0)
        self.cover_button = button("设当前帧为封面", self.set_video_cover, kind="playerText")
        cover_layout.addWidget(self.cover_button)
        left.addWidget(self.cover_slot)
        external = button("系统应用打开", self.open_external, kind="playerText")
        fullscreen = button("", self.toggle_fullscreen, glyph="fullscreen", kind="playerTool")
        right.addWidget(external); right.addWidget(fullscreen)
        left.addStretch()
        right.insertStretch(0)
        right_panel = QWidget()
        right_panel.setLayout(right)
        right.setContentsMargins(0, 0, 0, 0)
        row.addWidget(left_panel, 0, 0)
        row.addLayout(center, 0, 1)
        row.addWidget(right_panel, 0, 2)
        # Equal side columns keep transport controls at the window center.
        for column in (0, 2):
            row.setColumnMinimumWidth(column, 270)
            row.setColumnStretch(column, 1)
        for control in (self.slide_button, self.cover_button, external, previous,
                        self.play_button, following, fullscreen):
            control.setFixedHeight(34)
            control.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            control.setAutoDefault(False)
        for control, glyph in ((previous, "previous"), (self.play_button, "play"),
                               (following, "next"), (fullscreen, "fullscreen")):
            control.setFixedWidth(34)
            control.setIcon(icon(glyph, "#d8e1ed"))
        self.control_bar = QWidget()
        self.control_bar.setLayout(row)
        self.control_bar.setFixedHeight(44)
        panel_layout.addWidget(self.control_bar)
        layout.addWidget(self.controls_panel)
        self.close_button = button("", self.accept, glyph="close", kind="playerClose")
        self.close_button.setFixedSize(26, 26)
        self.close_button.setIconSize(QSize(14, 14))
        self.close_button.setIcon(icon("close", "#d8e1ed", 14))
        self.close_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.close_button.setAutoDefault(False)
        self.close_button.setParent(self)
        self.close_button.move(self.width() - 44, 12)
        self.close_button.raise_()
        self.close_button.show()
        self.timer = QTimer(self)
        self.timer.setInterval(4000)
        self.timer.timeout.connect(lambda: self.step(1))
        # Native video surfaces may consume mouse move events. Poll the
        # pointer only in fullscreen so the bottom edge always remains usable.
        self._pointer_timer = QTimer(self)
        self._pointer_timer.setInterval(40)
        self._pointer_timer.timeout.connect(self._poll_fullscreen_pointer)
        self.setMouseTracking(True)
        self.stack.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        if self.video:
            self.video.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        QShortcut(QKeySequence("F11"), self, activated=self.toggle_fullscreen)
        # Focus can be on the video surface, slider or buttons; all route media
        # keys through one handler so shortcuts never compete with seek controls.
        for widget in [self, *self.findChildren(QWidget)]:
            widget.installEventFilter(self)
            widget.setMouseTracking(True)
        if self.resources:
            self.show_resource()
        else:
            self.heading.setText("没有可欣赏的图片或视频")
            self.picture.setText("文件夹资源不会进入资源欣赏。")
            self.control_bar.setEnabled(False)

    def show_resource(self):
        self._release_right_hold(False)
        self._scrub_pause.stop()
        self._ended = False
        self.timer.stop()
        r = self.resources[self.position]
        self.heading.setText(f"{r['name']}    ·    {self.position + 1} / {len(self.resources)}")
        self._current_media_path = None
        if self.player:
            self.player.stop()
            self.player.setSource(QUrl())
        self.image = QImage()
        self.picture.clear()
        if self.video:
            self.video.clear()
        self.stack.setCurrentWidget(self.picture)
        self.seek.setRange(0, 0)
        self.seek.setEnabled(False)
        self.elapsed.setText("00:00")
        self.total.setText("00:00")
        self.play_button.setEnabled(r["type"] == "video" and self.player is not None)
        self._update_play_button()
        self.cover_button.setVisible(
            r["type"] == "video" and hasattr(self.parent(), "set_video_cover_from_preview")
        )
        if r["type"] == "video" and self.player:
            self.stack.setCurrentWidget(self.video)
            self.player.setPlaybackRate(1.0)
            self._current_media_path = r["path"]
            self._progress_timer.start()
            QTimer.singleShot(0, lambda path=r["path"]: self._load_video(path))
        elif r["type"] == "image":
            self.video_controls.hide()
            self._progress_timer.stop()
            self.image = self._read_image(r["path"])
            if self.image.isNull():
                self.picture.setText("此格式暂无法在应用内预览，请使用系统应用打开。")
            self.fit_image()
        else:
            self.video_controls.hide()
            self.picture.setText(
                "文件夹作为完整资源管理。\n点击“系统应用打开”浏览内部内容。"
                if r["type"] == "folder"
                else "当前播放器不可用，请使用系统应用打开。"
            )
        if self.slideshow and (r["type"] != "video" or not self.player):
            self.timer.start()
        self._layout_controls()
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    @staticmethod
    def _read_image(path):
        """Read an image with Qt first, then Pillow for extra formats.

        Qt's bundled image plugins cover common formats, while Pillow gives
        the preview a useful fallback for formats such as HEIC/RAW when a
        platform plugin is unavailable.  The returned image is detached from
        Pillow's memory so it remains valid after this method returns.
        """
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid():
            size.scale(QSize(2560, 1600), Qt.AspectRatioMode.KeepAspectRatio)
            reader.setScaledSize(size)
        image = reader.read()
        if not image.isNull():
            return image
        try:
            from PIL import Image, ImageOps

            with Image.open(path) as original:
                image = ImageOps.exif_transpose(original)
                image.thumbnail((2560, 1600))
                image = image.convert("RGBA")
                return QImage(
                    image.tobytes(), image.width, image.height, QImage.Format.Format_RGBA8888
                ).copy()
        except Exception:
            return QImage()

    def fit_image(self):
        if not self.image.isNull():
            self.picture.set_image(self.image)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "close_button"):
            self.close_button.move(self.width() - 44, 12)
            self._layout_controls()

    def showEvent(self, event):
        super().showEvent(event)
        screen = self.screen() or QApplication.primaryScreen()
        if screen and not self._centered and not self.isFullScreen():
            area = screen.availableGeometry()
            self.resize(min(self.width(), area.width()), min(self.height(), area.height()))
            self.move(area.center() - self.rect().center())
            self._centered = True
        self.activateWindow()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)

    def _video_clicked(self):
        self.toggle_play()
        self.setFocus(Qt.FocusReason.MouseFocusReason)

    def _load_video(self, path):
        if not self.player or self._current_media_path != path:
            return
        # Keep the loader tolerant of lightweight player doubles used by
        # integration tests and by installations where Qt Multimedia is not
        # available.  A real QMediaPlayer always exposes setSource; a test
        # double may only implement the transport methods.
        setter = getattr(self.player, "setSource", None)
        if callable(setter):
            setter(QUrl.fromLocalFile(path))
        position = getattr(self.player, "setPosition", None)
        if callable(position):
            position(0)
        play = getattr(self.player, "play", None)
        if callable(play):
            play()

    def step(self, amount=1):
        """Autoplay advances in list order and loops to the first item."""
        if not self.resources:
            return
        next_position = self.position + amount
        if next_position >= len(self.resources):
            next_position = 0
        self.position = max(0, next_position)
        self.show_resource()

    def _manual_step(self, amount):
        if not self.resources:
            return
        self.position = (self.position + amount) % len(self.resources)
        self.show_resource()

    def toggle_slideshow(self):
        if not self.resources:
            return
        self.slideshow = not self.slideshow
        self.slide_button.setText("取消自动播放" if self.slideshow else "自动播放")
        if self.slideshow and (self.resources[self.position]["type"] != "video" or not self.player):
            self.timer.start()
        else:
            self.timer.stop()

    def _update_play_button(self, *_):
        if not self.player or not hasattr(self, "play_button"):
            return
        try:
            playing = self.player.playbackState() == self.player.PlaybackState.PlayingState
        except (AttributeError, RuntimeError):
            playing = False
        self.play_button.setIcon(icon("pause" if playing else "play", "#d8e1ed"))

    def toggle_play(self):
        if self.player:
            if self.player.playbackState() == self.player.PlaybackState.PlayingState:
                self.player.pause()
            else:
                self.player.play()
            self._update_play_button()

    @staticmethod
    def _clock(ms):
        sec = max(0, int(ms // 1000))
        return (
            f"{sec // 3600:02d}:{sec % 3600 // 60:02d}:{sec % 60:02d}"
            if sec >= 3600
            else f"{sec // 60:02d}:{sec % 60:02d}"
        )

    def _position_changed(self, value):
        if not self._is_current_video_source():
            return
        if not self.seek.isSliderDown():
            self.seek.setValue(value)
        self.elapsed.setText(self._clock(value))

    def _duration_changed(self, value):
        if not self._is_current_video_source():
            return
        self.seek.setRange(0, max(0, value))
        self.seek.setEnabled(value > 0)
        self.total.setText(self._clock(value))

    def _is_video(self):
        return bool(self.player is not None and self.resources and self.resources[self.position]["type"] == "video")

    def _is_current_video_source(self):
        if not self._is_video() or self._current_media_path is None:
            return False
        # Backends can report an empty or stale URL while a new source loads.
        return True

    def _sync_progress(self):
        if not self._is_current_video_source():
            return
        try:
            duration = int(self.player.duration())
            position = int(self.player.position())
            self._duration_changed(duration)
            self._position_changed(position)
            state = self.player.playbackState()
            stopped = state == self.player.PlaybackState.StoppedState
            if duration > 0 and position >= duration - 250 and stopped and not self._ended:
                self._media_status(self.player.MediaStatus.EndOfMedia)
        except (AttributeError, RuntimeError):
            return

    def _seek_to(self, value):
        if self._is_video() and self.player.duration() > 0:
            self.player.setPosition(max(0, min(int(value), self.player.duration())))
            self.elapsed.setText(self._clock(value))
            # Some Windows media backends only repaint a newly sought frame
            # while the playback clock is active. Briefly resume and pause so
            # scrubbing gives immediate visual feedback even from pause.
            if not self._seek_was_playing:
                self.player.play()
                self._scrub_pause.start(70)

    def _seek_started(self):
        if self._is_video():
            self._seek_was_playing = (
                self.player.playbackState() == self.player.PlaybackState.PlayingState
            )

    def _seek_finished(self):
        self._seek_to(self.seek.value())
        if self._is_video() and not self._seek_was_playing:
            self._scrub_pause.start(80)

    def _pause_after_scrub(self):
        if self._is_video() and self.seek.isSliderDown() and not self._seek_was_playing:
            self.player.pause()
        elif self._is_video() and not self._seek_was_playing:
            self.player.pause()

    def _seek_relative(self, delta):
        if not self._is_video():
            return
        duration = self.player.duration()
        position = self.player.position()
        stopped_at_end = (
            duration > 0
            and position >= duration - 350
            and self.player.playbackState() == self.player.PlaybackState.StoppedState
        )
        if delta > 0 and (self._ended or stopped_at_end):
            self._manual_step(1)
            return
        if delta < 0 and self._ended and duration > 0:
            self._ended = False
            self.player.setPosition(max(0, duration - 3000))
            self.player.play()
            return
        if delta < 0 and position <= 350:
            self._manual_step(-1)
            return
        was_playing = self.player.playbackState() == self.player.PlaybackState.PlayingState
        target = max(0, min(position + delta, duration))
        self.player.setPosition(target)
        if was_playing or self.player.mediaStatus() == self.player.MediaStatus.EndOfMedia:
            self.player.play()

    def _begin_right_hold(self):
        if self._right_held:
            return
        self._right_held = True
        self._seek_hold.start(350)

    def _start_fast_forward(self):
        if self._right_held and self._is_video():
            self._previous_rate = self.player.playbackRate()
            self._was_playing = (
                self.player.playbackState() == self.player.PlaybackState.PlayingState
            )
            self._fast_forward = True
            self.player.setPlaybackRate(3.0)
            self.player.play()
            self.speed_label.setText("3×")

    def _release_right_hold(self, seek_on_tap=False):
        held, fast = self._right_held, self._fast_forward
        self._seek_hold.stop()
        self._right_held = False
        self._fast_forward = False
        if fast and self.player:
            self.player.setPlaybackRate(self._previous_rate)
            if not self._was_playing:
                self.player.pause()
        elif held and seek_on_tap and self._is_video():
            self._seek_relative(3000)
        self.speed_label.setText("")

    def eventFilter(self, watched, event):
        if (
            watched is self.heading
            and event.type() == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
            and self.windowHandle()
        ):
            self.windowHandle().startSystemMove()
            return True
        if watched is self and event.type() in (QEvent.Type.WindowDeactivate, QEvent.Type.Hide):
            self._release_right_hold(False)
        if event.type() == QEvent.Type.MouseMove and self.isFullScreen():
            position = event.position().toPoint() if hasattr(event, "position") else event.pos()
            mapped = watched.mapTo(self, position) if isinstance(watched, QWidget) else position
            self._update_fullscreen_pointer(mapped)
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Space:
            if not event.isAutoRepeat():
                self.toggle_play()
            event.accept()
            return True
        if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            if self.isFullScreen():
                self.toggle_fullscreen()
                event.accept()
                return True
        if event.type() in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease) and event.key() in (
            Qt.Key.Key_Right, Qt.Key.Key_Left, Qt.Key.Key_Up, Qt.Key.Key_Down,
        ):
            if event.isAutoRepeat():
                return True
            pressed = event.type() == QEvent.Type.KeyPress
            if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
                if pressed:
                    self._manual_step(-1 if event.key() == Qt.Key.Key_Up else 1)
                event.accept()
                return True
            if self._is_video():
                if event.key() == Qt.Key.Key_Right:
                    self._begin_right_hold() if pressed else self._release_right_hold(True)
                elif pressed:
                    self._seek_relative(-3000)
            elif pressed:
                self._manual_step(1 if event.key() == Qt.Key.Key_Right else -1)
            event.accept()
            return True
        if (
            self.video is not None and watched in (self.video, self.video.viewport())
            and event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease)
            and event.button() == Qt.MouseButton.RightButton
        ):
            if self._is_video():
                self._begin_right_hold() if event.type() == QEvent.Type.MouseButtonPress else self._release_right_hold(
                    False
                )
                event.accept()
                return True
        if (
            self.video is not None and watched in (self.video, self.video.viewport())
            and event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
        ):
            # MediaCanvas keeps the drag state until its release handler. A
            # plain click toggles playback; a zoomed drag only pans the frame.
            if not getattr(self.video, "_panned", False):
                self._video_clicked()
            return False
        return super().eventFilter(watched, event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right) and not event.isAutoRepeat():
            if self._is_video():
                if event.key() == Qt.Key.Key_Right:
                    self._begin_right_hold()
                else:
                    self._seek_relative(-3000)
            else:
                self._manual_step(1 if event.key() == Qt.Key.Key_Right else -1)
            event.accept()
            return
        if event.key() == Qt.Key.Key_Space:
            self.toggle_play(); event.accept(); return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Right and not event.isAutoRepeat():
            self._release_right_hold(True)
            event.accept()
            return
        super().keyReleaseEvent(event)

    def _media_status(self, status):
        if not self.player or not self._is_current_video_source():
            return
        if status == self.player.MediaStatus.LoadedMedia:
            self._ended = False
            self._duration_changed(self.player.duration())
            self._position_changed(self.player.position())
        elif status == self.player.MediaStatus.EndOfMedia:
            self._ended = True
            self._release_right_hold(False)
            if self.slideshow:
                self.step(1)
        self._update_play_button()

    def _video_error(self):
        self._release_right_hold(False)
        self.stack.setCurrentWidget(self.picture)
        self.picture.setText("当前视频编码无法播放，请使用系统应用打开。")

    def open_external(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.resources[self.position]["path"]))

    def set_video_cover(self):
        if not self._is_video():
            return
        owner = self.parent()
        if hasattr(owner, "set_video_cover_from_preview"):
            owner.set_video_cover_from_preview(
                self.resources[self.position],
                (self.player.position() / 1000.0) if self.player else 0.0,
            )

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self._pointer_timer.stop()
            self.showNormal()
            self.layout().setContentsMargins(22, 18, 22, 18)
            self.layout().addWidget(self.controls_panel)
            self.controls_panel.setMinimumHeight(0)
            self.controls_panel.setMaximumHeight(16777215)
            self.heading.show()
            self.close_button.show()
            self.control_bar.show()
            self.controls_panel.show()
        else:
            self.layout().removeWidget(self.controls_panel)
            self.layout().setContentsMargins(0, 0, 0, 0)
            self.heading.hide()
            self.close_button.hide()
            self.video_controls.hide()
            self.control_bar.hide()
            self.controls_panel.hide()
            self.showFullScreen()
            self._pointer_timer.start()
        self._layout_controls()

    def _layout_controls(self):
        if not hasattr(self, "control_bar"):
            return
        visible = not self.isFullScreen() or not self.controls_panel.isHidden()
        self.video_controls.setVisible(visible and self._is_video())
        if self.isFullScreen():
            height = 92 if self._is_video() else 60
            self.controls_panel.setGeometry(0, max(0, self.height() - height), self.width(), height)
            self.controls_panel.raise_()
        self.controls_panel.layout().activate()

    def _poll_fullscreen_pointer(self):
        self._update_fullscreen_pointer(self.mapFromGlobal(QCursor.pos()))

    def _update_fullscreen_pointer(self, point):
        if not self.isFullScreen():
            return
        if not self.rect().contains(point):
            self._hide_fullscreen_controls()
        elif self.control_bar.isHidden():
            # Only the last two logical pixels can reveal the controls.
            if point.y() >= self.height() - 2:
                self._show_fullscreen_controls()
        else:
            if not self.controls_panel.geometry().contains(point):
                self._hide_fullscreen_controls()

    def _show_fullscreen_controls(self):
        if not self.isFullScreen():
            return
        self.controls_panel.show()
        self.control_bar.show()
        self._layout_controls()

    def _hide_fullscreen_controls(self):
        if self.isFullScreen():
            self.video_controls.hide()
            self.control_bar.hide()
            self.controls_panel.hide()

    def done(self, result):
        self._release_right_hold(False)
        self._current_media_path = None
        self._pointer_timer.stop()
        self._progress_timer.stop()
        self._scrub_pause.stop()
        self.timer.stop()
        if self.player:
            self.player.stop()
            self.player.setSource(QUrl())
        super().done(result)
