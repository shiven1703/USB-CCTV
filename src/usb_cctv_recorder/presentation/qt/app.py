"""Qt application lifecycle."""

import sys
from collections.abc import Callable

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def run_application(window_factory: Callable[[], MainWindow] | None = None) -> int:
    """Open the application window."""
    application = QApplication.instance() or QApplication(sys.argv)
    window = (window_factory or MainWindow)()
    window.show()
    return application.exec()
