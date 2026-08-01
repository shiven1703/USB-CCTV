"""Short-lived Qt multimedia test that always releases its capture resources."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import QBuffer, QIODevice, QObject, QTimer
from PySide6.QtMultimedia import QAudioSource, QCamera, QMediaCaptureSession, QMediaDevices
from PySide6.QtMultimediaWidgets import QVideoWidget

from usb_cctv_recorder.application.dto import AudioSource, VideoDevice

PreviewCallback = Callable[[bool, str, bool], None]


class QtMultimediaPreview(QObject):
    """Tests packets and frames for a few seconds, then closes every opened device."""

    def __init__(self, video_widget: QVideoWidget, duration_milliseconds: int = 3_000) -> None:
        super().__init__(video_widget)
        self._video_widget = video_widget
        self._duration_milliseconds = duration_milliseconds
        self._callback: PreviewCallback | None = None
        self._camera: QCamera | None = None
        self._audio_source: QAudioSource | None = None
        self._audio_buffer: QBuffer | None = None
        self._capture_session: QMediaCaptureSession | None = None
        self._received_video = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._complete)

    def start(
        self, camera: VideoDevice, microphone: AudioSource, callback: PreviewCallback
    ) -> None:
        self.stop()
        self._callback = callback
        selected_camera = next(
            (
                candidate
                for candidate in QMediaDevices.videoInputs()
                if bytes(candidate.id().data()).decode(errors="replace") == camera.current_path
            ),
            None,
        )
        selected_microphone = next(
            (
                candidate
                for candidate in QMediaDevices.audioInputs()
                if bytes(candidate.id().data()).decode(errors="replace") == microphone.stable_id
            ),
            None,
        )
        if selected_camera is None or selected_microphone is None:
            self._notify_failure("The selected camera or microphone is no longer available.")
            return

        self._capture_session = QMediaCaptureSession(self)
        self._camera = QCamera(selected_camera, self)
        self._capture_session.setCamera(self._camera)
        self._capture_session.setVideoOutput(self._video_widget)
        self._video_widget.videoSink().videoFrameChanged.connect(self._on_video_frame)
        self._camera.errorOccurred.connect(self._on_camera_error)

        self._audio_buffer = QBuffer(self)
        self._audio_buffer.open(QIODevice.OpenModeFlag.ReadWrite)
        self._audio_source = QAudioSource(
            selected_microphone, selected_microphone.preferredFormat(), self
        )
        self._audio_source.start(self._audio_buffer)
        self._camera.start()
        self._timer.start(self._duration_milliseconds)

    def stop(self) -> None:
        """Idempotently stop devices after both successful and unsuccessful tests."""
        self._timer.stop()
        if self._camera is not None:
            self._camera.stop()
        if self._audio_source is not None:
            self._audio_source.stop()
        if self._audio_buffer is not None:
            self._audio_buffer.close()
        self._camera = None
        self._audio_source = None
        self._audio_buffer = None
        self._capture_session = None
        self._received_video = False

    def _on_video_frame(self) -> None:
        self._received_video = True

    def _on_camera_error(self, _error: object, message: str) -> None:
        self._notify_failure(message or "The camera test failed.")

    def _complete(self) -> None:
        audio_active = self._audio_buffer is not None and self._audio_buffer.size() > 0
        succeeded = self._received_video and audio_active
        message = (
            "Camera preview and microphone packets verified."
            if succeeded
            else ("No video frame or microphone packets arrived during the test.")
        )
        callback = self._callback
        self._callback = None
        self.stop()
        if callback is not None:
            callback(succeeded, message, audio_active)

    def _notify_failure(self, message: str) -> None:
        callback = self._callback
        self._callback = None
        self.stop()
        if callback is not None:
            callback(False, message, False)
