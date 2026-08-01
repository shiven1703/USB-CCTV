"""Command-line entrypoints for USB CCTV Recorder."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from .bootstrap import run_gui
from .worker.main import run_worker


def parse_args(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the deliberately small public command-line surface."""
    parser = argparse.ArgumentParser(prog="usb-cctv-recorder")
    parser.add_argument("--worker", action="store_true", help="run the on-demand worker")
    parser.add_argument(
        "--record", action="store_true", help="run one foreground development recording"
    )
    parser.add_argument("--media-root", type=Path, help="absolute media root for --record")
    parser.add_argument("--camera", help="persistent /dev/v4l/by-id camera identity for --record")
    parser.add_argument("--microphone", help="explicit Pulse source name for --record")
    parser.add_argument("--segment-minutes", type=int, default=60, help="segment duration (1-360)")
    parser.add_argument("--output-frame-rate", type=float, default=15, choices=(12, 15))
    parser.add_argument(
        "--synthetic-duration-seconds",
        type=float,
        help="CI/development-only lavfi recording duration; does not use camera hardware",
    )
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    """Run either the GUI or worker process."""
    parsed = parse_args(arguments)
    if parsed.record:
        if parsed.media_root is None:
            raise ValueError("--media-root is required with --record")
        if not 1 <= parsed.segment_minutes <= 360:
            raise ValueError("--segment-minutes must be between 1 and 360")
        return run_worker(
            media_root=parsed.media_root,
            camera_identity=parsed.camera,
            microphone_source=parsed.microphone,
            output_frame_rate=parsed.output_frame_rate,
            segment_minutes=parsed.segment_minutes,
            synthetic_duration_seconds=parsed.synthetic_duration_seconds,
        )
    if parsed.worker:
        return run_worker()
    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
