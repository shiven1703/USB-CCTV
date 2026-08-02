#!/usr/bin/env python3
"""Build the supported amd64 PyInstaller one-folder Debian artifact."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_DIRECTORY = PROJECT_ROOT / "dist"
PYINSTALLER_DIST = DIST_DIRECTORY / "pyinstaller"
BUILD_DIRECTORY = PROJECT_ROOT / "build" / "phase-11-debian"
PACKAGE_NAME = "usb-cctv-recorder"
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256, 512)


def main(arguments: list[str] | None = None) -> int:
    parsed = _parse_arguments(arguments)
    version = parsed.package_version or _project_version()
    _reset_build_directories()
    bundle = _build_one_folder_bundle()
    stage = BUILD_DIRECTORY / "stage"
    _populate_stage(stage, bundle, version)
    shlibs_depends = _shared_library_dependencies(stage)
    _write_control(stage, version, shlibs_depends)
    artifact_directory = parsed.artifact_directory.resolve()
    artifact_directory.mkdir(parents=True, exist_ok=True)
    artifact = artifact_directory / f"{PACKAGE_NAME}_{version}_amd64.deb"
    artifact.unlink(missing_ok=True)
    _run(("dpkg-deb", "--root-owner-group", "--build", str(stage), str(artifact)))
    print(artifact)
    return 0


def _parse_arguments(arguments: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--package-version",
        help="override only the Debian package version (for clean-VM upgrade acceptance)",
    )
    parser.add_argument(
        "--artifact-directory",
        type=Path,
        default=DIST_DIRECTORY,
        help="directory for the generated .deb (default: dist/)",
    )
    return parser.parse_args(arguments)


def _project_version() -> str:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as source:
        project = tomllib.load(source)["project"]
    version = project["version"]
    if not isinstance(version, str):
        raise ValueError("project version must be a string")
    return version


def _reset_build_directories() -> None:
    for directory in (PYINSTALLER_DIST, BUILD_DIRECTORY):
        if directory.exists():
            shutil.rmtree(directory)
    DIST_DIRECTORY.mkdir(exist_ok=True)


def _build_one_folder_bundle() -> Path:
    _run(
        (
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--log-level",
            "WARN",
            "--distpath",
            str(PYINSTALLER_DIST),
            "--workpath",
            str(BUILD_DIRECTORY / "pyinstaller-work"),
            str(PROJECT_ROOT / "packaging" / "pyinstaller" / "usb_cctv_recorder.spec"),
        )
    )
    bundle = PYINSTALLER_DIST / PACKAGE_NAME
    if not (bundle / PACKAGE_NAME).is_file():
        raise RuntimeError("PyInstaller did not create the expected one-folder executable")
    return bundle


def _populate_stage(stage: Path, bundle: Path, version: str) -> None:
    if stage.exists():
        shutil.rmtree(stage)
    application_directory = stage / "usr" / "lib" / PACKAGE_NAME
    shutil.copytree(bundle, application_directory)
    _write_launcher(stage / "usr" / "bin" / PACKAGE_NAME)
    _copy_file(
        PROJECT_ROOT / "systemd" / f"{PACKAGE_NAME}-worker.service",
        stage / "usr" / "lib" / "systemd" / "user" / f"{PACKAGE_NAME}-worker.service",
        mode=0o644,
    )
    _copy_file(
        PROJECT_ROOT / "packaging" / "debian" / f"{PACKAGE_NAME}.desktop",
        stage / "usr" / "share" / "applications" / f"{PACKAGE_NAME}.desktop",
        mode=0o644,
    )
    _write_icon_assets(stage)
    _copy_file(
        PROJECT_ROOT / "packaging" / "debian" / "README.Debian",
        stage / "usr" / "share" / "doc" / PACKAGE_NAME / "README.Debian",
        mode=0o644,
    )
    _copy_file(
        PROJECT_ROOT / "LICENSE",
        stage / "usr" / "share" / "doc" / PACKAGE_NAME / "copyright",
        mode=0o644,
    )
    control_directory = stage / "DEBIAN"
    control_directory.mkdir(parents=True, exist_ok=True)
    for script_name in ("postinst", "prerm"):
        _copy_file(
            PROJECT_ROOT / "packaging" / "debian" / script_name,
            control_directory / script_name,
            mode=0o755,
        )
    _write_control(stage, version, "libc6")


def _write_launcher(destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        'launcher_directory=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
        'exec "$launcher_directory/../lib/usb-cctv-recorder/usb-cctv-recorder" "$@"\n',
        encoding="utf-8",
    )
    destination.chmod(0o755)


def _write_icon_assets(stage: Path) -> None:
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QColor, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    source = PROJECT_ROOT / "assets" / f"{PACKAGE_NAME}.svg"
    renderer = QSvgRenderer(str(source))
    if not renderer.isValid():
        raise RuntimeError("application SVG icon is invalid")
    scalable = stage / "usr" / "share" / "icons" / "hicolor" / "scalable" / "apps"
    _copy_file(source, scalable / source.name, mode=0o644)
    for size in ICON_SIZES:
        image = QImage(QSize(size, size), QImage.Format.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0))
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        destination = (
            stage
            / "usr"
            / "share"
            / "icons"
            / "hicolor"
            / f"{size}x{size}"
            / "apps"
            / f"{PACKAGE_NAME}.png"
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not image.save(str(destination), "PNG"):
            raise RuntimeError(f"could not create {size}px icon")
        destination.chmod(0o644)


def _copy_file(source: Path, destination: Path, *, mode: int) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    destination.chmod(mode)


def _shared_library_dependencies(stage: Path) -> str:
    # PyInstaller owns the private libraries below _internal. Ask dpkg-shlibdeps
    # only about the bootloader executable, whose non-bundled ELF requirements
    # are the package's actual shared-library dependencies.
    executable = stage / "usr" / "lib" / PACKAGE_NAME / PACKAGE_NAME
    if not executable.is_file() or not _is_elf(executable):
        raise RuntimeError("the frozen bundle contains no executable ELF bootloader")
    source_control = BUILD_DIRECTORY / "debian" / "control"
    source_control.parent.mkdir(parents=True, exist_ok=True)
    source_control.write_text(
        "Source: usb-cctv-recorder\n"
        "Section: video\n"
        "Priority: optional\n"
        "Maintainer: USB CCTV Recorder contributors\n"
        "Standards-Version: 4.7.0\n\n"
        "Package: usb-cctv-recorder\n"
        "Architecture: amd64\n"
        "Description: local USB camera recorder\n",
        encoding="utf-8",
    )
    result = _run(
        (
            "dpkg-shlibdeps",
            "-O",
            f"-S{stage}",
            f"-l{stage / 'usr' / 'lib' / PACKAGE_NAME / '_internal'}",
            f"-e{executable}",
        ),
        capture_output=True,
        working_directory=BUILD_DIRECTORY,
    )
    for line in result.stdout.splitlines():
        if line.startswith("shlibs:Depends="):
            dependencies = line.removeprefix("shlibs:Depends=").strip()
            if dependencies:
                return dependencies
    raise RuntimeError(f"dpkg-shlibdeps did not produce shlibs:Depends: {result.stderr}")


def _is_elf(path: Path) -> bool:
    with path.open("rb") as source:
        return source.read(4) == b"\x7fELF"


def _write_control(stage: Path, version: str, shlibs_depends: str) -> None:
    template = (PROJECT_ROOT / "packaging" / "debian" / "control.in").read_text(encoding="utf-8")
    control = template.format(version=version, shlibs_depends=shlibs_depends)
    destination = stage / "DEBIAN" / "control"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(control, encoding="utf-8")
    destination.chmod(0o644)


def _run(
    arguments: tuple[str, ...],
    *,
    capture_output: bool = False,
    working_directory: Path = PROJECT_ROOT,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        arguments,
        check=False,
        capture_output=capture_output,
        text=True,
        cwd=working_directory,
        shell=False,
    )
    if result.returncode:
        detail = result.stderr.strip() if capture_output else ""
        raise RuntimeError(f"command failed ({result.returncode}): {' '.join(arguments)} {detail}")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
