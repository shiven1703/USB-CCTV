"""Manual Phase 9 archive queue; the widget only calls application services."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from usb_cctv_recorder.application.archive import ArchiveService
from usb_cctv_recorder.application.dto import (
    ArchiveJobView,
    ArchiveProfile,
    ArchiveProfileKind,
    ArchiveRequest,
)


class _ArchiveThread(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, action: Callable[[], object]) -> None:
        super().__init__()
        self._action = action

    def run(self) -> None:
        try:
            result = self._action()
            if not self.isInterruptionRequested():
                self.completed.emit(result)
        except Exception as error:  # Boundary: archive diagnostics must remain user-safe.
            if not self.isInterruptionRequested():
                self.failed.emit(str(error))


class ArchivePage(QWidget):
    """Selection, queue controls, progress, and durable failure visibility."""

    def __init__(self, service: ArchiveService, media_root: Path) -> None:
        super().__init__()
        self._service = service
        self._thread: _ArchiveThread | None = None
        self._selected_ids: tuple[str, ...] = ()
        self.destination = QLineEdit(str(media_root))
        self.session_id = QLineEdit()
        self.session_id.setPlaceholderText("Session ID")
        self.free_space_gb = QDoubleSpinBox()
        self.free_space_gb.setRange(0.1, 90.0)
        self.free_space_gb.setValue(1.0)
        self.free_space_gb.setSuffix(" GB")
        self.profile = QComboBox()
        self.profile.addItem(
            "Compressed archive (H.264; audio copied)", ArchiveProfileKind.COMPRESSED
        )
        self.profile.addItem("Move without compression (original quality)", ArchiveProfileKind.MOVE)
        self.delete_sources = QCheckBox("Delete original only after fully verified commit")
        self.selection = QLabel("No originals selected in the Library")
        self.queue_button = QPushButton("Archive selected")
        self.session_button = QPushButton("Select session originals")
        self.free_space_button = QPushButton("Select oldest until free space")
        self.run_button = QPushButton("Run next job")
        self.pause_button = QPushButton("Pause")
        self.resume_button = QPushButton("Resume")
        self.cancel_button = QPushButton("Cancel")
        self.retry_button = QPushButton("Retry failed")
        self.status = QLabel("Queue idle")
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ("Source", "Profile", "State", "Progress", "Destination", "Failure")
        )
        controls = QFormLayout()
        controls.addRow("Archive drive/root", self.destination)
        controls.addRow("Archive profile", self.profile)
        controls.addRow("Library selection", self.selection)
        controls.addRow("Session", self.session_id)
        controls.addRow(self.session_button)
        controls.addRow("Requested free space", self.free_space_gb)
        controls.addRow(self.free_space_button)
        controls.addRow(self.delete_sources)
        controls.addRow(self.queue_button)
        buttons = QHBoxLayout()
        for button in (
            self.run_button,
            self.pause_button,
            self.resume_button,
            self.cancel_button,
            self.retry_button,
        ):
            buttons.addWidget(button)
        layout = QVBoxLayout(self)
        layout.addLayout(controls)
        layout.addWidget(self.table)
        layout.addLayout(buttons)
        layout.addWidget(self.status)
        self.queue_button.clicked.connect(self._enqueue)
        self.session_button.clicked.connect(self._select_session)
        self.free_space_button.clicked.connect(self._select_oldest_for_space)
        self.run_button.clicked.connect(lambda: self._start(self._service.run_next))
        self.pause_button.clicked.connect(lambda: self._selected_action(self._service.pause))
        self.resume_button.clicked.connect(lambda: self._selected_action(self._service.resume))
        self.cancel_button.clicked.connect(lambda: self._selected_action(self._service.cancel))
        self.retry_button.clicked.connect(lambda: self._selected_action(self._service.retry))
        self.refresh()

    def set_library_selection(self, item_ids: tuple[str, ...]) -> None:
        self._selected_ids = item_ids
        plural = "s" if len(item_ids) != 1 else ""
        self.selection.setText(f"{len(item_ids)} original{plural} selected in the Library")

    def refresh(self) -> None:
        self._populate(self._service.jobs())

    def _enqueue(self) -> None:  # pragma: no cover - Qt dispatch
        if not self._selected_ids:
            self._failed("Select eligible originals in the Library first")
            return
        try:
            kind = ArchiveProfileKind(str(self.profile.currentData()))
        except ValueError:
            self._failed("Select a valid archive profile")
            return
        request = ArchiveRequest(
            self._selected_ids,
            ArchiveProfile(kind),
            self.destination.text(),
            self.delete_sources.isChecked(),
        )
        self._start(lambda: self._service.enqueue(request))

    def _select_session(self) -> None:  # pragma: no cover - Qt dispatch
        session_id = self.session_id.text().strip()
        if not session_id:
            self._failed("Enter a session ID to select its eligible originals")
            return
        self._start(lambda: self._service.select_session(session_id))

    def _select_oldest_for_space(self) -> None:  # pragma: no cover - Qt dispatch
        requested_bytes = int(self.free_space_gb.value() * 1_000_000_000)
        self._start(lambda: self._service.select_oldest_for_space(requested_bytes))

    def _selected_action(self, action: Callable[[str], ArchiveJobView]) -> None:  # pragma: no cover
        row = self.table.currentRow()
        if row < 0:
            self._failed("Select an archive job first")
            return
        item = self.table.item(row, 0)
        if item is None:
            return
        self._start(lambda: action(item.data(32)))

    def _start(self, action: Callable[[], object]) -> None:  # pragma: no cover - thread dispatch
        if self._thread is not None and self._thread.isRunning():
            return
        self.status.setText("Archive operation running…")
        self._thread = _ArchiveThread(action)
        self._thread.completed.connect(self._completed)
        self._thread.failed.connect(self._failed)
        self._thread.start()

    def _completed(self, result: object) -> None:
        if isinstance(result, tuple) and all(isinstance(item, str) for item in result):
            self.set_library_selection(result)
            self.status.setText(f"Selected {len(result)} eligible original(s) for manual archive")
            return
        self.refresh()
        self.status.setText("Archive operation completed; inspect state and failure details below")

    def _populate(self, jobs: tuple[ArchiveJobView, ...]) -> None:
        self.table.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            source = QTableWidgetItem(Path(job.source_path).name or job.source_item_id)
            source.setData(32, job.job_id)
            values = (
                source,
                QTableWidgetItem(job.profile.value),
                QTableWidgetItem(job.state.value),
                QTableWidgetItem(f"{job.progress_percent}%"),
                QTableWidgetItem(job.destination_path),
                QTableWidgetItem(job.failure_detail or job.failure_code or "—"),
            )
            for column, item in enumerate(values):
                self.table.setItem(row, column, item)
        self.pause_button.setEnabled(bool(jobs))
        self.resume_button.setEnabled(bool(jobs))
        self.cancel_button.setEnabled(bool(jobs))
        self.retry_button.setEnabled(bool(jobs))

    def _failed(self, message: str) -> None:
        self.status.setText(f"Archive diagnostic: {message}")
