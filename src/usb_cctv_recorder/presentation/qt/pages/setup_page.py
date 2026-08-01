"""Phase 3 setup and preflight page."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from PySide6.QtCore import QSettings
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from usb_cctv_recorder.application.configuration import RecorderConfiguration
from usb_cctv_recorder.application.dto import (
    AudioSource,
    CaptureMode,
    DeviceDiscovery,
    PreflightErrorCode,
    VideoDevice,
)
from usb_cctv_recorder.application.preflight import PreflightService, SetupSelection

from ..preview import PreviewCallback, QtMultimediaPreview


class PreviewTestPort(Protocol):
    def start(
        self, camera: VideoDevice, microphone: AudioSource, callback: PreviewCallback
    ) -> None: ...

    def stop(self) -> None: ...


class SetupPage(QWidget):
    """Stores UI preferences only; validated configuration stays application-facing."""

    def __init__(
        self,
        service: PreflightService | None = None,
        settings: QSettings | None = None,
        preview_factory: Callable[[QVideoWidget], PreviewTestPort] = QtMultimediaPreview,
    ) -> None:
        super().__init__()
        self._service = service
        self._settings = settings or QSettings("USB CCTV Recorder", "USB CCTV Recorder")
        self._discovery = DeviceDiscovery((), ())
        self._preview_succeeded = False
        self._preview_failed = False
        self._preview_message = "Run the camera and microphone test before starting."

        self.camera_selector = QComboBox()
        self.microphone_selector = QComboBox()
        self.mode_selector = QComboBox()
        self.segment_duration = QSpinBox()
        self.segment_duration.setRange(1, 360)
        self.segment_duration.setValue(int(str(self._settings.value("segment_duration", 60))))
        self.output_directory = QLineEdit(
            str(self._settings.value("output_directory", str(Path.home() / "Videos")))
        )
        browse_button = QPushButton("Browse…")
        browse_button.clicked.connect(self._choose_output_directory)
        output_layout = QHBoxLayout()
        output_layout.addWidget(self.output_directory)
        output_layout.addWidget(browse_button)
        self.video_preview = QVideoWidget()
        self.video_preview.setMinimumHeight(180)
        self.microphone_activity = QLabel("Microphone activity: not tested")
        self.storage_estimate = QLabel("Storage estimate: awaiting configuration")
        self.preflight_status = QLabel(self._preview_message)
        self.test_button = QPushButton("Test camera and microphone")
        self.test_button.clicked.connect(self._run_test)
        self.start_button = QPushButton("Start")
        self.start_button.setEnabled(False)
        self._preview = preview_factory(self.video_preview)

        form = QFormLayout()
        form.addRow("Camera", self.camera_selector)
        form.addRow("Microphone", self.microphone_selector)
        form.addRow("Capture mode", self.mode_selector)
        form.addRow("Segment duration (minutes)", self.segment_duration)
        form.addRow("Recording directory", output_layout)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.video_preview)
        layout.addWidget(self.microphone_activity)
        layout.addWidget(self.storage_estimate)
        layout.addWidget(self.preflight_status)
        layout.addWidget(self.test_button)
        layout.addWidget(self.start_button)

        self.camera_selector.currentIndexChanged.connect(self._camera_changed)
        self.microphone_selector.currentIndexChanged.connect(self._selection_changed)
        self.mode_selector.currentIndexChanged.connect(self._selection_changed)
        self.segment_duration.valueChanged.connect(self._selection_changed)
        self.output_directory.editingFinished.connect(self._selection_changed)

    def set_discovery(self, discovery: DeviceDiscovery) -> None:
        self._discovery = discovery
        self._populate(self.camera_selector, discovery.video_devices, "camera_stable_id")
        self._populate(self.microphone_selector, discovery.audio_sources, "microphone_stable_id")
        self._camera_changed()
        messages = [
            error.message for error in (discovery.video_error, discovery.audio_error) if error
        ]
        if messages:
            self.preflight_status.setText(" ".join(messages))

    def _populate(self, selector: QComboBox, values: tuple[object, ...], settings_key: str) -> None:
        selector.blockSignals(True)
        selector.clear()
        for value in values:
            selector.addItem(value.label, value)  # type: ignore[attr-defined]
        saved_id = str(self._settings.value(settings_key, ""))
        for index in range(selector.count()):
            item = selector.itemData(index)
            if getattr(item, "stable_id", None) == saved_id:
                selector.setCurrentIndex(index)
                break
        selector.blockSignals(False)

    def _camera_changed(self) -> None:
        self.mode_selector.blockSignals(True)
        self.mode_selector.clear()
        camera = self._selected_camera()
        if camera is not None:
            for mode in camera.capture_modes:
                self.mode_selector.addItem(mode.label, mode)
        self.mode_selector.blockSignals(False)
        self._selection_changed()

    def _selection_changed(self) -> None:
        self._preview.stop()
        self._preview_succeeded = False
        self._preview_failed = False
        self.microphone_activity.setText("Microphone activity: not tested")
        self._persist_selection()
        self._update_preflight()

    def _persist_selection(self) -> None:
        camera = self._selected_camera()
        microphone = self._selected_microphone()
        self._settings.setValue("camera_stable_id", camera.stable_id if camera else "")
        self._settings.setValue("microphone_stable_id", microphone.stable_id if microphone else "")
        self._settings.setValue("segment_duration", self.segment_duration.value())
        self._settings.setValue("output_directory", self.output_directory.text())

    def _update_preflight(self) -> None:
        if self._service is None:
            return
        try:
            configuration = RecorderConfiguration(
                media_root=Path(self.output_directory.text()).expanduser(),
                segment_duration_minutes=self.segment_duration.value(),
            )
        except ValueError:
            self.start_button.setEnabled(False)
            self.preflight_status.setText("Choose an absolute recording directory.")
            return
        result = self._service.validate(
            self._discovery,
            SetupSelection(
                self._selected_camera_stable_id(),
                self._selected_microphone_stable_id(),
                self._selected_mode(),
                configuration,
            ),
            preview_succeeded=self._preview_succeeded,
            preview_failed=self._preview_failed,
        )
        self.start_button.setEnabled(result.ready)
        if result.storage_estimate is not None:
            self.storage_estimate.setText(result.storage_estimate.message)
        self.preflight_status.setText(_preflight_message(result.errors, self._preview_message))

    def _run_test(self) -> None:
        camera = self._selected_camera()
        microphone = self._selected_microphone()
        if camera is None or microphone is None or self._selected_mode() is None:
            self.preflight_status.setText(
                "Select a camera, microphone, and supported capture mode first."
            )
            return
        self.test_button.setEnabled(False)
        self.preflight_status.setText("Testing camera preview and microphone activity…")
        self._preview.start(camera, microphone, self._test_finished)

    def _test_finished(self, succeeded: bool, message: str, microphone_active: bool) -> None:
        self._preview.stop()
        self.test_button.setEnabled(True)
        self._preview_succeeded = succeeded
        self._preview_failed = not succeeded
        self._preview_message = message
        self.microphone_activity.setText(
            "Microphone activity: packets received"
            if microphone_active
            else "Microphone activity: none"
        )
        self._update_preflight()

    def _choose_output_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Select recording directory")
        if selected:
            self.output_directory.setText(selected)
            self._selection_changed()

    def _selected_camera(self) -> VideoDevice | None:
        value = self.camera_selector.currentData()
        return value if isinstance(value, VideoDevice) else None

    def _selected_microphone(self) -> AudioSource | None:
        value = self.microphone_selector.currentData()
        return value if isinstance(value, AudioSource) else None

    def _selected_mode(self) -> CaptureMode | None:
        value = self.mode_selector.currentData()
        return value if isinstance(value, CaptureMode) else None

    def _selected_camera_stable_id(self) -> str | None:
        camera = self._selected_camera()
        return camera.stable_id if camera is not None else None

    def _selected_microphone_stable_id(self) -> str | None:
        microphone = self._selected_microphone()
        return microphone.stable_id if microphone is not None else None


def _preflight_message(errors: tuple[PreflightErrorCode, ...], preview_message: str) -> str:
    if not errors:
        return "Preflight passed. Recording can start when the Phase 4 worker is available."
    messages = {
        PreflightErrorCode.CAMERA_MISSING: "Select an available camera.",
        PreflightErrorCode.MICROPHONE_MISSING: "Select an available microphone.",
        PreflightErrorCode.UNSUPPORTED_MODE: "The selected capture mode is unsupported.",
        PreflightErrorCode.OUTPUT_DIRECTORY: "Choose a writable recording directory.",
        PreflightErrorCode.INSUFFICIENT_STORAGE: (
            "The recording directory has insufficient safe space."
        ),
        PreflightErrorCode.PREVIEW_REQUIRED: preview_message,
        PreflightErrorCode.PREVIEW_FAILED: preview_message,
    }
    return " ".join(messages[error] for error in errors)
