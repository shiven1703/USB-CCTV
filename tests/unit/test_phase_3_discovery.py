"""Phase 3 discovery, capability, and preflight tests use only fixtures/fakes."""

from __future__ import annotations

from pathlib import Path

from usb_cctv_recorder.application.configuration import RecorderConfiguration
from usb_cctv_recorder.application.dto import (
    AudioSource,
    CaptureMode,
    DeviceDiscovery,
    PreflightErrorCode,
    StorageEstimate,
    VideoDevice,
)
from usb_cctv_recorder.application.preflight import PreflightService, SetupSelection
from usb_cctv_recorder.infrastructure.commands.runner import CommandResult
from usb_cctv_recorder.infrastructure.devices.audio_discovery import (
    PulseAudioSourceDiscovery,
    parse_pactl_short_sources,
    parse_pactl_source_details,
)
from usb_cctv_recorder.infrastructure.devices.video_discovery import (
    V4l2VideoDiscovery,
    parse_v4l2_capture_modes,
)
from usb_cctv_recorder.infrastructure.ffmpeg.capabilities import (
    FfmpegCapabilityProbe,
    parse_encoder_candidates,
    parse_muxers,
)
from usb_cctv_recorder.infrastructure.storage.preflight import FilesystemStorageEstimate

FIXTURES = Path(__file__).parents[1] / "fixtures"


class FakeRunner:
    def __init__(self, results: dict[tuple[str, ...], CommandResult]) -> None:
        self.results = results
        self.calls: list[tuple[str, ...]] = []

    def run(self, arguments: tuple[str, ...]) -> CommandResult:
        self.calls.append(arguments)
        return self.results[arguments]


def result(
    arguments: tuple[str, ...], stdout: str, returncode: int = 0, stderr: str = ""
) -> CommandResult:
    return CommandResult(arguments, returncode, stdout, stderr)


def test_v4l2_discovery_keeps_stable_identity_when_video_number_changes() -> None:
    device_output = (FIXTURES / "probe" / "v4l2-devices.txt").read_text()
    capture_output = (FIXTURES / "probe" / "v4l2-formats.txt").read_text()
    metadata_output = (FIXTURES / "phase_3" / "v4l2-metadata-formats.txt").read_text()
    runner = FakeRunner(
        {
            ("v4l2-ctl", "--list-devices"): result(("v4l2-ctl", "--list-devices"), device_output),
            ("v4l2-ctl", "--device", "/dev/video2", "--list-formats-ext"): result(
                ("v4l2-ctl", "--device", "/dev/video2", "--list-formats-ext"), capture_output
            ),
            ("v4l2-ctl", "--device", "/dev/video3", "--list-formats-ext"): result(
                ("v4l2-ctl", "--device", "/dev/video3", "--list-formats-ext"), metadata_output
            ),
        }
    )
    stable_id = "/dev/v4l/by-id/usb-camera-video-index0"
    discovery = V4l2VideoDiscovery(
        runner, lambda path: (stable_id,) if path == "/dev/video2" else ("metadata-index1",)
    )

    devices, error = discovery.discover()

    assert error is None
    assert [(device.stable_id, device.current_path) for device in devices] == [
        (stable_id, "/dev/video2")
    ]
    assert devices[0].capture_modes[0].pixel_format == "MJPG"

    changed_node_runner = FakeRunner(
        {
            ("v4l2-ctl", "--list-devices"): result(
                ("v4l2-ctl", "--list-devices"), "USB 2.0 Camera 2K:\n\t/dev/video8\n"
            ),
            ("v4l2-ctl", "--device", "/dev/video8", "--list-formats-ext"): result(
                ("v4l2-ctl", "--device", "/dev/video8", "--list-formats-ext"), capture_output
            ),
        }
    )
    changed_node_discovery = V4l2VideoDiscovery(changed_node_runner, lambda _path: (stable_id,))
    changed_devices, _ = changed_node_discovery.discover()
    assert changed_devices[0].stable_id == devices[0].stable_id
    assert changed_devices[0].current_path == "/dev/video8"


def test_v4l2_rejects_metadata_only_and_one_fps_modes() -> None:
    assert (
        parse_v4l2_capture_modes((FIXTURES / "phase_3" / "v4l2-metadata-formats.txt").read_text())
        == ()
    )
    assert (
        parse_v4l2_capture_modes(
            (FIXTURES / "phase_3" / "v4l2-unsupported-formats.txt").read_text()
        )
        == ()
    )


def test_duplicate_friendly_camera_names_remain_unambiguous() -> None:
    device_output = (FIXTURES / "phase_3" / "v4l2-duplicate-devices.txt").read_text()
    capture_output = (FIXTURES / "probe" / "v4l2-formats.txt").read_text()
    runner = FakeRunner(
        {
            ("v4l2-ctl", "--list-devices"): result(("v4l2-ctl", "--list-devices"), device_output),
            ("v4l2-ctl", "--device", "/dev/video2", "--list-formats-ext"): result(
                ("v4l2-ctl", "--device", "/dev/video2", "--list-formats-ext"), capture_output
            ),
            ("v4l2-ctl", "--device", "/dev/video4", "--list-formats-ext"): result(
                ("v4l2-ctl", "--device", "/dev/video4", "--list-formats-ext"), capture_output
            ),
        }
    )
    devices, _ = V4l2VideoDiscovery(runner, lambda path: (f"/dev/v4l/by-id/{path[-1]}",)).discover()
    assert devices[0].friendly_name == devices[1].friendly_name
    assert devices[0].label != devices[1].label


def test_v4l2_permission_denied_is_presented() -> None:
    runner = FakeRunner(
        {
            ("v4l2-ctl", "--list-devices"): result(
                ("v4l2-ctl", "--list-devices"), "", 1, "Permission denied"
            )
        }
    )
    devices, error = V4l2VideoDiscovery(runner).discover()
    assert devices == ()
    assert error is not None and error.code.value == "permission_denied"


def test_pulse_discovery_uses_source_name_as_stable_id_and_description_as_label() -> None:
    short = (FIXTURES / "probe" / "pactl-sources.txt").read_text()
    detail = (FIXTURES / "phase_3" / "pactl-source-details.txt").read_text()
    runner = FakeRunner(
        {
            ("pactl", "list", "short", "sources"): result(
                ("pactl", "list", "short", "sources"), short
            ),
            ("pactl", "list", "sources"): result(("pactl", "list", "sources"), detail),
        }
    )
    sources, error = PulseAudioSourceDiscovery(runner).discover()
    assert error is None
    assert sources[1] == AudioSource(
        "alsa_input.usb_camera_2k.mono-fallback", "USB 2.0 Camera 2K Mono", "s16le 1ch 48000Hz"
    )
    assert parse_pactl_short_sources(short)[sources[1].stable_id] == sources[1].sample_specification
    assert parse_pactl_source_details(detail)[sources[1].stable_id] == sources[1].friendly_name


def test_pulse_no_sources_and_permission_denied_are_reported() -> None:
    no_sources_runner = FakeRunner(
        {
            ("pactl", "list", "short", "sources"): result(
                ("pactl", "list", "short", "sources"), ""
            ),
            ("pactl", "list", "sources"): result(("pactl", "list", "sources"), ""),
        }
    )
    sources, error = PulseAudioSourceDiscovery(no_sources_runner).discover()
    assert sources == () and error is None

    denied_runner = FakeRunner(
        {
            ("pactl", "list", "short", "sources"): result(
                ("pactl", "list", "short", "sources"), "", 1, "Permission denied"
            ),
            ("pactl", "list", "sources"): result(("pactl", "list", "sources"), ""),
        }
    )
    _, error = PulseAudioSourceDiscovery(denied_runner).discover()
    assert error is not None and error.code.value == "permission_denied"


def test_ffmpeg_probe_reports_candidates_and_muxers_without_claiming_usability() -> None:
    encoders = (FIXTURES / "probe" / "ffmpeg-encoders.txt").read_text()
    muxers = "File formats:\n .E matroska        Matroska\n .E mp4             MP4\n"
    runner = FakeRunner(
        {
            ("ffmpeg", "-hide_banner", "-encoders"): result(
                ("ffmpeg", "-hide_banner", "-encoders"), encoders
            ),
            ("ffmpeg", "-hide_banner", "-muxers"): result(
                ("ffmpeg", "-hide_banner", "-muxers"), muxers
            ),
        }
    )
    capabilities = FfmpegCapabilityProbe(runner).probe()
    assert capabilities.encoder_candidates == ("libx264", "h264_vaapi", "hevc_qsv")
    assert capabilities.muxers == ("matroska", "mp4")
    assert "libx264" in parse_encoder_candidates(encoders)
    assert parse_muxers(muxers) == ("matroska", "mp4")


class StaticDiscovery:
    def __init__(self, discovery: DeviceDiscovery) -> None:
        self.discovery = discovery

    def discover(self) -> DeviceDiscovery:
        return self.discovery


class StaticStorage:
    def __init__(self, estimate: StorageEstimate) -> None:
        self.value = estimate

    def estimate(self, configuration: RecorderConfiguration) -> StorageEstimate:
        assert configuration.segment_duration_minutes == 60
        return self.value


def test_preflight_rejects_missing_devices_unsupported_mode_and_requires_test(
    tmp_path: Path,
) -> None:
    mode = CaptureMode("MJPG", "Motion-JPEG", 2560, 1440, 30)
    unsupported_mode = CaptureMode("YUYV", "YUYV", 2560, 1440, 1)
    camera = VideoDevice("/dev/v4l/by-id/camera", "Camera", "/dev/video8", (mode,))
    microphone = AudioSource("alsa_input.camera", "Camera microphone", "s16le 1ch 48000Hz")
    service = PreflightService(
        StaticDiscovery(DeviceDiscovery((camera,), (microphone,))),
        StaticStorage(StorageEstimate(90_000_000_000, 62_000_000_000, "space")),
    )
    configuration = RecorderConfiguration(media_root=tmp_path)
    unsupported = service.validate(
        service.discover(),
        SetupSelection(camera.stable_id, microphone.stable_id, unsupported_mode, configuration),
        preview_succeeded=False,
    )
    assert PreflightErrorCode.UNSUPPORTED_MODE in unsupported.errors
    assert PreflightErrorCode.PREVIEW_REQUIRED in unsupported.errors

    missing = service.validate(
        service.discover(), SetupSelection(None, None, None, configuration), preview_succeeded=False
    )
    assert {PreflightErrorCode.CAMERA_MISSING, PreflightErrorCode.MICROPHONE_MISSING} <= set(
        missing.errors
    )


def test_filesystem_storage_estimate_requires_an_existing_writable_directory(
    tmp_path: Path,
) -> None:
    adapter = FilesystemStorageEstimate()
    missing = adapter.estimate(RecorderConfiguration(media_root=tmp_path / "missing"))
    assert not missing.usable and missing.safe_recording_bytes == 0
    estimate = adapter.estimate(RecorderConfiguration(media_root=tmp_path))
    assert estimate.usable
    assert 0 <= estimate.safe_recording_bytes <= 90_000_000_000
