"""Qt tests for Phase 3 setup persistence and short-lived test cleanup."""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtMultimediaWidgets import QVideoWidget

from usb_cctv_recorder.application.configuration import (
    RecorderConfiguration,
    WorkerRecordingConfiguration,
)
from usb_cctv_recorder.application.dto import (
    AudioSource,
    CaptureMode,
    DeviceDiscovery,
    DiscoveryError,
    DiscoveryErrorCode,
    StorageEstimate,
    VideoDevice,
)
from usb_cctv_recorder.application.preflight import PreflightService
from usb_cctv_recorder.application.storage import StorageDashboard, StorageUsage
from usb_cctv_recorder.presentation.qt.pages.setup_page import PreviewTestPort, SetupPage
from usb_cctv_recorder.presentation.qt.preview import PreviewCallback


class StaticDiscovery:
    def __init__(self, value: DeviceDiscovery) -> None:
        self.value = value

    def discover(self) -> DeviceDiscovery:
        return self.value


class WritableStorage:
    def estimate(self, configuration: RecorderConfiguration) -> StorageEstimate:
        assert configuration.media_root.is_absolute()
        return StorageEstimate(
            100_000_000_000, 62_000_000_000, "Estimated safe recording space: 62.0 GB."
        )


class FakePreview(PreviewTestPort):
    def __init__(self, _widget: QVideoWidget, succeeded: bool = True) -> None:
        self.succeeded = succeeded
        self.started = 0
        self.stopped = 0

    def start(
        self, camera: VideoDevice, microphone: AudioSource, callback: PreviewCallback
    ) -> None:
        self.started += 1
        callback(
            self.succeeded, "test complete" if self.succeeded else "test failed", self.succeeded
        )

    def stop(self) -> None:
        self.stopped += 1


def fixture_discovery() -> DeviceDiscovery:
    mode = CaptureMode("MJPG", "Motion-JPEG", 2560, 1440, 30)
    return DeviceDiscovery(
        (VideoDevice("/dev/v4l/by-id/camera", "USB 2.0 Camera 2K", "/dev/video8", (mode,)),),
        (AudioSource("alsa_input.camera", "USB camera microphone", "s16le 1ch 48000Hz"),),
    )


def setup_page(tmp_path: Path, succeeded: bool = True) -> tuple[SetupPage, FakePreview, QSettings]:
    settings = QSettings(str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat)
    preview_holder: list[FakePreview] = []

    def preview_factory(widget: QVideoWidget) -> FakePreview:
        preview = FakePreview(widget, succeeded)
        preview_holder.append(preview)
        return preview

    page = SetupPage(
        PreflightService(StaticDiscovery(fixture_discovery()), WritableStorage()),
        settings,
        preview_factory,
    )
    page.output_directory.setText(str(tmp_path))
    page.set_discovery(fixture_discovery())
    return page, preview_holder[0], settings


def test_start_is_disabled_until_successful_preflight(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    page, preview, _ = setup_page(tmp_path)
    qtbot.addWidget(page)
    page.show()

    assert not page.start_button.isEnabled()
    page.test_button.click()

    assert preview.started == 1
    assert preview.stopped >= 1
    assert page.start_button.isEnabled()
    assert page.microphone_activity.text() == "Microphone activity: packets received"


def test_failed_preview_releases_resources_and_keeps_start_disabled(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    page, preview, _ = setup_page(tmp_path, succeeded=False)
    qtbot.addWidget(page)
    page.show()
    page.test_button.click()

    assert preview.stopped >= 1
    assert not page.start_button.isEnabled()
    assert "test failed" in page.preflight_status.text()


def test_selection_persists_by_stable_identity(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    page, _, settings = setup_page(tmp_path)
    qtbot.addWidget(page)
    page.camera_selector.setCurrentIndex(0)
    page.microphone_selector.setCurrentIndex(0)
    page.segment_duration.setValue(15)
    page._selection_changed()
    settings.sync()

    restored, _, _ = setup_page(tmp_path)
    assert restored.camera_selector.currentData().stable_id == "/dev/v4l/by-id/camera"
    assert restored.microphone_selector.currentData().stable_id == "alsa_input.camera"
    assert restored.segment_duration.value() == 15


def test_selection_persists_worker_readable_capture_configuration(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    saved: list[WorkerRecordingConfiguration] = []

    class WorkerStore:
        def save(self, configuration: WorkerRecordingConfiguration) -> None:
            saved.append(configuration)

    page, _, settings = setup_page(tmp_path)
    page = SetupPage(
        PreflightService(StaticDiscovery(fixture_discovery()), WritableStorage()),
        settings,
        worker_configuration=WorkerStore(),
    )
    qtbot.addWidget(page)
    page.output_directory.setText(str(tmp_path))
    page.set_discovery(fixture_discovery())
    page._selection_changed()
    assert saved[-1].camera_identity == "/dev/v4l/by-id/camera"
    assert saved[-1].microphone_source == "alsa_input.camera"
    assert saved[-1].media_root == tmp_path
    assert saved[-1].prevent_suspend
    assert not saved[-1].block_lid_close


def test_power_protection_settings_persist_to_worker_configuration(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    saved: list[WorkerRecordingConfiguration] = []

    class WorkerStore:
        def save(self, configuration: WorkerRecordingConfiguration) -> None:
            saved.append(configuration)

    page, _, settings = setup_page(tmp_path)
    page = SetupPage(
        PreflightService(StaticDiscovery(fixture_discovery()), WritableStorage()),
        settings,
        worker_configuration=WorkerStore(),
    )
    qtbot.addWidget(page)
    page.output_directory.setText(str(tmp_path))
    page.set_discovery(fixture_discovery())
    page.prevent_suspend.setChecked(False)
    assert not page.block_lid_close.isEnabled()
    page.prevent_suspend.setChecked(True)
    page.block_lid_close.setChecked(True)
    assert saved[-1].prevent_suspend
    assert saved[-1].block_lid_close


def test_discovery_error_is_visible_and_prevents_start(qtbot: pytest.QtBot, tmp_path: Path) -> None:
    page, _, _ = setup_page(tmp_path)
    qtbot.addWidget(page)
    page.set_discovery(
        DeviceDiscovery(
            (),
            (),
            DiscoveryError(DiscoveryErrorCode.PERMISSION_DENIED, "Camera permission denied."),
            DiscoveryError(DiscoveryErrorCode.PERMISSION_DENIED, "Microphone permission denied."),
        )
    )
    assert not page.start_button.isEnabled()
    assert "Camera permission denied." in page.preflight_status.text()


def test_storage_dashboard_and_policy_preferences_are_visible_and_worker_persisted(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    saved: list[WorkerRecordingConfiguration] = []

    class WorkerStore:
        def save(self, configuration: WorkerRecordingConfiguration) -> None:
            saved.append(configuration)

    class StorageService:
        def dashboard(self) -> StorageDashboard:
            return StorageDashboard(
                StorageUsage(originals_bytes=1_000_000_000),
                104_200_000_000,
                76_200_000_000,
                90_000_000_000,
                20_000_000_000,
                8_000_000_000,
                39_624_000_000,
                25_146_000_000,
                3_810_000_000,
                7_620_000_000,
                1_650_000_000,
                900_000_000,
                13_200_000_000,
                39_600_000_000,
                92_400_000_000,
                3,
                7,
            )

    settings = QSettings(str(tmp_path / "preferences.ini"), QSettings.Format.IniFormat)
    page = SetupPage(
        PreflightService(StaticDiscovery(fixture_discovery()), WritableStorage()),
        settings,
        worker_configuration=WorkerStore(),
        storage_service=StorageService(),  # type: ignore[arg-type]
    )
    qtbot.addWidget(page)
    page.output_directory.setText(str(tmp_path))
    page.set_discovery(fixture_discovery())
    page.storage_cap_gb.setValue(80.0)
    page.operating_system_reserve_gb.setValue(19.0)
    page.emergency_reserve_gb.setValue(7.0)
    page._selection_changed()

    assert "Actual managed usage" in page.storage_dashboard.text()
    assert saved[-1].configured_storage_cap_bytes == 80_000_000_000
    assert saved[-1].operating_system_reserve_bytes == 19_000_000_000
    assert saved[-1].emergency_finalization_reserve_bytes == 7_000_000_000
