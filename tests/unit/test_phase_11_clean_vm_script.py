"""Pure contracts for the clean-VM lifecycle harness."""

from __future__ import annotations

import runpy
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / "scripts" / "verify_clean_vm_lifecycle.py"


def test_clean_vm_script_parses_absolute_package_paths_and_optional_upgrade(tmp_path: Path) -> None:
    module = runpy.run_path(str(SCRIPT))
    package = tmp_path / "usb-cctv-recorder_0.1.0_amd64.deb"
    upgrade = tmp_path / "usb-cctv-recorder_0.1.1_amd64.deb"
    arguments = module["parse_arguments"](
        [str(package), "--upgrade-package", str(upgrade), "--media-root", str(tmp_path / "media")]
    )
    assert arguments.package == package
    assert arguments.upgrade_package == upgrade
    assert arguments.media_root == tmp_path / "media"


def test_clean_vm_script_uses_only_structured_package_and_user_service_commands() -> None:
    content = SCRIPT.read_text()
    assert '"apt-get", "install", "-y"' in content
    assert '"apt-get", "remove", "-y"' in content
    assert '"systemctl", "--user", "start"' in content
    assert '"systemctl", "--user", "stop"' in content
    assert "def _wait_for_socket" in content
    assert "def _verify_gui_launch_close_reopen" in content
    assert '("/usr/bin/usb-cctv-recorder",)' in content
    assert "shell=False" in content
    assert "shell=True" not in content


def test_clean_vm_script_captures_package_query_output() -> None:
    module = runpy.run_path(str(SCRIPT))
    calls: list[dict[str, object]] = []

    def run(arguments: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(kwargs)
        return subprocess.CompletedProcess(arguments, 0, stdout="0.1.0\n")

    module["_installed_version_or_none"].__globals__["_run"] = run

    assert module["_installed_version_or_none"]() == "0.1.0"
    assert calls == [{"check": False, "capture_output": True}]
