"""Command-line entrypoints for USB CCTV Recorder."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from .bootstrap import run_gui
from .worker.main import run_worker


def parse_args(arguments: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse the deliberately small public command-line surface."""
    parser = argparse.ArgumentParser(prog="usb-cctv-recorder")
    parser.add_argument("--worker", action="store_true", help="run the on-demand worker")
    return parser.parse_args(arguments)


def main(arguments: Sequence[str] | None = None) -> int:
    """Run either the GUI or worker process."""
    if parse_args(arguments).worker:
        return run_worker()
    return run_gui()


if __name__ == "__main__":
    raise SystemExit(main())
