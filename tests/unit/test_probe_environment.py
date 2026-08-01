from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPOSITORY_ROOT / "scripts" / "probe_environment.py"
SPEC = importlib.util.spec_from_file_location("probe_environment", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
probe_environment = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe_environment)


class EnvironmentProbeParserTests(unittest.TestCase):
    def fixture(self, name: str) -> str:
        return (REPOSITORY_ROOT / "tests" / "fixtures" / "probe" / name).read_text(encoding="utf-8")

    def test_parses_os_release(self) -> None:
        result = probe_environment.parse_key_value_lines(self.fixture("os-release.txt"))
        self.assertEqual(result["ID"], "ubuntu")
        self.assertEqual(result["VERSION_ID"], "24.04")

    def test_parses_pactl_sources(self) -> None:
        sources = probe_environment.parse_pactl_sources(self.fixture("pactl-sources.txt"))
        self.assertEqual(sources[1]["name"], "alsa_input.usb_camera_2k.mono-fallback")
        self.assertEqual(sources[1]["state"], "SUSPENDED")

    def test_selects_webcam_microphone_without_using_default_source(self) -> None:
        sources = probe_environment.parse_pactl_sources(self.fixture("pactl-sources.txt"))
        selected = probe_environment.select_audio_source(sources, "alsa_input.usb_camera_2k.mono-fallback")
        self.assertIsNotNone(selected)
        self.assertEqual(selected["sample_spec"], "s16le 1ch 48000Hz")

    def test_parses_pactl_server_info(self) -> None:
        server = probe_environment.parse_pactl_info("Server Name: PulseAudio (on PipeWire 1.2.0)\n")
        self.assertEqual(server["Server Name"], "PulseAudio (on PipeWire 1.2.0)")

    def test_parses_v4l2_devices_and_modes(self) -> None:
        devices = probe_environment.parse_v4l2_devices(self.fixture("v4l2-devices.txt"))
        formats = probe_environment.parse_v4l2_formats(self.fixture("v4l2-formats.txt"))
        self.assertEqual(devices[0]["paths"], ["/dev/video2", "/dev/video3"])
        self.assertEqual(formats[0]["pixel_format"], "MJPG")
        self.assertEqual(formats[0]["sizes"][0], {"resolution": "2560x1440", "frame_rates": [30.0]})

    def test_finds_device_after_transient_node_changes(self) -> None:
        devices = [
            {
                "path": "/dev/video2",
                "persistent_aliases": ["/dev/v4l/by-id/usb-camera-video-index0"],
            },
            {
                "path": "/dev/video6",
                "persistent_aliases": ["/dev/v4l/by-id/usb-camera-video-index0"],
            },
        ]
        found = probe_environment.find_video_device_by_alias(devices, "/dev/v4l/by-id/usb-camera-video-index0")
        self.assertEqual(found["path"], "/dev/video2")

    def test_classifies_capture_and_metadata_nodes(self) -> None:
        capture_formats = probe_environment.parse_v4l2_formats(self.fixture("v4l2-formats.txt"))
        self.assertEqual(probe_environment.classify_video_node(capture_formats), "capture")
        self.assertEqual(probe_environment.classify_video_node([]), "metadata_or_unusable")

    def test_parses_hardware_encoder_candidates(self) -> None:
        self.assertEqual(
            probe_environment.parse_encoder_candidates(self.fixture("ffmpeg-encoders.txt")),
            ["h264_vaapi", "hevc_qsv"],
        )

    def test_malformed_output_is_safe(self) -> None:
        self.assertEqual(probe_environment.parse_pactl_sources("not a source"), [])
        self.assertEqual(probe_environment.parse_v4l2_devices("broken output"), [])
        self.assertEqual(probe_environment.parse_v4l2_formats("[bad]"), [])
        self.assertEqual(probe_environment.parse_version("\n\n"), None)

    def test_missing_command_is_reported(self) -> None:
        result = probe_environment.command_result(["definitely-not-an-installed-command", "--version"])
        self.assertEqual(result["status"], "missing")

    def test_probe_does_not_write_without_an_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            report = probe_environment.probe()
            self.assertEqual(list(temporary_path.iterdir()), [])
        self.assertEqual(report["schema_version"], 1)

    def test_output_path_is_the_only_path_written(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary_path = Path(temporary_directory)
            output_path = temporary_path / "report.json"
            probe_environment.write_report(output_path, "{}\n")
            self.assertEqual([path.name for path in temporary_path.iterdir()], ["report.json"])
            self.assertEqual(output_path.read_text(encoding="utf-8"), "{}\n")


if __name__ == "__main__":
    unittest.main()
