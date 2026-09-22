"""rc_app.bootstrap: extracted workbench component."""

from __future__ import annotations

import argparse
import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from rc_app.ui.theme import STYLE, apply_palette
from rc_app.ui.window import MainWindow


def main(argv=None):
    parser = argparse.ArgumentParser(description="ResourceController Qt desktop")
    parser.add_argument("--data-dir", help="Use a separate application database/data directory")
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("ResourceController")
    app.setOrganizationName("ResourceController")
    app.setStyle("Fusion")
    apply_palette(app)
    app.setStyleSheet(STYLE)
    font = QFont("Microsoft YaHei UI", 9)
    app.setFont(font)
    window = MainWindow(data_dir=args.data_dir)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
