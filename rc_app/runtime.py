"""Resolve a source checkout and optional local dependency directory."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def ensure_runtime():
    runtime = PROJECT_ROOT / ".runtime"
    if runtime.is_dir() and str(runtime) not in sys.path:
        sys.path.insert(0, str(runtime))
