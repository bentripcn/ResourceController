"""Make PySide6's nested Qt DLL directory visible in a frozen Windows app."""

from __future__ import annotations

import os
import sys


if sys.platform == "win32":
    bundle_root = getattr(sys, "_MEIPASS", "")
    # In a PyInstaller 6 one-folder build, sys._MEIPASS already points to the
    # ``_internal`` directory. Shiboken.pyd lives in a package subdirectory,
    # while shiboken6.abi3.dll and pyside6.abi3.dll live at its root. Register
    # every relevant directory before qt_app imports PySide6.
    roots = (bundle_root, os.path.join(bundle_root, "_internal"))
    package_root = next(
        (root for root in roots if os.path.isdir(os.path.join(root, "PySide6"))),
        bundle_root,
    )
    candidates = (
        package_root,
        os.path.join(package_root, "PySide6"),
        os.path.join(package_root, "shiboken6"),
    )
    dll_directories = []
    for path in candidates:
        if path and os.path.isdir(path):
            # Keep all handles alive for the lifetime of the process; dropping
            # a handle unregisters that DLL search directory immediately.
            dll_directories.append(os.add_dll_directory(path))
    if dll_directories:
        os.environ["PATH"] = os.pathsep.join(candidates) + os.pathsep + os.environ.get("PATH", "")
