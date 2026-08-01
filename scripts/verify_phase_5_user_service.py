"""Manual acceptance probe for the installed Phase 5 systemd user worker."""

from __future__ import annotations

import argparse
import time
import uuid

from usb_cctv_recorder.infrastructure.commands.runner import StructuredCommandRunner
from usb_cctv_recorder.infrastructure.configuration import XdgPaths
from usb_cctv_recorder.infrastructure.ipc.client import UnixSocketClient
from usb_cctv_recorder.infrastructure.ipc.protocol import Command, Request
from usb_cctv_recorder.infrastructure.systemd.user_service import UNIT_NAME


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--crash-test",
        action="store_true",
        help="kill an idle installed worker and verify systemd restarts it",
    )
    parser.add_argument(
        "--command",
        choices=[command.value for command in Command],
        default="status",
        help="send one closed protocol command after starting the installed service",
    )
    parser.add_argument("--unit", default=UNIT_NAME, help="systemd user unit to verify")
    arguments = parser.parse_args()
    runner = StructuredCommandRunner()
    started = runner.run(("systemctl", "--user", "start", arguments.unit))
    if not started.succeeded:
        raise RuntimeError(started.stderr or started.execution_error or "could not start worker")
    client = UnixSocketClient(XdgPaths.resolve().runtime / "worker.sock")
    command = Command(arguments.command)
    status = client.request(Request(command, str(uuid.uuid4())))
    print(
        f"worker response: command={command.value} state={status.state} accepted={status.accepted}"
    )
    if not arguments.crash_test:
        return 0
    if status.state not in {"idle", "completed", "failed"}:
        raise RuntimeError("refusing crash test while a recording is active")
    before = _property(runner, arguments.unit, "NRestarts")
    result = runner.run(("systemctl", "--user", "kill", "--signal=SIGKILL", arguments.unit))
    if not result.succeeded:
        raise RuntimeError(result.stderr or result.execution_error or "could not kill worker")
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            status = client.request(Request(Command.STATUS, str(uuid.uuid4())))
        except OSError:
            time.sleep(0.25)
            continue
        after = _property(runner, arguments.unit, "NRestarts")
        if after > before:
            print(f"crash recovery passed: status={status.state}, restarts={before}->{after}")
            return 0
        time.sleep(0.25)
    raise RuntimeError("worker did not restart within 15 seconds")


def _property(runner: StructuredCommandRunner, unit: str, name: str) -> int:
    result = runner.run(("systemctl", "--user", "show", unit, f"--property={name}", "--value"))
    if not result.succeeded:
        raise RuntimeError(result.stderr or result.execution_error or f"could not read {name}")
    return int(result.stdout.strip())


if __name__ == "__main__":
    raise SystemExit(main())
