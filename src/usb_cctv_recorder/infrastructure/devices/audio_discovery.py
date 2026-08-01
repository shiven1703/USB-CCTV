"""Pulse/PipeWire-Pulse source discovery with source-name identities."""

from __future__ import annotations

import re

from usb_cctv_recorder.application.dto import AudioSource, DiscoveryError, DiscoveryErrorCode
from usb_cctv_recorder.infrastructure.commands.runner import CommandResult, StructuredCommandRunner

_SOURCE_HEADER = re.compile(r"^Source #\d+$")


def parse_pactl_short_sources(output: str) -> dict[str, str]:
    """Map source name to its advertised sample specification."""
    sources: dict[str, str] = {}
    for line in output.splitlines():
        fields = line.split("\t")
        if len(fields) >= 4:
            sources[fields[1]] = fields[3]
    return sources


def parse_pactl_source_details(output: str) -> dict[str, str]:
    """Map Pulse source names to their user-facing Description properties."""
    sources: dict[str, str] = {}
    current_name: str | None = None
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if _SOURCE_HEADER.match(line):
            current_name = None
            continue
        if line.startswith("Name: "):
            current_name = line.removeprefix("Name: ")
            continue
        if line.startswith("Description: ") and current_name is not None:
            sources[current_name] = line.removeprefix("Description: ")
    return sources


class PulseAudioSourceDiscovery:
    """Adapter for documented ``pactl list [short] sources`` commands."""

    def __init__(self, runner: StructuredCommandRunner) -> None:
        self._runner = runner

    def list_audio_devices(self) -> tuple[AudioSource, ...]:
        sources, _ = self.discover()
        return sources

    def discover(self) -> tuple[tuple[AudioSource, ...], DiscoveryError | None]:
        short = self._runner.run(("pactl", "list", "short", "sources"))
        details = self._runner.run(("pactl", "list", "sources"))
        if not short.succeeded or not details.succeeded:
            return (), _discovery_error(short if not short.succeeded else details)
        sample_specs = parse_pactl_short_sources(short.stdout)
        labels = parse_pactl_source_details(details.stdout)
        return (
            tuple(
                AudioSource(name, labels.get(name, name), sample_spec)
                for name, sample_spec in sample_specs.items()
            ),
            None,
        )


def _discovery_error(result: CommandResult) -> DiscoveryError:
    combined_output = f"{result.stdout}\n{result.stderr}\n{result.execution_error or ''}".lower()
    if "permission denied" in combined_output:
        return DiscoveryError(
            DiscoveryErrorCode.PERMISSION_DENIED, "Permission denied while listing microphones."
        )
    if result.execution_error is not None:
        return DiscoveryError(DiscoveryErrorCode.MISSING, "Cannot run the audio discovery tool.")
    return DiscoveryError(DiscoveryErrorCode.COMMAND_FAILED, "Unable to list microphones.")
