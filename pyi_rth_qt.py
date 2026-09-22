"""Make PySide6's nested Qt DLL directory visible in a frozen Windows app."""

from __future__ import annotations

import ctypes
import os
import sys


if sys.platform == "win32":
    bundle_root = getattr(sys, "_MEIPASS", "")
    # PyInstaller 6.0+ one-folder builds place collected packages under
    # ``_internal`` while older builds used the bundle root. Support both so
    # the hook remains compatible with existing release artifacts.
    candidates = (
        os.path.join(bundle_root, "_internal", "PySide6"),
        os.path.join(bundle_root, "PySide6"),
    )
    pyside_dir = next((path for path in candidates if os.path.isdir(path)), "")
    if pyside_dir:
        # Keep the handle alive for the lifetime of the process; dropping it
        # immediately unregisters the directory on Windows.
        _qt_dll_directory = os.add_dll_directory(pyside_dir)
        os.environ["PATH"] = pyside_dir + os.pathsep + os.environ.get("PATH", "")
        ctypes.windll.kernel32.SetDllDirectoryW(pyside_dir)
