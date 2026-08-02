"""Main window hosting the Phase 3 setup page."""

import time
import uuid
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMainWindow, QPushButton, QTabWidget

from usb_cctv_recorder.application.archive import ArchiveService
from usb_cctv_recorder.application.dto import DeviceDiscovery
from usb_cctv_recorder.application.library import LibraryService
from usb_cctv_recorder.application.ports import SystemServicePort, WorkerConfigurationPort
from usb_cctv_recorder.application.preflight import PreflightService
from usb_cctv_recorder.application.storage import StorageGovernorService
from usb_cctv_recorder.infrastructure.ipc.client import UnixSocketClient
from usb_cctv_recorder.infrastructure.ipc.protocol import Command, Request, Response

from .pages.archive_page import ArchivePage
from .pages.library_page import LibraryPage
from .pages.setup_page import SetupPage


class DeviceProbeThread(QThread):
    """Keep command-based device probing off the Qt event loop."""

    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, service: PreflightService) -> None:
        super().__init__()
        self._service = service

    def run(self) -> None:
        try:
            discovery = self._service.discover()
            if not self.isInterruptionRequested():
                self.completed.emit(discovery)
        except Exception as error:  # Boundary: user-facing UI cannot expose a traceback.
            if not self.isInterruptionRequested():
                self.failed.emit(str(error))


class WorkerStatusThread(QThread):
    """Reconnect status lookup without blocking Qt while the worker owns recording."""

    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, client_factory: Callable[[], UnixSocketClient]) -> None:
        super().__init__()
        self._client_factory = client_factory

    def run(self) -> None:
        try:
            response = self._client_factory().request(Request(Command.STATUS, str(uuid.uuid4())))
            if not self.isInterruptionRequested():
                self.completed.emit(response)
        except Exception as error:  # Boundary: a missing worker is a normal UI state.
            if not self.isInterruptionRequested():
                self.failed.emit(str(error))


class WorkerCommandThread(QThread):
    """Send one predefined worker command outside the Qt event loop."""

    completed = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        client_factory: Callable[[], UnixSocketClient],
        command: Command,
        service: SystemServicePort | None = None,
    ) -> None:
        super().__init__()
        self._client_factory = client_factory
        self._command = command
        self._service = service

    def run(self) -> None:
        try:
            if self._command is Command.START and self._service is not None:
                self._service.start_worker()
            response = self._request_response()
            if self._command is Command.STOP and response.accepted and self._service is not None:
                self._service.stop_worker()
            if not self.isInterruptionRequested():
                self.completed.emit(response)
        except Exception as error:  # Boundary: a missing worker is a normal UI state.
            if not self.isInterruptionRequested():
                self.failed.emit(str(error))

    def _request_response(self) -> Response:
        deadline = time.monotonic() + 2
        while True:
            try:
                return self._client_factory().request(Request(self._command, str(uuid.uuid4())))
            except OSError:
                if self._command is not Command.START or time.monotonic() >= deadline:
                    raise
                time.sleep(0.1)


class MainWindow(QMainWindow):
    """Setup UI; persistent recording remains deliberately out of scope."""

    def __init__(
        self,
        preflight_service: PreflightService | None = None,
        worker_client_factory: Callable[[], UnixSocketClient] | None = None,
        worker_configuration: WorkerConfigurationPort | None = None,
        library_service: LibraryService | None = None,
        library_media_root: Path | None = None,
        archive_service: ArchiveService | None = None,
        storage_service: StorageGovernorService | None = None,
        worker_service: SystemServicePort | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("USB CCTV Recorder")
        self.setup_page = SetupPage(
            preflight_service,
            worker_configuration=worker_configuration,
            storage_service=storage_service,
        )
        self.library_page: LibraryPage | None = None
        self.archive_page: ArchivePage | None = None
        if library_service is None or library_media_root is None or archive_service is None:
            self.setCentralWidget(self.setup_page)
        else:
            tabs = QTabWidget()
            tabs.addTab(self.setup_page, "Setup")
            self.archive_page = ArchivePage(archive_service, library_media_root, storage_service)
            self.library_page = LibraryPage(
                library_service,
                library_media_root,
                self.archive_page.set_library_selection,
                archive_service,
            )
            tabs.addTab(self.library_page, "Library")
            tabs.addTab(self.archive_page, "Archive")
            self.setCentralWidget(tabs)
        self._probe_thread: DeviceProbeThread | None = None
        self._worker_status_thread: WorkerStatusThread | None = None
        self._worker_command_thread: WorkerCommandThread | None = None
        self._worker_client_factory = worker_client_factory
        self._worker_service = worker_service
        self._close_requested = False
        self._retry_button = QPushButton("Retry now", self)
        self._retry_button.setEnabled(False)
        self._retry_button.clicked.connect(self._retry_now)
        self.statusBar().addPermanentWidget(self._retry_button)
        self.setup_page.start_button.clicked.connect(self._toggle_recording)
        if preflight_service is not None:
            self._probe_thread = DeviceProbeThread(preflight_service)
            self._probe_thread.completed.connect(self._discovery_completed)
            self._probe_thread.failed.connect(self.setup_page.preflight_status.setText)
            self._probe_thread.finished.connect(self._probe_finished)
            self._probe_thread.start()
        if worker_client_factory is not None:
            self._worker_status_thread = WorkerStatusThread(worker_client_factory)
            self._worker_status_thread.completed.connect(self._initial_worker_status_completed)
            self._worker_status_thread.failed.connect(self._initial_worker_status_failed)
            self._worker_status_thread.start()

    def _discovery_completed(self, discovery: object) -> None:
        if isinstance(discovery, DeviceDiscovery):
            self.setup_page.set_discovery(discovery)

    def _probe_finished(self) -> None:
        if self._close_requested:
            self.close()

    def _worker_status_completed(self, response: object) -> None:
        if isinstance(response, Response):
            self.setup_page.set_recording_active(
                response.state
                in {"starting", "recording_av", "recording_audio_only", "recording_video_only"}
            )
            session = f" session {response.session_id}" if response.session_id else ""
            battery = (
                f", battery {response.battery_percent}%"
                if response.battery_percent is not None
                else ""
            )
            self.statusBar().showMessage(
                f"Worker status: {response.state}{session}; power protection: "
                f"{response.power_protection}; power: {response.power_source}{battery}; "
                f"video: {response.video_health}; audio: {response.audio_health}; "
                f"output: {response.output_health}; recovery: {response.recovery_attempt}; "
                "last gap: "
                f"{response.last_gap_seconds if response.last_gap_seconds is not None else '-'}"
            )
            self._retry_button.setEnabled(response.state == "recovering")

    def _initial_worker_status_completed(self, response: object) -> None:
        if self._worker_command_thread is None:
            self._worker_status_completed(response)

    def _worker_status_failed(self, _message: str) -> None:
        self.setup_page.set_recording_active(False)
        self.statusBar().showMessage("Worker status: unavailable")
        self._retry_button.setEnabled(False)

    def _initial_worker_status_failed(self, message: str) -> None:
        if self._worker_command_thread is None:
            self._worker_status_failed(message)

    def _retry_now(self) -> None:
        if self._worker_client_factory is None or (
            self._worker_command_thread is not None and self._worker_command_thread.isRunning()
        ):
            return
        self._retry_button.setEnabled(False)
        self._worker_command_thread = WorkerCommandThread(
            self._worker_client_factory, Command.RETRY
        )
        self._worker_command_thread.completed.connect(self._worker_status_completed)
        self._worker_command_thread.failed.connect(self._worker_status_failed)
        self._worker_command_thread.start()

    def _toggle_recording(self) -> None:
        if self._worker_client_factory is None or (
            self._worker_command_thread is not None and self._worker_command_thread.isRunning()
        ):
            return
        command = (
            Command.STOP if self.setup_page.start_button.text() == "Stop safely" else Command.START
        )
        self.setup_page.start_button.setEnabled(False)
        self._worker_command_thread = WorkerCommandThread(
            self._worker_client_factory, command, self._worker_service
        )
        self._worker_command_thread.completed.connect(self._worker_status_completed)
        self._worker_command_thread.failed.connect(self._worker_command_failed)
        self._worker_command_thread.start()

    def _worker_command_failed(self, message: str) -> None:
        self.setup_page.set_recording_active(False)
        self.statusBar().showMessage(f"Worker command failed: {message}")

    def closeEvent(self, event: QCloseEvent) -> None:
        # Closing the window deliberately never sends a recording stop request.
        self.setup_page._preview.stop()
        if self._probe_thread is not None and self._probe_thread.isRunning():
            self._close_requested = True
            self._probe_thread.requestInterruption()
            self.setup_page.preflight_status.setText(
                "Finishing the active device probe before closing…"
            )
            event.ignore()
            return
        for thread in (self._worker_status_thread, self._worker_command_thread):
            if thread is not None and thread.isRunning():
                thread.requestInterruption()
                thread.wait(2_000)
        super().closeEvent(event)
