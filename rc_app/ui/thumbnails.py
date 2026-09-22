"""rc_app.ui.thumbnails: extracted workbench component."""

from __future__ import annotations

import os
import subprocess
from collections import OrderedDict
from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, QThreadPool, Signal, Slot
from PySide6.QtGui import QImage, QImageReader

from library import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS
from media_tools import make_video_poster, resolve_ffmpeg
from rc_app.ui.jobs import Job


class ThumbnailStore(QObject):
    changed = Signal(str)

    def __init__(self, parent=None, cache_dir=None):
        super().__init__(parent)
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(3)
        self.cache = OrderedDict()
        self.pending = set()
        self.jobs = set()

    def image(self, path: str | None, stamp: str = "") -> QImage | None:
        if not path:
            return None
        key = (path, stamp)
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        if key not in self.pending:
            self.pending.add(key)

            def decode():
                source = path
                if Path(path).is_dir():
                    with os.scandir(path) as entries:
                        source = next(
                            (
                                entry.path
                                for entry in entries
                                if not entry.is_symlink()
                                and entry.is_file(follow_symlinks=False)
                                and Path(entry.name).suffix.lower() in IMAGE_EXTENSIONS
                            ),
                            None,
                        )
                    if not source:
                        return key, QImage()
                # Generate a display-only video poster when ffmpeg is available.
                if source and Path(source).suffix.lower() in VIDEO_EXTENSIONS:
                    if self.cache_dir:
                        try:
                            poster = make_video_poster(source, self.cache_dir)
                        except Exception:
                            poster = make_video_poster(source, self.cache_dir, seek=0)
                        return key, QImage(poster)
                    ffmpeg = resolve_ffmpeg()
                    if ffmpeg:
                        try:
                            proc = subprocess.run(
                                [
                                    ffmpeg,
                                    "-hide_banner",
                                    "-loglevel",
                                    "error",
                                    "-ss",
                                    "00:00:01",
                                    "-i",
                                    path,
                                    "-frames:v",
                                    "1",
                                    "-vf",
                                    "scale=700:520:force_original_aspect_ratio=decrease",
                                    "-f",
                                    "image2pipe",
                                    "-vcodec",
                                    "png",
                                    "pipe:1",
                                ],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                timeout=12,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                            )
                            poster = QImage.fromData(proc.stdout, "PNG")
                            if not poster.isNull():
                                return key, poster
                        except Exception:
                            pass
                reader = QImageReader(source)
                reader.setAutoTransform(True)
                size = reader.size()
                if size.isValid():
                    size.scale(QSize(700, 520), Qt.AspectRatioMode.KeepAspectRatio)
                    reader.setScaledSize(size)
                image = reader.read()
                if image.isNull():
                    try:
                        from PIL import Image, ImageOps

                        with Image.open(source) as original:
                            im = ImageOps.exif_transpose(original)
                            im.thumbnail((700, 520))
                            im = im.convert("RGBA")
                            image = QImage(
                                im.tobytes(), im.width, im.height, QImage.Format.Format_RGBA8888
                            ).copy()
                    except Exception:
                        pass
                return key, image

            job = Job(decode)
            self.jobs.add(job)
            job.signals.done.connect(self._decoded)
            job.signals.done.connect(lambda _, j=job: self.jobs.discard(j))
            job.signals.failed.connect(lambda _, k=key, j=job: self._failed(k, j))
            self.pool.start(job)
        return None

    @Slot(object)
    def _decoded(self, result):
        key, image = result
        self.pending.discard(key)
        self.cache[key] = image
        while len(self.cache) > 300:
            self.cache.popitem(last=False)
        self.changed.emit(key[0])

    def _failed(self, key, job):
        self.pending.discard(key)
        self.jobs.discard(job)
        self.cache[key] = QImage()
