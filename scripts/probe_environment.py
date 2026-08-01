#!/usr/bin/env python3
"""Collect a read-only environment report for USB CCTV Recorder Phase 0."""

from __future__ import annotations

import argparse
import glob
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Sequence


PROBE_SCHEMA_VERSION = 1
COMMAND_TIMEOUT_SECONDS = 10


def parse_key_value_lines(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            values[key] = value.strip().strip('"')
    return values


def parse_version(output: str) -> str | None:
    for line in output.splitlines():
        if line.strip():
            return line.strip()
    return None


def parse_pactl_info(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in output.splitlines():
        if ": " not in line:
            continue
        key, value = line.split(": ", 1)
        values[key.strip()] = value.strip()
    return values


def parse_pactl_sources(output: str) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    for line in output.splitlines():
        fields = line.split("\t")
        if len(fields) < 2:
            continue
        source: dict[str, str] = {"index": fields[0], "name": fields[1]}
        if len(fields) > 1:
            source["driver"] = fields[2] if len(fields) > 2 else ""
        if len(fields) > 3:
            source["sample_spec"] = fields[3]
        if len(fields) > 4:
            source["state"] = fields[4]
        sources.append(source)
    return sources


def select_audio_source(sources: list[dict[str, str]], source_name: str) -> dict[str, str] | None:
    return next((source for source in sources if source["name"] == source_name), None)


def parse_v4l2_devices(output: str) -> list[dict[str, Any]]:
    devices: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("/dev/video"):
            if current is not None:
                current["paths"].append(line)
            continue
        if raw_line and not raw_line[0].isspace() and line.endswith(":"):
            current = {"name": line[:-1], "paths": []}
            devices.append(current)
    return [device for device in devices if device["paths"]]


def parse_v4l2_formats(output: str) -> list[dict[str, Any]]:
    formats: list[dict[str, Any]] = []
    current_format: dict[str, Any] | None = None
    current_size: dict[str, Any] | None = None
    for raw_line in output.splitlines():
        line = raw_line.strip()
        format_match = re.match(r"\[\d+\]: '([^']+)' \((.+)\)", line)
        if format_match:
            current_format = {
                "pixel_format": format_match.group(1),
                "description": format_match.group(2),
                "sizes": [],
            }
            formats.append(current_format)
            current_size = None
            continue
        size_match = re.match(r"Size: Discrete (\d+x\d+)", line)
        if size_match and current_format is not None:
            current_size = {"resolution": size_match.group(1), "frame_rates": []}
            current_format["sizes"].append(current_size)
            continue
        interval_match = re.search(r"\(([0-9.]+) fps\)", line)
        if interval_match and current_size is not None:
            current_size["frame_rates"].append(float(interval_match.group(1)))
    return formats


def parse_encoder_candidates(output: str) -> list[str]:
    candidates: list[str] = []
    for line in output.splitlines():
        match = re.match(r"\s*V\S*\s+(\S+)", line)
        if match is None:
            continue
        encoder = match.group(1)
        if (
            ("h264" in encoder or "hevc" in encoder)
            and any(token in encoder for token in ("nvenc", "qsv", "vaapi", "v4l2m2m", "amf"))
        ):
            candidates.append(encoder)
    return candidates


def parse_power_supplies(supply_root: Path) -> list[dict[str, str]]:
    supplies: list[dict[str, str]] = []
    for supply_path in sorted(supply_root.glob("*")):
        if not supply_path.is_dir():
            continue
        entry = {"name": supply_path.name}
        for field in ("type", "online", "status", "capacity"):
            value_path = supply_path / field
            if value_path.is_file():
                entry[field] = value_path.read_text(encoding="utf-8").strip()
        supplies.append(entry)
    return supplies


def command_result(arguments: Sequence[str]) -> dict[str, Any]:
    executable = shutil.which(arguments[0])
    if executable is None:
        return {"status": "missing", "argv": list(arguments)}
    try:
        completed = subprocess.run(
            list(arguments),
            check=False,
            capture_output=True,
            text=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        return {
            "status": "timed_out",
            "argv": list(arguments),
            "stdout": error.stdout or "",
            "stderr": error.stderr or "",
        }
    except OSError as error:
        return {
            "status": "error",
            "argv": list(arguments),
            "error": f"{type(error).__name__}: {error}",
        }
    return {
        "status": "ok" if completed.returncode == 0 else "failed",
        "argv": list(arguments),
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def stable_aliases(device_path: str) -> list[str]:
    aliases: list[str] = []
    resolved_device = os.path.realpath(device_path)
    for alias_pattern in ("/dev/v4l/by-id/*", "/dev/v4l/by-path/*"):
        for alias in glob.glob(alias_pattern):
            if os.path.realpath(alias) == resolved_device:
                aliases.append(alias)
    return sorted(aliases)


def filesystem_type(path: Path) -> str | None:
    mounts = read_text(Path("/proc/mounts"))
    if mounts is None:
        return None
    resolved_path = str(path.resolve())
    matching_mounts: list[tuple[str, str]] = []
    for line in mounts.splitlines():
        fields = line.split()
        if len(fields) < 3:
            continue
        mount_path = fields[1].replace("\\040", " ")
        if resolved_path == mount_path or resolved_path.startswith(mount_path.rstrip("/") + "/"):
            matching_mounts.append((mount_path, fields[2]))
    return max(matching_mounts, key=lambda entry: len(entry[0]))[1] if matching_mounts else None


def find_video_device_by_alias(devices: list[dict[str, Any]], alias: str) -> dict[str, Any] | None:
    return next((device for device in devices if alias in device["persistent_aliases"]), None)


def classify_video_node(formats: list[dict[str, Any]]) -> str:
    return "capture" if formats else "metadata_or_unusable"


def write_report(output_path: Path, report: str) -> None:
    if not output_path.parent.is_dir():
        raise ValueError(f"output directory does not exist: {output_path.parent}")
    output_path.write_text(report, encoding="utf-8")


def probe() -> dict[str, Any]:
    os_release = parse_key_value_lines(read_text(Path("/etc/os-release")) or "")
    command_results = {
        "plasmashell": command_result(["plasmashell", "--version"]),
        "systemd": command_result(["systemctl", "--version"]),
        "ffmpeg": command_result(["ffmpeg", "-version"]),
        "ffprobe": command_result(["ffprobe", "-version"]),
        "pactl_info": command_result(["pactl", "info"]),
        "pactl_sources": command_result(["pactl", "list", "short", "sources"]),
        "v4l2_devices": command_result(["v4l2-ctl", "--list-devices"]),
        "ffmpeg_encoders": command_result(["ffmpeg", "-hide_banner", "-encoders"]),
        "uv": command_result(["uv", "--version"]),
        "user_manager_state": command_result(["systemctl", "--user", "is-system-running"]),
        "user_manager_failed_units": command_result(
            ["systemctl", "--user", "--failed", "--no-legend", "--plain"]
        ),
        "inhibitors": command_result(["systemd-inhibit", "--list", "--no-legend"]),
    }
    video_paths = sorted(glob.glob("/dev/video*"))
    video_devices = []
    for path in video_paths:
        formats = parse_v4l2_formats(
            command_result(["v4l2-ctl", "--device", path, "--list-formats-ext"]).get("stdout", "")
        )
        video_devices.append(
            {
            "path": path,
            "persistent_aliases": stable_aliases(path),
            "node_kind": classify_video_node(formats),
            "formats": formats,
            }
        )
    default_media_directory = Path.home() / "Videos" / "USB-CCTV-Recorder"
    filesystem_root = default_media_directory
    while not filesystem_root.exists() and filesystem_root.parent != filesystem_root:
        filesystem_root = filesystem_root.parent
    filesystem = os.statvfs(filesystem_root)
    logind_files = [Path("/etc/systemd/logind.conf"), *map(Path, glob.glob("/etc/systemd/logind.conf.d/*.conf"))]
    return {
        "schema_version": PROBE_SCHEMA_VERSION,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "host": {
            "architecture": platform.machine(),
            "python_version": platform.python_version(),
            "session_type": os.environ.get("XDG_SESSION_TYPE"),
            "os_release": os_release,
        },
        "versions": {
            name: parse_version(result.get("stdout", ""))
            for name, result in command_results.items()
            if name in {"plasmashell", "systemd", "ffmpeg", "ffprobe", "uv"}
        },
        "audio": {
            "server": parse_pactl_info(command_results["pactl_info"].get("stdout", "")),
            "sources": parse_pactl_sources(command_results["pactl_sources"].get("stdout", "")),
        },
        "video": {
            "listed_devices": parse_v4l2_devices(command_results["v4l2_devices"].get("stdout", "")),
            "devices": video_devices,
        },
        "hardware_encoder_candidates": parse_encoder_candidates(
            command_results["ffmpeg_encoders"].get("stdout", "")
        ),
        "power_supplies": parse_power_supplies(Path("/sys/class/power_supply")),
        "logind_configured_values": {
            path.name: parse_key_value_lines(read_text(path) or "") for path in logind_files if path.is_file()
        },
        "default_media_filesystem": {
            "requested_path": str(default_media_directory),
            "inspected_existing_path": str(filesystem_root),
            "filesystem_type": filesystem_type(filesystem_root),
            "available_bytes": filesystem.f_bavail * filesystem.f_frsize,
        },
        "commands": command_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="Write JSON only to this existing directory.")
    arguments = parser.parse_args()
    report = json.dumps(probe(), indent=2, sort_keys=True) + "\n"
    if arguments.output is None:
        print(report, end="")
        return 0
    try:
        write_report(arguments.output, report)
    except ValueError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
