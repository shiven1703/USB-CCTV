"""Headless recording and on-demand IPC worker entrypoints."""

from __future__ import annotations

import logging
import signal
from collections.abc import Callable
from pathlib import Path

from usb_cctv_recorder.application.configuration import WorkerRecordingConfiguration
from usb_cctv_recorder.application.dto import CaptureMode
from usb_cctv_recorder.domain.states import SessionState
from usb_cctv_recorder.infrastructure.configuration import WorkerConfigurationStore, XdgPaths
from usb_cctv_recorder.infrastructure.devices.hotplug import UdevVideoHotplugMonitor
from usb_cctv_recorder.infrastructure.ffmpeg.command_builder import (
    CameraCapture,
    FfmpegRecordingCommandBuilder,
    OutputProfile,
    RecordingSettings,
    build_synthetic_recording_command,
)
from usb_cctv_recorder.infrastructure.ipc.server import UnixSocketServer
from usb_cctv_recorder.infrastructure.power.inhibitor import SystemdInhibitAdapter
from usb_cctv_recorder.infrastructure.power.power_status import LinuxPowerStatusAdapter

from .recording import HeadlessRecordingController, RecordingFailure
from .supervisor import WorkerSupervisor


def run_ipc_worker(
    paths: XdgPaths | None = None,
    supervisor: WorkerSupervisor | None = None,
) -> int:
    """Run the service-owned worker until systemd stops it.

    The installed worker does not accept capture arguments over IPC. Persisted capture
    configuration is intentionally not introduced here because Phase 3 only owns setup
    preferences; a start without a worker factory reports that configuration is unavailable.
    """
    runtime_paths = paths or XdgPaths.resolve()
    runtime_paths.create_private_directories()
    if supervisor is None:
        try:
            configuration = WorkerConfigurationStore(runtime_paths).load()
        except AttributeError:
            # Lightweight socket harnesses need only a runtime directory.
            configuration = None
        active_supervisor = WorkerSupervisor(
            _recording_factory(configuration),
            inhibitor=SystemdInhibitAdapter(),
            power_status=LinuxPowerStatusAdapter(),
            prevent_suspend=configuration.prevent_suspend if configuration is not None else True,
            block_lid_close=configuration.block_lid_close if configuration is not None else False,
            hotplug_monitor=UdevVideoHotplugMonitor() if configuration is not None else None,
            camera_identity=configuration.camera_identity if configuration is not None else None,
        )
    else:
        active_supervisor = supervisor
    server = UnixSocketServer(runtime_paths.runtime / "worker.sock", active_supervisor.handle)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    server.start()
    previous_sigterm_handler = signal.getsignal(signal.SIGTERM)

    def request_shutdown(_signal_number: int, _frame: object) -> None:
        # Phase 6 adds active-recording finalization for systemd SIGTERM requests.
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, request_shutdown)
    exit_code = 0
    try:
        while True:
            server.serve_once()
            active_supervisor.poll()
    except KeyboardInterrupt:
        # SIGTERM is delivered by systemd before TimeoutStopSec. This completes the
        # bounded Phase 4 safe-stop path before the service is allowed to exit.
        exit_code = active_supervisor.finalize_for_shutdown()
    finally:
        server.close()
        signal.signal(signal.SIGTERM, previous_sigterm_handler)
    return exit_code


def _recording_factory(
    configuration: WorkerRecordingConfiguration | None,
) -> Callable[[], HeadlessRecordingController] | None:
    if configuration is None:
        return None

    def factory() -> HeadlessRecordingController:
        return _configured_controller(configuration)

    return factory


def _configured_controller(
    configuration: WorkerRecordingConfiguration,
) -> HeadlessRecordingController:
    persistent = Path(configuration.camera_identity)

    def settings(output_pattern: Path) -> RecordingSettings:
        # Resolve this selected stable alias for every initial and recovery attempt.
        resolved = persistent.resolve(strict=True)
        return RecordingSettings(
            camera=CameraCapture(
                configuration.camera_identity,
                resolved,
                CaptureMode(
                    "MJPG",
                    "Motion-JPEG",
                    configuration.width,
                    configuration.height,
                    configuration.input_frame_rate,
                ),
            ),
            microphone_source=configuration.microphone_source,
            output_profile=OutputProfile(
                configuration.width,
                configuration.height,
                configuration.output_frame_rate,
            ),
            segment_seconds=configuration.segment_duration_minutes * 60,
            output_pattern=output_pattern,
        )

    def command_factory(output_pattern: Path) -> tuple[str, ...]:
        return FfmpegRecordingCommandBuilder().build(settings(output_pattern))

    builder = FfmpegRecordingCommandBuilder()
    return HeadlessRecordingController(
        configuration.media_root,
        command_factory,
        emergency_command_factories={
            SessionState.RECORDING_AUDIO_ONLY: lambda output: builder.build_for_streams(
                settings(output), include_video=False, include_audio=True
            ),
            SessionState.RECORDING_VIDEO_ONLY: lambda output: builder.build_for_streams(
                settings(output), include_video=True, include_audio=False
            ),
        },
    )


def run_worker(
    *,
    media_root: Path | None = None,
    camera_identity: str | None = None,
    microphone_source: str | None = None,
    width: int = 2560,
    height: int = 1440,
    input_frame_rate: float = 30,
    output_frame_rate: float = 15,
    segment_minutes: int = 60,
    synthetic_duration_seconds: float | None = None,
) -> int:
    """Run the service worker, or one explicit foreground development recording."""
    if media_root is None:
        return run_ipc_worker()
    if synthetic_duration_seconds is not None:

        def command_factory(output_pattern: Path) -> tuple[str, ...]:
            return build_synthetic_recording_command(
                output_pattern, segment_minutes * 60, duration_seconds=synthetic_duration_seconds
            )
    else:
        if camera_identity is None or microphone_source is None:
            raise ValueError("camera identity and microphone source are required for recording")
        persistent = Path(camera_identity)
        resolved = persistent.resolve(strict=True)

        def command_factory(output_pattern: Path) -> tuple[str, ...]:
            return FfmpegRecordingCommandBuilder().build(
                RecordingSettings(
                    camera=CameraCapture(
                        camera_identity,
                        resolved,
                        CaptureMode("MJPG", "Motion-JPEG", width, height, input_frame_rate),
                    ),
                    microphone_source=microphone_source,
                    output_profile=OutputProfile(width, height, output_frame_rate),
                    segment_seconds=segment_minutes * 60,
                    output_pattern=output_pattern,
                )
            )

    controller = HeadlessRecordingController(media_root, command_factory)
    try:
        controller.start()
        controller.run_until_complete()
    except KeyboardInterrupt:
        controller.stop()
    except RecordingFailure:
        return 1
    return 0
