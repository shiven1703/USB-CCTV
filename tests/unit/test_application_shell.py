"""Phase 1 tests for the launchable application shell."""

from __future__ import annotations

import importlib
import pkgutil
import subprocess
import sys
from pathlib import Path

import pytest

import usb_cctv_recorder
from usb_cctv_recorder import __main__, bootstrap
from usb_cctv_recorder.presentation.qt import app
from usb_cctv_recorder.presentation.qt.main_window import MainWindow


def test_all_application_packages_import() -> None:
    package_root = Path(usb_cctv_recorder.__file__).parent
    package_names = [
        module.name for module in pkgutil.walk_packages([str(package_root)], "usb_cctv_recorder.")
    ]

    for package_name in package_names:
        importlib.import_module(package_name)


def test_main_window_opens_and_closes(qtbot: pytest.QtBot) -> None:
    window = MainWindow()
    qtbot.addWidget(window)
    window.show()

    assert window.isVisible()
    assert window.windowTitle() == "USB CCTV Recorder"

    window.close()
    assert not window.isVisible()


def test_normal_cli_mode_starts_gui(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(__main__, "run_gui", lambda: 0)

    assert __main__.main([]) == 0


def test_bootstrap_starts_presentation_application(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bootstrap, "run_application", lambda: 0)

    assert bootstrap.run_gui() == 0


def test_qt_application_starts_window(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeApplication:
        @staticmethod
        def instance() -> None:
            return None

        def __init__(self, arguments: list[str]) -> None:
            self.arguments = arguments

        def exec(self) -> int:
            return 0

    class FakeWindow:
        def show(self) -> None:
            pass

    monkeypatch.setattr(app, "QApplication", FakeApplication)
    monkeypatch.setattr(app, "MainWindow", FakeWindow)

    assert app.run_application() == 0


def test_worker_cli_mode_exits_cleanly() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "usb_cctv_recorder", "--worker"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
