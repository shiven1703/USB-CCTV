"""Composes the independent video and audio discovery adapters."""

from __future__ import annotations

from usb_cctv_recorder.application.dto import DeviceDiscovery

from .audio_discovery import PulseAudioSourceDiscovery
from .video_discovery import V4l2VideoDiscovery


class LocalDeviceDiscovery:
    def __init__(self, video: V4l2VideoDiscovery, audio: PulseAudioSourceDiscovery) -> None:
        self._video = video
        self._audio = audio

    def discover(self) -> DeviceDiscovery:
        video_devices, video_error = self._video.discover()
        audio_sources, audio_error = self._audio.discover()
        return DeviceDiscovery(video_devices, audio_sources, video_error, audio_error)
