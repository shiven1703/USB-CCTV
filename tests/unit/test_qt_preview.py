"""Resource-lifecycle tests for the Qt preview adapter without real hardware."""

from __future__ import annotations

import pytest
from PySide6.QtMultimediaWidgets import QVideoWidget

from usb_cctv_recorder.application.dto import AudioSource, VideoDevice
from usb_cctv_recorder.presentation.qt import preview


class Signal:
    def __init__(self) -> None:
        self.callback: object | None = None

    def connect(self, callback: object) -> None:
        self.callback = callback


class DeviceIdentifier:
    def __init__(self, value: str) -> None:
        self.value = value

    def data(self) -> bytes:
        return self.value.encode()


class Device:
    def __init__(self, identifier: str) -> None:
        self.identifier = identifier

    def id(self) -> DeviceIdentifier:
        return DeviceIdentifier(self.identifier)

    def preferredFormat(self) -> object:
        return object()


class FakeMediaDevices:
    camera = Device("/dev/video8")
    microphone = Device("alsa_input.camera")

    @classmethod
    def videoInputs(cls) -> list[Device]:
        return [cls.camera]

    @classmethod
    def audioInputs(cls) -> list[Device]:
        return [cls.microphone]


class FakeCamera:
    instances: list[FakeCamera] = []

    def __init__(self, _device: Device, _parent: object) -> None:
        self.started = False
        self.stopped = False
        self.errorOccurred = Signal()
        self.instances.append(self)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True


class FakeAudioSource:
    instances: list[FakeAudioSource] = []

    def __init__(self, _device: Device, _format: object, _parent: object) -> None:
        self.stopped = False
        self.instances.append(self)

    def start(self, buffer: object) -> None:
        buffer.write(b"audio packets")  # type: ignore[attr-defined]

    def stop(self) -> None:
        self.stopped = True


class FakeCaptureSession:
    def __init__(self, _parent: object) -> None:
        self.camera: object | None = None
        self.output: object | None = None

    def setCamera(self, camera: object) -> None:
        self.camera = camera

    def setVideoOutput(self, output: object) -> None:
        self.output = output


def test_preview_releases_camera_and_microphone_after_success(
    qtbot: pytest.QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(preview, "QMediaDevices", FakeMediaDevices)
    monkeypatch.setattr(preview, "QCamera", FakeCamera)
    monkeypatch.setattr(preview, "QAudioSource", FakeAudioSource)
    monkeypatch.setattr(preview, "QMediaCaptureSession", FakeCaptureSession)
    widget = QVideoWidget()
    qtbot.addWidget(widget)
    controller = preview.QtMultimediaPreview(widget)
    results: list[tuple[bool, str, bool]] = []
    camera = VideoDevice("camera", "Camera", "/dev/video8", ())
    microphone = AudioSource("alsa_input.camera", "Microphone", "s16le 1ch 48000Hz")

    controller.start(camera, microphone, lambda *result: results.append(result))
    controller._on_video_frame()
    controller._complete()

    assert results == [(True, "Camera preview and microphone packets verified.", True)]
    assert FakeCamera.instances[-1].started and FakeCamera.instances[-1].stopped
    assert FakeAudioSource.instances[-1].stopped


def test_preview_releases_nothing_opened_when_selected_device_disappears(
    qtbot: pytest.QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    class MissingDevices(FakeMediaDevices):
        @classmethod
        def videoInputs(cls) -> list[Device]:
            return []

    monkeypatch.setattr(preview, "QMediaDevices", MissingDevices)
    widget = QVideoWidget()
    qtbot.addWidget(widget)
    controller = preview.QtMultimediaPreview(widget)
    results: list[tuple[bool, str, bool]] = []
    controller.start(
        VideoDevice("camera", "Camera", "/dev/video8", ()),
        AudioSource("alsa_input.camera", "Microphone", "s16le 1ch 48000Hz"),
        lambda *result: results.append(result),
    )
    assert results == [(False, "The selected camera or microphone is no longer available.", False)]
