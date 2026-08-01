# Phase 6 Completion Report

## Delivered

- Worker-owned, runtime-only logind protection through locally verified `systemd-inhibit` argv:
  `sleep:idle` is blocked during recording; `handle-lid-switch` is added only when enabled; a
  separate shutdown-delay handle is held for bounded system-stop finalization.
- Validated private worker settings and Setup controls for suspend/hibernate protection (default on)
  and optional lid-close protection (default off).
- IPC power-protection, AC/battery, and battery-percentage fields shown by the existing Qt status
  reconnect. Qt does not own an inhibitor handle.
- `SIGTERM` now invokes the existing safe FFmpeg/ffprobe/checksum/manifest/event finalization path
  with the durable `shutdown_requested` reason, releases inhibitors, and exits 0 only when the
  outcome is known successful (otherwise 1). The unit gives this path 40 seconds.
- Read-only Linux power-supply status and a conservative critical-battery policy: at 5% or lower
  without AC, refuse a new recording or safely stop an active one.

## Files changed

- `src/usb_cctv_recorder/infrastructure/power/inhibitor.py`
- `src/usb_cctv_recorder/infrastructure/power/power_status.py`
- `src/usb_cctv_recorder/worker/main.py`, `supervisor.py`, and `recording.py`
- Application configuration, DTO, ports, IPC protocol, and private configuration storage
- Setup page and main-window worker-status display
- `systemd/usb-cctv-recorder-worker.service`, `README.md`, and ADR 0010
- Phase 5 regression tests and `tests/unit/test_phase_6_power.py`

## Architecture compliance

- Domain remains standard-library only. Application exposes power status and ports; infrastructure
  owns sysfs and `systemd-inhibit`; presentation only displays IPC status and writes validated
  preferences. FFmpeg remains worker-owned.

## Tests executed

- `systemd-inhibit --help` and local `man systemd-inhibit`
  - Result: verified `sleep`, `idle`, `handle-lid-switch`, `shutdown`, `block`, and `delay`
    semantics on systemd 255.
- `man systemd.service`
  - Result: verified `TimeoutStopSec=` stop semantics before setting the 40-second unit budget.
- `systemd-analyze verify systemd/usb-cctv-recorder-worker.service`
  - Result: syntax parsed; expected development-checkout warning that the package-only
    `/usr/bin/usb-cctv-recorder` executable is absent.
- `make ci`
  - Result: pass — Ruff format/lint, mypy, 127 automated tests at 90.20% coverage, synthetic
    integration/fault suites, package build/verification, and dependency audit.

## Acceptance criteria

- [x] Screen power-off does not stop recording — accepted by user without the manual target-desktop check.
- [x] KDE lock does not stop recording — accepted by user without the manual target-desktop check.
- [x] HDMI disconnection does not stop recording — accepted by user without the manual target-desktop check.
- [x] Configured idle timeout does not suspend the laptop while recording — accepted by user without the manual target-desktop check.
- [x] Active-file SIGTERM finalization follows the bounded safe-finalization path in automated tests.
- [x] Inhibitors release after normal safe stop, failure, inhibition loss, and shutdown finalization tests.

## Known limitations deferred by plan

- No device hotplug/watchdog recovery, degraded capture, storage governor, library/archive work,
  package-install lifecycle, or Phase 7 functionality was added.
- Manual target-desktop tests, including optional lid-close behavior only when enabled, were
  explicitly waived by the user for Phase 6 approval.

## Risks or decisions requiring user approval

- The source plan requests a critical-battery policy but does not state its threshold. The user
  approved the implemented 5% off-AC policy, documented in ADR 0010.
- `TimeoutStopSec=40s` bounds the service stop; a real shutdown test must confirm the target
  system's logind delay-inhibitor budget is sufficient for the final segment.

## Next phase

Phase 7 is ready to begin from the clean committed Phase 6 baseline.
