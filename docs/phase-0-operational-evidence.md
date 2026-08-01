# Phase 0 operational evidence

Captured from the logged-in user session on 2026-08-01. These checks create no persistent service or configuration.

| Check | Result |
| --- | --- |
| `uv --version` | PASS — `uv 0.12.1` |
| `systemctl --user --failed --no-legend --plain` | One failed unit: `app-nvidia-settings-autostart@autostart.service`. It is an NVIDIA settings autostart unit and is irrelevant to the recorder, PipeWire, D-Bus, and transient user services. |
| `systemd-run --user --wait --collect /usr/bin/true` | PASS — transient `run-u192.service` completed successfully. |
| Temporary inhibitor | PASS — a `sleep:idle` block inhibitor named `USB CCTV Recorder Phase 0` appeared in `systemd-inhibit --list` and was released after the 20-second test. |

The real environment report is refreshed at `.local/probes/environment-probe.json`; `.local/` is Git-ignored. It must remain local because it contains machine-specific paths and identifiers.
