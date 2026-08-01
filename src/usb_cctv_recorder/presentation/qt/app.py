"""Qt application lifecycle."""

import sys

from PySide6.QtWidgets import QApplication

from .main_window import MainWindow


def run_application() -> int:
    """Open the placeholder application window."""
    application = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return application.exec()
