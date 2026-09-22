"""FFmpeg discovery and safe video poster generation.

FFmpeg is optional at runtime. Discovery checks an application-bundled
executable, project ``.runtime`` (used by the Windows build), then the
``imageio-ffmpeg`` package and finally PATH. No shell is used for commands.
"""

from __future__ import annotations

import hashlib
import importlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterable


class MediaToolError(RuntimeError):
    """An FFmpeg operation could not be completed."""


def _roots() -> Iterable[Path]:
    here = Path(__file__).resolve().parent
    yield here
    yield here / ".runtime"
    if getattr(sys, "_MEIPASS", None):
        yield Path(sys._MEIPASS)
    yield Path(sys.executable).resolve().parent


def _runtime_imageio_exe() -> str | None:
    # PyInstaller may expose the package as a bundled module, while a source
    # checkout has it in .runtime. Importing through an explicit path keeps the
    # normal application environment untouched.
    runtime = Path(__file__).resolve().parent / ".runtime"
    if runtime.is_dir() and str(runtime) not in sys.path:
        sys.path.insert(0, str(runtime))
    try:
        module = importlib.import_module("imageio_ffmpeg")
        candidate = module.get_ffmpeg_exe()
    except Exception:
        return None
    return str(candidate) if candidate and Path(candidate).is_file() else None


def resolve_ffmpeg(prefer: str | os.PathLike[str] | None = None) -> str | None:
    """Return an executable path, or ``None`` when FFmpeg is unavailable.

    ``prefer`` is accepted only when it points to an existing executable; it
    never invokes a shell or searches arbitrary command strings.
    """
    candidates: list[Path] = []
    if prefer:
        candidates.append(Path(prefer).expanduser())
    for root in _roots():
        candidates.extend(
            (
                root / "ffmpeg.exe",
                root / "ffmpeg",
                root / "bin" / "ffmpeg.exe",
                root / "bin" / "ffmpeg",
            )
        )
        # imageio-ffmpeg's wheel stores a versioned binary in this directory.
        binary_dir = root / "imageio_ffmpeg" / "binaries"
        if binary_dir.is_dir():
            candidates.extend(sorted(binary_dir.glob("ffmpeg*"), reverse=True))
    package_exe = _runtime_imageio_exe()
    if package_exe:
        candidates.append(Path(package_exe))
    path_exe = shutil.which("ffmpeg")
    if path_exe:
        candidates.append(Path(path_exe))
    seen = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            key = os.path.normcase(str(resolved))
            if key not in seen and resolved.is_file() and os.access(resolved, os.X_OK):
                seen.add(key)
                return str(resolved)
        except OSError:
            continue
    return None


def ffmpeg_version(ffmpeg: str | None = None) -> str:
    """Return the first FFmpeg version line; raises a clear error if absent."""
    executable = resolve_ffmpeg(ffmpeg)
    if not executable:
        raise MediaToolError(
            "未找到 FFmpeg。请运行 install_runtime.ps1 或将 ffmpeg.exe 放入 PATH。"
        )
    try:
        process = subprocess.run(
            [executable, "-hide_banner", "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MediaToolError(f"启动 FFmpeg 失败：{exc}") from exc
    if process.returncode != 0:
        raise MediaToolError(process.stdout.strip() or "FFmpeg 版本检查失败。")
    return (process.stdout or "").splitlines()[0] if process.stdout else "ffmpeg (unknown version)"


def extract_frame(
    video: str | os.PathLike[str],
    output: str | os.PathLike[str],
    *,
    seek: float = 1.0,
    size: tuple[int, int] | None = None,
    ffmpeg: str | None = None,
    timeout: float = 30,
) -> str:
    """Extract one PNG frame atomically and return its absolute path."""
    source = Path(video).expanduser().resolve()
    destination = Path(output).expanduser().resolve()
    if not source.is_file():
        raise MediaToolError(f"视频文件不存在：{source}")
    if seek < 0:
        raise MediaToolError("抽帧时间不能为负数。")
    executable = resolve_ffmpeg(ffmpeg)
    if not executable:
        raise MediaToolError("未找到 FFmpeg。请先安装项目运行时依赖。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".frame-", suffix=".png", dir=destination.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    command = [
        executable,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{seek:g}",
        "-i",
        str(source),
        "-frames:v",
        "1",
    ]
    if size:
        width, height = int(size[0]), int(size[1])
        if width < 1 or height < 1:
            raise MediaToolError("缩略图尺寸必须为正数。")
        command.extend(["-vf", f"scale={width}:{height}:force_original_aspect_ratio=decrease"])
    command.extend(["-f", "image2", str(temporary)])
    try:
        process = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if process.returncode != 0 or not temporary.is_file() or temporary.stat().st_size == 0:
            message = (process.stderr or process.stdout or "抽帧失败").strip().splitlines()[-1]
            raise MediaToolError(f"FFmpeg 抽帧失败：{message}")
        os.replace(temporary, destination)
    except subprocess.TimeoutExpired as exc:
        raise MediaToolError(f"FFmpeg 抽帧超时（>{timeout:g} 秒）。") from exc
    except OSError as exc:
        raise MediaToolError(f"写入缩略图失败：{exc}") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return str(destination)


def video_metadata(
    video: str | os.PathLike[str], *, ffmpeg: str | None = None, timeout: float = 15
) -> dict:
    """Read lightweight duration/size metadata using FFmpeg's input probe."""
    source = Path(video).expanduser().resolve()
    executable = resolve_ffmpeg(ffmpeg)
    if not source.is_file() or not executable:
        raise MediaToolError("视频或 FFmpeg 不可用。")
    try:
        process = subprocess.run(
            [executable, "-hide_banner", "-i", str(source)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MediaToolError(f"读取视频信息失败：{exc}") from exc
    report = process.stderr or process.stdout
    duration = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", report)
    dimensions = re.search(r"(\d{2,5})x(\d{2,5})", report)
    result = {"path": str(source), "duration": None, "width": None, "height": None}
    if duration:
        result["duration"] = (
            int(duration.group(1)) * 3600 + int(duration.group(2)) * 60 + float(duration.group(3))
        )
    if dimensions:
        result["width"], result["height"] = int(dimensions.group(1)), int(dimensions.group(2))
    return result


def make_video_poster(
    video: str | os.PathLike[str],
    cache_dir: str | os.PathLike[str],
    *,
    seek: float = 1.0,
    size: tuple[int, int] = (700, 520),
    ffmpeg: str | None = None,
) -> str:
    """Generate/reuse a deterministic cache poster keyed by file stat and options."""
    source = Path(video).expanduser().resolve()
    stat = source.stat()
    key = hashlib.sha256(
        f"{source}|{stat.st_size}|{stat.st_mtime_ns}|{seek}|{size}".encode()
    ).hexdigest()
    cache = Path(cache_dir).expanduser().resolve()
    destination = cache / f"{key}.png"
    if destination.is_file() and destination.stat().st_size:
        return str(destination)
    return extract_frame(source, destination, seek=seek, size=size, ffmpeg=ffmpeg)


__all__ = [
    "MediaToolError",
    "resolve_ffmpeg",
    "ffmpeg_version",
    "extract_frame",
    "video_metadata",
    "make_video_poster",
]
