"""Phase 11 packaging contracts that do not require a package build."""

from __future__ import annotations

import runpy
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[2]
PACKAGE_NAME = "usb-cctv-recorder"


def test_one_folder_spec_and_debian_metadata_keep_the_release_boundaries() -> None:
    spec = (PROJECT_ROOT / "packaging" / "pyinstaller" / "usb_cctv_recorder.spec").read_text()
    control = (PROJECT_ROOT / "packaging" / "debian" / "control.in").read_text()
    assert "COLLECT(" in spec
    assert "one-file" in spec
    assert "onefile" not in spec.lower().replace("one-folder", "")
    assert "Architecture: amd64" in control
    for dependency in ("ffmpeg", "pulseaudio-utils", "v4l-utils", "systemd"):
        assert dependency in control


def test_static_worker_unit_is_packaged_without_login_enablement() -> None:
    unit = (PROJECT_ROOT / "systemd" / f"{PACKAGE_NAME}-worker.service").read_text()
    postinst = (PROJECT_ROOT / "packaging" / "debian" / "postinst").read_text()
    assert "ExecStart=/usr/bin/usb-cctv-recorder --worker" in unit
    assert "[Install]" not in unit
    assert "systemctl --user daemon-reload" in postinst
    assert "systemctl --user enable" not in postinst


def test_desktop_entry_validates_and_uses_the_installed_launcher() -> None:
    desktop = PROJECT_ROOT / "packaging" / "debian" / f"{PACKAGE_NAME}.desktop"
    completed = subprocess.run(
        ("desktop-file-validate", str(desktop)),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    content = desktop.read_text()
    assert "TryExec=usb-cctv-recorder" in content
    assert "Exec=usb-cctv-recorder" in content
    assert "Icon=usb-cctv-recorder" in content


def test_uninstall_documentation_explicitly_preserves_user_data() -> None:
    documentation = (PROJECT_ROOT / "packaging" / "debian" / "README.Debian").read_text()
    assert "does not remove user data" in documentation
    assert "~/.config/usb-cctv-recorder/" in documentation
    assert "~/.local/state/usb-cctv-recorder/" in documentation
    assert "~/Videos/USB-CCTV-Recorder/" in documentation


def test_maintainer_scripts_are_valid_and_guard_active_worker_replacement() -> None:
    debian = PROJECT_ROOT / "packaging" / "debian"
    for script_name in ("postinst", "prerm"):
        completed = subprocess.run(
            ("sh", "-n", str(debian / script_name)),
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
    prerm = (debian / "prerm").read_text()
    assert "systemctl --user is-active --quiet usb-cctv-recorder-worker.service" in prerm
    assert "stop recording safely before" in prerm


def test_package_builder_can_write_a_higher_version_upgrade_artifact_separately() -> None:
    module = runpy.run_path(str(PROJECT_ROOT / "scripts" / "build_deb.py"))
    artifact_directory = PROJECT_ROOT / "dist" / "phase-11-upgrade"
    arguments = module["_parse_arguments"](
        ["--package-version", "0.1.1", "--artifact-directory", str(artifact_directory)]
    )
    assert arguments.package_version == "0.1.1"
    assert arguments.artifact_directory == artifact_directory
