"""Composition root for the desktop application."""

from .application.preflight import PreflightService
from .infrastructure.commands.runner import StructuredCommandRunner
from .infrastructure.configuration import WorkerConfigurationStore, XdgPaths
from .infrastructure.devices.audio_discovery import PulseAudioSourceDiscovery
from .infrastructure.devices.discovery import LocalDeviceDiscovery
from .infrastructure.devices.video_discovery import V4l2VideoDiscovery
from .infrastructure.ipc.client import UnixSocketClient
from .infrastructure.storage.preflight import FilesystemStorageEstimate
from .presentation.qt.app import run_application
from .presentation.qt.main_window import MainWindow


def run_gui() -> int:
    """Start the setup page with local discovery adapters."""
    paths = XdgPaths.resolve()
    runner = StructuredCommandRunner()
    discovery = LocalDeviceDiscovery(V4l2VideoDiscovery(runner), PulseAudioSourceDiscovery(runner))
    service = PreflightService(discovery, FilesystemStorageEstimate())

    def worker_client() -> UnixSocketClient:
        return UnixSocketClient(paths.runtime / "worker.sock")

    return run_application(
        lambda: MainWindow(service, worker_client, WorkerConfigurationStore(paths))
    )
