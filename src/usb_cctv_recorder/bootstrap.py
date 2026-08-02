"""Composition root for the desktop application."""

from pathlib import Path

from .application.archive import ArchiveService
from .application.library import LibraryService
from .application.preflight import PreflightService
from .infrastructure.commands.runner import StructuredCommandRunner
from .infrastructure.configuration import WorkerConfigurationStore, XdgPaths
from .infrastructure.devices.audio_discovery import PulseAudioSourceDiscovery
from .infrastructure.devices.discovery import LocalDeviceDiscovery
from .infrastructure.devices.video_discovery import V4l2VideoDiscovery
from .infrastructure.ipc.client import UnixSocketClient
from .infrastructure.persistence.library_catalogue import SQLiteLibraryCatalogue
from .infrastructure.persistence.sqlite import SQLiteCatalogue
from .infrastructure.storage.archive_transaction import ArchiveTransactionManager
from .infrastructure.storage.preflight import FilesystemStorageEstimate
from .presentation.qt.app import run_application
from .presentation.qt.main_window import MainWindow


def rebuild_catalogue(media_root: Path) -> int:
    """Reconstruct derived browse state without writing any media file."""
    paths = XdgPaths.resolve()
    catalogue = SQLiteLibraryCatalogue(SQLiteCatalogue(paths.state / "catalogue.sqlite"))
    return catalogue.rebuild(media_root)


def run_gui() -> int:
    """Start the setup page with local discovery adapters."""
    paths = XdgPaths.resolve()
    runner = StructuredCommandRunner()
    discovery = LocalDeviceDiscovery(V4l2VideoDiscovery(runner), PulseAudioSourceDiscovery(runner))
    service = PreflightService(discovery, FilesystemStorageEstimate())
    configuration_store = WorkerConfigurationStore(paths)
    configuration = configuration_store.load()
    media_root = configuration.media_root if configuration is not None else paths.media
    catalogue = SQLiteLibraryCatalogue(SQLiteCatalogue(paths.state / "catalogue.sqlite"))
    library_service = LibraryService(catalogue)
    archive_service = ArchiveService(ArchiveTransactionManager(catalogue))
    archive_service.recover_partials()

    def worker_client() -> UnixSocketClient:
        return UnixSocketClient(paths.runtime / "worker.sock")

    return run_application(
        lambda: MainWindow(
            service,
            worker_client,
            configuration_store,
            library_service,
            media_root,
            archive_service,
        )
    )
