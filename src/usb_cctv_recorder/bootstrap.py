"""Composition root for the desktop application."""

from pathlib import Path

from .application.archive import ArchiveService
from .application.library import LibraryService
from .application.preflight import PreflightService
from .application.storage import StorageGovernorService, StoragePolicy
from .infrastructure.commands.runner import StructuredCommandRunner
from .infrastructure.configuration import WorkerConfigurationStore, XdgPaths
from .infrastructure.devices.audio_discovery import PulseAudioSourceDiscovery
from .infrastructure.devices.discovery import LocalDeviceDiscovery
from .infrastructure.devices.video_discovery import V4l2VideoDiscovery
from .infrastructure.ipc.client import UnixSocketClient
from .infrastructure.persistence.library_catalogue import SQLiteLibraryCatalogue
from .infrastructure.persistence.sqlite import SQLiteCatalogue
from .infrastructure.storage.archive_transaction import ArchiveTransactionManager
from .infrastructure.storage.governor import FilesystemStorageGovernor
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
    archive_manager = ArchiveTransactionManager(catalogue)
    catalogue_path = paths.state / "catalogue.sqlite"
    policy = (
        StoragePolicy(
            configured_cap_bytes=configuration.configured_storage_cap_bytes,
            operating_system_reserve_bytes=configuration.operating_system_reserve_bytes,
            emergency_finalization_reserve_bytes=configuration.emergency_finalization_reserve_bytes,
        )
        if configuration is not None
        else StoragePolicy()
    )
    storage_governor = FilesystemStorageGovernor(
        media_root,
        catalogue,
        archive_manager,
        policy,
        metadata_paths=(
            catalogue_path,
            catalogue_path.with_name("catalogue.sqlite-wal"),
            catalogue_path.with_name("catalogue.sqlite-shm"),
        ),
    )
    archive_manager.set_storage_reserve_checker(
        lambda required: not storage_governor.ensure_working_reserve(
            required, recording_active=False
        ).remaining_bytes_needed
    )
    storage_service = StorageGovernorService(storage_governor)
    archive_service = ArchiveService(archive_manager)
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
            storage_service,
        )
    )
