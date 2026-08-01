"""Minimal application window for the Phase 1 shell."""

from PySide6.QtWidgets import QLabel, QMainWindow


class MainWindow(QMainWindow):
    """Window shell; recording behaviour belongs to later application services."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("USB CCTV Recorder")
        self.setCentralWidget(QLabel("USB CCTV Recorder"))
