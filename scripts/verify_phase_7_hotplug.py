"""Guided physical webcam disconnect/reconnect acceptance for Phase 7."""

from __future__ import annotations

import argparse
import json
import time
import uuid
from dataclasses import asdict
from pathlib import Path

from usb_cctv_recorder.infrastructure.configuration import WorkerConfigurationStore, XdgPaths
from usb_cctv_recorder.infrastructure.ipc.client import UnixSocketClient
from usb_cctv_recorder.infrastructure.ipc.protocol import Command, Request, Response
from usb_cctv_recorder.infrastructure.storage.checksums import Sha256Service


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout-seconds", type=float, default=30)
    parser.add_argument("--report", type=Path, help="optional JSON acceptance report path")
    arguments = parser.parse_args()
    if arguments.timeout_seconds <= 0:
        raise ValueError("timeout must be positive")

    paths = XdgPaths.resolve()
    configuration = WorkerConfigurationStore(paths).load()
    if configuration is None:
        raise RuntimeError("configure the selected camera and microphone in the GUI first")
    client = UnixSocketClient(paths.runtime / "worker.sock")
    report: dict[str, object] = {"camera_identity": configuration.camera_identity}
    before_hashes: dict[str, str] = {}
    try:
        _wait_for_worker(client, arguments.timeout_seconds)
        started = _request(client, Command.START)
        _require(started.accepted, f"worker refused Start: {started.error_code}")
        report["started"] = asdict(started)
        av = _wait_for_healthy_av(client, arguments.timeout_seconds)
        report["before_disconnect"] = asdict(av)
        session_directory = _session_directory(configuration.media_root, av.session_id)
        before_hashes = _segment_hashes(session_directory)

        input("Unplug the selected webcam now, then press Enter… ")
        degraded = _wait_for(
            client,
            {"recovering", "recording_audio_only", "recording_video_only"},
            arguments.timeout_seconds,
        )
        report["after_disconnect"] = asdict(degraded)

        input("Reconnect the same webcam now, then press Enter… ")
        recovered = _wait_for_healthy_av(client, arguments.timeout_seconds)
        report["after_reconnect"] = asdict(recovered)
        _require(recovered.last_gap_seconds is not None, "worker did not report a completed gap")

        recovery = json.loads((session_directory / "recovery.json").read_text(encoding="utf-8"))
        events = [
            json.loads(line)["event_type"]
            for line in (session_directory / "events.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
            if line
        ]
        _require(recovery["gaps"], "recovery journal contains no gap")
        _require(
            "capture_gap_started" in events and "capture_gap_ended" in events, "gap events absent"
        )
        after_hashes = _segment_hashes(session_directory)
        _require(
            all(after_hashes.get(name) == digest for name, digest in before_hashes.items()),
            "a finalized segment changed",
        )
        report["recovery_journal"] = recovery
        report["completed_segment_hashes"] = before_hashes
        report["new_finalized_segments"] = sorted(set(after_hashes) - set(before_hashes))
        report["result"] = "pass"
    except Exception as error:
        report["result"] = "fail"
        report["error"] = str(error)
        raise
    finally:
        try:
            report["stop"] = asdict(_request(client, Command.STOP))
        except OSError as error:
            report["stop_error"] = str(error)
        print(json.dumps(report, indent=2, sort_keys=True))
        if arguments.report is not None:
            arguments.report.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            arguments.report.write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
    return 0


def _request(client: UnixSocketClient, command: Command) -> Response:
    return client.request(Request(command, str(uuid.uuid4())))


def _wait_for(client: UnixSocketClient, states: set[str], timeout_seconds: float) -> Response:
    deadline = time.monotonic() + timeout_seconds
    last: Response | None = None
    while time.monotonic() < deadline:
        last = _request(client, Command.STATUS)
        if last.state in states:
            return last
        time.sleep(0.5)
    detail = last.state if last is not None else "no response"
    raise RuntimeError(f"timed out waiting for {sorted(states)}; last state was {detail}")


def _wait_for_healthy_av(client: UnixSocketClient, timeout_seconds: float) -> Response:
    deadline = time.monotonic() + timeout_seconds
    last: Response | None = None
    while time.monotonic() < deadline:
        last = _request(client, Command.STATUS)
        if last.state == "recording_av" and {
            last.video_health,
            last.audio_health,
            last.output_health,
        } == {"healthy"}:
            return last
        time.sleep(0.5)
    detail = asdict(last) if last is not None else "no response"
    raise RuntimeError(f"timed out waiting for healthy AV capture; last status was {detail}")


def _wait_for_worker(client: UnixSocketClient, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            _request(client, Command.STATUS)
        except OSError:
            time.sleep(0.25)
            continue
        return
    raise RuntimeError("timed out waiting for the worker socket")


def _session_directory(media_root: Path, session_id: str | None) -> Path:
    if session_id is None:
        raise RuntimeError("worker did not return a session ID")
    for manifest in media_root.glob("originals/*/session-*/session.json"):
        data = json.loads(manifest.read_text(encoding="utf-8"))
        if data.get("session_id") == session_id:
            return manifest.parent
    raise RuntimeError("could not locate active session manifest")


def _segment_hashes(session_directory: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    checksums = Sha256Service()
    manifest = json.loads((session_directory / "session.json").read_text(encoding="utf-8"))
    for segment in manifest["segments"]:
        path = session_directory / segment["filename"]
        digest = checksums.digest_file(path)
        _require(digest == segment["sha256"], f"manifest checksum mismatch for {path.name}")
        hashes[path.name] = digest
    return hashes


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


if __name__ == "__main__":
    raise SystemExit(main())
