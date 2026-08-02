#!/usr/bin/env python3
"""Run the automatable Phase 11 lifecycle checks in a clean KDE VM.

Run this as the logged-in graphical user, not root. The script uses sudo only
for package-manager actions and deliberately leaves its test media behind so
uninstall/reinstall preservation can be inspected afterwards.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

PACKAGE_NAME = "usb-cctv-recorder"
UNIT_NAME = "usb-cctv-recorder-worker.service"
TEST_DIRECTORY_NAME = "USB-CCTV-Recorder-phase-11-clean-vm-test"


@dataclass(frozen=True, slots=True)
class Arguments:
    package: Path
    upgrade_package: Path | None
    media_root: Path


def parse_arguments(arguments: list[str] | None = None) -> Arguments:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path, help="initial .deb artifact")
    parser.add_argument(
        "--upgrade-package",
        type=Path,
        help="newer .deb artifact for the no-active-worker upgrade check",
    )
    parser.add_argument(
        "--media-root",
        type=Path,
        help=f"empty test media root (default: ~/Videos/{TEST_DIRECTORY_NAME})",
    )
    parsed = parser.parse_args(arguments)
    home = Path.home()
    media_root = parsed.media_root or home / "Videos" / TEST_DIRECTORY_NAME
    return Arguments(
        parsed.package.resolve(), _resolved_or_none(parsed.upgrade_package), media_root
    )


def main(arguments: list[str] | None = None) -> int:
    parsed = parse_arguments(arguments)
    _validate_environment(parsed)
    _install(parsed.package)
    initial_version = _installed_version()
    _verify_static_on_demand_worker()
    _verify_gui_launch_close_reopen()
    media_hashes = _create_and_verify_synthetic_media(parsed.media_root)
    sentinel = _write_retention_sentinel()
    final_package = parsed.package
    if parsed.upgrade_package is not None:
        _assert_newer(parsed.upgrade_package, initial_version)
        _assert_worker_inactive()
        _install(parsed.upgrade_package)
        final_package = parsed.upgrade_package
        _verify_preserved_state(parsed.media_root, media_hashes, sentinel)
        _rebuild_catalogue(parsed.media_root)
        _verify_gui_launch_close_reopen()
    else:
        print("SKIP upgrade check: pass --upgrade-package with a newer .deb to run it.")
    _assert_worker_inactive()
    _remove_package()
    _verify_preserved_state(parsed.media_root, media_hashes, sentinel)
    _install(final_package)
    _rebuild_catalogue(parsed.media_root)
    _verify_preserved_state(parsed.media_root, media_hashes, sentinel)
    _verify_gui_launch_close_reopen()
    print("PASS: automated clean-VM package lifecycle checks completed.")
    print("Manual KDE checks still required: menu visibility, real-device safe stop,")
    print("and archive through the Library/Archive UI. See docs/phase-11-clean-vm-checklist.md.")
    return 0


def _resolved_or_none(value: Path | None) -> Path | None:
    return value.resolve() if value is not None else None


def _validate_environment(arguments: Arguments) -> None:
    if os.geteuid() == 0:
        raise RuntimeError("run as the logged-in graphical user, not root")
    if not arguments.package.is_file():
        raise FileNotFoundError(arguments.package)
    if arguments.upgrade_package is not None and not arguments.upgrade_package.is_file():
        raise FileNotFoundError(arguments.upgrade_package)
    if arguments.media_root.exists():
        raise RuntimeError(f"test media root already exists: {arguments.media_root}")
    if os.environ.get("XDG_CURRENT_DESKTOP", "").lower().find("kde") == -1:
        raise RuntimeError("run from the supported KDE graphical session")
    if os.environ.get("XDG_SESSION_TYPE", "").lower() != "x11":
        raise RuntimeError("run from the supported X11 session")
    if not os.environ.get("XDG_RUNTIME_DIR") or not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        raise RuntimeError("the graphical user systemd/D-Bus session is unavailable")
    if _installed_version_or_none() is not None:
        raise RuntimeError(f"{PACKAGE_NAME} is already installed; start from a clean VM")


def _install(package: Path) -> None:
    _run_sudo(("apt-get", "install", "-y", str(package)))
    if _installed_version_or_none() is None:
        raise RuntimeError("package manager reported success but the package is not installed")


def _remove_package() -> None:
    _run_sudo(("apt-get", "remove", "-y", PACKAGE_NAME))
    if _installed_version_or_none() is not None:
        raise RuntimeError("package manager reported success but the package is still installed")


def _installed_version_or_none() -> str | None:
    result = _run(
        ("dpkg-query", "--showformat=${Version}", "--show", PACKAGE_NAME),
        check=False,
        capture_output=True,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _installed_version() -> str:
    version = _installed_version_or_none()
    if version is None:
        raise RuntimeError("package is not installed")
    return version


def _assert_newer(package: Path, installed_version: str) -> None:
    candidate = _run(
        ("dpkg-deb", "--field", str(package), "Version"), capture_output=True
    ).stdout.strip()
    comparison = _run(
        ("dpkg", "--compare-versions", candidate, "gt", installed_version), check=False
    )
    if comparison.returncode != 0:
        raise RuntimeError(
            f"upgrade package version {candidate!r} is not newer than {installed_version!r}"
        )


def _verify_static_on_demand_worker() -> None:
    _assert_worker_inactive()
    enabled = _run(
        ("systemctl", "--user", "is-enabled", UNIT_NAME),
        check=False,
        capture_output=True,
    ).stdout.strip()
    if enabled != "static":
        raise RuntimeError(f"worker must be static, got {enabled!r}")
    _run(("systemctl", "--user", "start", UNIT_NAME))
    _wait_for_worker(True)
    _wait_for_socket(_worker_socket())
    _run(("systemctl", "--user", "stop", UNIT_NAME))
    _wait_for_worker(False)


def _assert_worker_inactive() -> None:
    result = _run(("systemctl", "--user", "is-active", "--quiet", UNIT_NAME), check=False)
    if result.returncode == 0:
        raise RuntimeError("worker is active; safely stop recording before lifecycle testing")


def _wait_for_worker(active: bool) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        result = _run(("systemctl", "--user", "is-active", "--quiet", UNIT_NAME), check=False)
        if (result.returncode == 0) is active:
            return
        time.sleep(0.1)
    state = "active" if active else "inactive"
    raise RuntimeError(f"worker did not become {state}")


def _worker_socket() -> Path:
    return Path(os.environ["XDG_RUNTIME_DIR"]) / "usb-cctv-recorder" / "worker.sock"


def _wait_for_socket(socket: Path) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if socket.exists():
            return
        time.sleep(0.1)
    raise RuntimeError("on-demand worker did not create its private IPC socket")


def _verify_gui_launch_close_reopen() -> None:
    desktop = Path("/usr/share/applications") / f"{PACKAGE_NAME}.desktop"
    if not desktop.is_file():
        raise RuntimeError("installed KDE desktop entry is missing")
    _run(("desktop-file-validate", str(desktop)))
    for attempt in range(2):
        _launch_and_close_gui(attempt + 1)


def _launch_and_close_gui(attempt: int) -> None:
    process = subprocess.Popen(
        ("/usr/bin/usb-cctv-recorder",),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if process.poll() is None:
                time.sleep(1)
                if process.poll() is None:
                    return
            time.sleep(0.1)
        stderr = process.stderr.read() if process.stderr is not None else ""
        raise RuntimeError(f"GUI launch attempt {attempt} exited early: {stderr.strip()}")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def _create_and_verify_synthetic_media(media_root: Path) -> dict[Path, str]:
    _run(
        (
            "/usr/bin/usb-cctv-recorder",
            "--record",
            "--media-root",
            str(media_root),
            "--synthetic-duration-seconds",
            "1",
            "--segment-minutes",
            "1",
        )
    )
    media_hashes = _media_hashes(media_root)
    if not media_hashes:
        raise RuntimeError("frozen application did not create synthetic media")
    for media in media_hashes:
        _run(("ffprobe", "-v", "error", "-show_streams", str(media)))
    _rebuild_catalogue(media_root)
    return media_hashes


def _rebuild_catalogue(media_root: Path) -> None:
    _run(("/usr/bin/usb-cctv-recorder", "--rebuild-catalogue", "--media-root", str(media_root)))
    catalogue = _xdg_state_directory() / PACKAGE_NAME / "catalogue.sqlite"
    if not catalogue.is_file():
        raise RuntimeError("catalogue rebuild did not create the derived SQLite catalogue")


def _write_retention_sentinel() -> Path:
    directory = _xdg_config_directory() / PACKAGE_NAME
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.chmod(0o700)
    sentinel = directory / ".phase-11-clean-vm-sentinel"
    sentinel.write_text("package removal must preserve user configuration\n", encoding="utf-8")
    sentinel.chmod(0o600)
    return sentinel


def _verify_preserved_state(
    media_root: Path, expected_hashes: dict[Path, str], sentinel: Path
) -> None:
    if sentinel.read_text(encoding="utf-8") != "package removal must preserve user configuration\n":
        raise RuntimeError("package lifecycle did not preserve user configuration")
    if not (_xdg_state_directory() / PACKAGE_NAME / "catalogue.sqlite").is_file():
        raise RuntimeError("package lifecycle did not preserve the derived catalogue")
    if _media_hashes(media_root) != expected_hashes:
        raise RuntimeError("package lifecycle changed synthetic media bytes")


def _media_hashes(media_root: Path) -> dict[Path, str]:
    return {path: _sha256(path) for path in sorted(media_root.glob("originals/*/session-*/*.mkv"))}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _xdg_config_directory() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))


def _xdg_state_directory() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state"))


def _run_sudo(arguments: tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return _run(("sudo", "--", *arguments))


def _run(
    arguments: tuple[str, ...], *, check: bool = True, capture_output: bool = False
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        check=check,
        capture_output=capture_output,
        text=True,
        shell=False,
    )


if __name__ == "__main__":
    raise SystemExit(main())
