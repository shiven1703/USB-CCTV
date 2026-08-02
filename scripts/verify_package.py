#!/usr/bin/env python3
"""Exercise a built .deb as an ordinary user without the development environment."""

from __future__ import annotations

import argparse
import os
import stat
import subprocess
import tempfile
from pathlib import Path

PACKAGE_NAME = "usb-cctv-recorder"
REQUIRED_DEPENDENCIES = ("ffmpeg", "pulseaudio-utils", "v4l-utils", "systemd")
REQUIRED_PATHS = (
    f"./usr/bin/{PACKAGE_NAME}",
    f"./usr/lib/{PACKAGE_NAME}/{PACKAGE_NAME}",
    f"./usr/lib/systemd/user/{PACKAGE_NAME}-worker.service",
    f"./usr/share/applications/{PACKAGE_NAME}.desktop",
    f"./usr/share/icons/hicolor/256x256/apps/{PACKAGE_NAME}.png",
    f"./usr/share/icons/hicolor/scalable/apps/{PACKAGE_NAME}.svg",
)
REQUIRED_UNIT_LINES = (
    "Type=exec",
    "ExecStart=/usr/bin/usb-cctv-recorder --worker",
    "Restart=on-failure",
    "RuntimeDirectory=usb-cctv-recorder",
    "UMask=0077",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("artifact", type=Path)
    arguments = parser.parse_args()
    artifact = arguments.artifact.resolve()
    if not artifact.is_file():
        raise FileNotFoundError(artifact)
    _verify_metadata(artifact)
    with tempfile.TemporaryDirectory(prefix="usb-cctv-recorder-package-") as temporary:
        root = Path(temporary)
        extraction = root / "package"
        _run(("dpkg-deb", "--extract", str(artifact), str(extraction)))
        _verify_layout(artifact, extraction)
        _exercise_frozen_runtime(extraction, root)
    print(f"verified {artifact}")
    return 0


def _verify_metadata(artifact: Path) -> None:
    control = _run(
        ("dpkg-deb", "--field", str(artifact), "Package", "Architecture", "Depends"),
        capture_output=True,
    ).stdout
    if f"Package: {PACKAGE_NAME}" not in control or "Architecture: amd64" not in control:
        raise RuntimeError("package identity or architecture is incorrect")
    if any(dependency not in control for dependency in REQUIRED_DEPENDENCIES):
        raise RuntimeError(f"missing runtime dependency declaration: {control}")


def _verify_layout(artifact: Path, extraction: Path) -> None:
    contents = _run(("dpkg-deb", "--contents", str(artifact)), capture_output=True).stdout
    if any(path not in contents for path in REQUIRED_PATHS):
        raise RuntimeError("package is missing a required installed path")
    if "Videos/" in contents or "originals/" in contents or "archives/" in contents:
        raise RuntimeError("package must not include user recordings")
    desktop = extraction / "usr" / "share" / "applications" / f"{PACKAGE_NAME}.desktop"
    _run(("desktop-file-validate", str(desktop)))
    unit = extraction / "usr" / "lib" / "systemd" / "user" / f"{PACKAGE_NAME}-worker.service"
    unit_content = unit.read_text(encoding="utf-8")
    if any(line not in unit_content for line in REQUIRED_UNIT_LINES) or "[Install]" in unit_content:
        raise RuntimeError("packaged worker unit is not the required static on-demand service")
    for size in (16, 24, 32, 48, 64, 128, 256, 512):
        icon = (
            extraction
            / "usr"
            / "share"
            / "icons"
            / "hicolor"
            / f"{size}x{size}"
            / "apps"
            / f"{PACKAGE_NAME}.png"
        )
        if icon.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            raise RuntimeError(f"invalid {size}px PNG icon")
        if stat.S_IMODE(icon.stat().st_mode) != 0o644:
            raise RuntimeError(f"{size}px PNG icon permissions are not 0644")


def _exercise_frozen_runtime(extraction: Path, root: Path) -> None:
    home = root / "home"
    runtime = root / "runtime"
    media = root / "media"
    for directory in (home, runtime, media):
        directory.mkdir(mode=0o700)
    environment = {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / "config"),
        "XDG_STATE_HOME": str(home / "state"),
        "XDG_CACHE_HOME": str(home / "cache"),
        "XDG_RUNTIME_DIR": str(runtime),
        "PATH": os.environ["PATH"],
    }
    executable = extraction / "usr" / "bin" / PACKAGE_NAME
    _run((str(executable), "--help"), environment=environment)
    _run(
        (
            str(executable),
            "--record",
            "--media-root",
            str(media),
            "--synthetic-duration-seconds",
            "1",
            "--segment-minutes",
            "1",
        ),
        environment=environment,
    )
    segment = next(media.glob("originals/*/session-*/segment-*.mkv"), None)
    if segment is None:
        raise RuntimeError("frozen runtime did not create a synthetic recording")
    _run(("ffprobe", "-v", "error", "-show_streams", str(segment)), environment=environment)
    _run(
        (str(executable), "--rebuild-catalogue", "--media-root", str(media)),
        environment=environment,
    )


def _run(
    arguments: tuple[str, ...],
    *,
    capture_output: bool = False,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        check=True,
        capture_output=capture_output,
        text=True,
        env=environment,
        shell=False,
    )


if __name__ == "__main__":
    raise SystemExit(main())
