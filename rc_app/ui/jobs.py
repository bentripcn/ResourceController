"""rc_app.ui.jobs: extracted workbench component."""

from __future__ import annotations

import threading
from typing import Callable

from PySide6.QtCore import QObject, QRunnable, Signal


class JobSignals(QObject):
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(object)


class Job(QRunnable):
    def __init__(self, function: Callable, *, cancel_event=None, with_context=False):
        super().__init__()
        self.function = function
        self.signals = JobSignals()
        self.cancel_event = cancel_event or threading.Event()
        self.with_context = with_context

    def report(self, value):
        self.signals.progress.emit(value)

    def run(self):
        try:
            result = (
                self.function(self.report, self.cancel_event)
                if self.with_context
                else self.function()
            )
        except Exception as exc:
            self.signals.failed.emit(str(exc))
        else:
            self.signals.done.emit(result)
