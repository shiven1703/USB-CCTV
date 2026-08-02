# Phase 7 Completion Report

## Delivered

- A `udevadm monitor --udev --property --subsystem-match=video4linux` adapter, verified locally
  against `udevadm monitor --help`, which re-resolves only the configured `/dev/v4l/by-id` alias.
  It never chooses a transient node or replacement camera.
- Monotonic 5-second warning and 15-second stalled thresholds for FFmpeg video-frame progress,
  encoded-audio timestamp progress, and current-output byte growth; worker heartbeat status.
- Durable `recovery.json` facts and append-only gap events, including wall times, monotonic gap
  duration, attempt count, retry deadline, reason, and last-good audio/video monotonic timestamps.
- Bounded 2/5/10/30/60-second recovery, safe active-segment interruption, distinct recovery file
  families, interrupted verification, and quarantine without deletion on failed verification.
  Audio-only capture promotes back to a fresh AV segment when the selected camera returns.
- Explicit audio-only and video-only FFmpeg pipelines with no synthesized counterpart stream.
- Validated IPC health/recovery fields and a Qt `Retry now` control; Qt remains a status/control
  client and does not own FFmpeg or evidence files.

## Files changed

- `src/usb_cctv_recorder/infrastructure/devices/hotplug.py`
- `src/usb_cctv_recorder/infrastructure/persistence/recovery_journal.py`
- `src/usb_cctv_recorder/worker/watchdog.py`, `recording.py`, `supervisor.py`, and `main.py`
- FFmpeg command builder, IPC protocol, Qt main window, README, and Phase 5 regression tests
- `tests/unit/test_phase_7_recovery.py` and `tests/fault_injection/test_phase_7_recovery_faults.py`

## Architecture compliance

- Domain remains standard-library-only. Infrastructure owns udev, FFmpeg, FFprobe, media files,
  and durable journals. Application/IPC only exposes defined fields. Qt displays status and sends
  the predefined retry command.

## Tests executed

- `udevadm monitor --help`, `udevadm --version`, `ffmpeg -hide_banner -h full`, and `pactl --help`
  - Result: verified local supported udev monitoring, FFmpeg progress/stat, and Pulse command APIs.
- `make ci`
  - Result: pass — Ruff, mypy, 156 automated tests at 90.09% coverage, integration/fault suites,
    dependency audit, build, and wheel verification.
- Target-hardware guided unplug/reconnect, 2026-08-02
  - Result: pass — the configured `/dev/v4l/by-id` camera was detected as disconnected,
    recovery was journaled, and AV capture returned with video, audio, and output all healthy.
    The journal recorded a 17.102-second video-disconnect gap followed by a 2.048-second
    audio-only-to-AV restoration gap.

## Acceptance criteria

- [x] Completed segments remain byte-identical through automated recovery faults.
- [x] Gaps use monotonic duration and are persisted with explicit recovery facts.
- [x] Recovery creates a new segment and never appends to the interrupted output.
- [x] Unverified interrupted media is quarantined, never deleted or archived automatically.
- [x] Automated same-identity re-enumeration and repeated recovery-cycle coverage passes.
- [x] Target-hardware unplug/reconnect acceptance passes with the configured webcam.
- [ ] Multi-hour target-hardware soak — deferred by user.

## Known limitations deferred by plan

- The multi-hour target-hardware soak remains deferred by user.
- Retention, library/archive UI, packaging, multi-camera selection, and Phase 8+ work remain out
  of scope.

## Risks or decisions requiring user approval

- FFmpeg’s documented progress stream supplies encoded output time for the audio-progress signal;
  actual stream authority remains FFprobe verification, never process liveness or file existence.
- The selected persistent alias is one-to-one. If it no longer resolves, recovery waits rather than
  substituting a camera; the user must use the existing setup selection flow for a new identity.

## Next phase

Phase 8 is ready to begin after user approval; the multi-hour soak remains a deferred acceptance
activity.
