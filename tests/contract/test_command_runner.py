"""Contract tests for structured command execution."""

from __future__ import annotations

import subprocess

import pytest

from usb_cctv_recorder.infrastructure.commands.runner import StructuredCommandRunner


def test_runner_uses_argument_vector_and_explicitly_disables_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(arguments: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured["arguments"] = arguments
        captured.update(kwargs)
        return subprocess.CompletedProcess(arguments, 0, "output", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = StructuredCommandRunner().run(("ffmpeg", "-hide_banner", "-encoders"))

    assert result.succeeded
    assert captured["arguments"] == ("ffmpeg", "-hide_banner", "-encoders")
    assert captured["shell"] is False
    assert captured["capture_output"] is True


def test_runner_rejects_empty_or_non_string_arguments() -> None:
    runner = StructuredCommandRunner()
    with pytest.raises(ValueError):
        runner.run(())
    with pytest.raises(ValueError):
        runner.run(("pactl", ""))
