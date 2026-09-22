"""rc_app.ui.jobs: extracted workbench component."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QRunnable, Signal


class JobSignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class Job(QRunnable):
    def __init__(self, function: Callable):
        super().__init__()
        self.function = function
        self.signals = JobSignals()

    def run(self):
        try:
            result = self.function()
        except Exception as exc:
            self.signals.failed.emit(str(exc))
        else:
            self.signals.done.emit(result)
