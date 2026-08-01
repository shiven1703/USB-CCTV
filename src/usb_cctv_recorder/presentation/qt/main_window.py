"""Main window hosting the Phase 3 setup page."""

import uuid
from collections.abc import Callable

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMainWindow

from usb_cctv_recorder.application.dto import DeviceDiscovery
from usb_cctv_recorder.application.ports import WorkerConfigurationPort
from usb_cctv_recorder.application.preflight import PreflightService
from usb_cctv_recorder.infrastructure.ipc.client import UnixSocketClient
from usb_cctv_recorder.infrastructure.ipc.protocol import Command, Request, Response

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


class MainWindow(QMainWindow):
    """Setup UI; persistent recording remains deliberately out of scope."""

    def __init__(
        self,
        preflight_service: PreflightService | None = None,
        worker_client_factory: Callable[[], UnixSocketClient] | None = None,
        worker_configuration: WorkerConfigurationPort | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("USB CCTV Recorder")
        self.setup_page = SetupPage(preflight_service, worker_configuration=worker_configuration)
        self.setCentralWidget(self.setup_page)
        self._probe_thread: DeviceProbeThread | None = None
        self._worker_status_thread: WorkerStatusThread | None = None
        self._close_requested = False
        if preflight_service is not None:
            self._probe_thread = DeviceProbeThread(preflight_service)
            self._probe_thread.completed.connect(self._discovery_completed)
            self._probe_thread.failed.connect(self.setup_page.preflight_status.setText)
            self._probe_thread.finished.connect(self._probe_finished)
            self._probe_thread.start()
        if worker_client_factory is not None:
            self._worker_status_thread = WorkerStatusThread(worker_client_factory)
            self._worker_status_thread.completed.connect(self._worker_status_completed)
            self._worker_status_thread.failed.connect(self._worker_status_failed)
            self._worker_status_thread.start()

    def _discovery_completed(self, discovery: object) -> None:
        if isinstance(discovery, DeviceDiscovery):
            self.setup_page.set_discovery(discovery)

    def _probe_finished(self) -> None:
        if self._close_requested:
            self.close()

    def _worker_status_completed(self, response: object) -> None:
        if isinstance(response, Response):
            session = f" session {response.session_id}" if response.session_id else ""
            self.statusBar().showMessage(f"Worker status: {response.state}{session}")

    def _worker_status_failed(self, _message: str) -> None:
        self.statusBar().showMessage("Worker status: unavailable")

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
        super().closeEvent(event)
