# Phase 3 Completion Report

## Delivered

- V4L2 discovery using persistent `/dev/v4l/by-id` aliases, with friendly labels, capture modes, metadata-node exclusion, and a 1 FPS-mode exclusion that keeps the target's 2K YUYV mode unavailable.
- Pulse/PipeWire-Pulse source discovery that keeps the source name as the stable identity and uses the Pulse description as the friendly label.
- FFmpeg encoder and muxer enumeration. Encoder results are candidates only; none are marked runtime-usable.
- Application DTOs and preflight validation for explicit camera, microphone, mode, output directory, segment duration, and safe-space estimate.
- Qt Setup page with persisted selections, 1–360 minute duration, short-lived preview/microphone packet test, activity indication, and Start disabled until preflight passes.
- Structured command execution with an argv sequence and explicit `shell=False`.

## Files changed

- `src/usb_cctv_recorder/application/`: device/capability DTOs, preflight service, and typed device ports.
- `src/usb_cctv_recorder/infrastructure/`: structured command runner; V4L2, Pulse, FFmpeg, and storage-estimate adapters.
- `src/usb_cctv_recorder/presentation/qt/`: asynchronous discovery, Setup page, and resource-releasing Qt multimedia test.
- `tests/`: Phase 3 fixtures plus discovery, command-contract, Qt preflight, and preview-cleanup tests.
- `Makefile` and `README.md`: contract tests now run through the standard test target and Phase 3 setup behaviour is documented.
- `USB_CCTV_RECORDER_IMPLEMENTATION_PLAN.md` and `docs/phase-4-handover-prompt.md`: phase state and successor handover.

## Architecture compliance

- `domain` remains standard-library-only.
- Device, filesystem, subprocess, and FFmpeg probing are infrastructure adapters.
- Qt multimedia and widgets remain in `presentation`.
- No recording command construction, worker IPC, systemd integration, retention, archive workflow, or packaging scope was added.

## Tests executed

- `v4l2-ctl --help`, `v4l2-ctl --help-vidcap`, `pactl --help`, `ffmpeg -hide_banner -h`, and `ffmpeg -hide_banner -h muxer=matroska`
  - Result: verified every Phase 3 command-line option before use.
- `make ci`
  - Result: passed. Ruff formatting/linting, mypy (48 source files), 58 unit/contract/Qt tests at 90.77% coverage, dependency audit, source/wheel build, and wheel verification all passed.
- Manual target-KDE-session preflight test
  - Result: passed; user confirmed that the UI reported preflight success.

## Acceptance criteria

- [x] The target webcam and explicit webcam microphone are selectable.
- [x] Only verified supported capture modes are presented; metadata-only and 1 FPS modes are excluded.
- [x] Target-laptop preview and microphone preflight passed.
- [x] Failed preflight prevents Start.
- [x] Preview/test cleanup releases capture resources on success and failure.
- [x] Segment duration validates 1–360 minutes.

## Known limitations deferred by plan

- Phase 3 does not record, construct FFmpeg recording commands, segment media, start a persistent worker, or select a runtime-proven encoder.
- The displayed space value is a preflight safe-space estimate; measured recording-rate and retention estimates belong to later recording/storage phases.

## Risks or decisions requiring user approval

- User approval was recorded after the target-session preflight test passed.
- Hardware encoder candidates remain untrusted until Phase 4 runtime smoke tests.

## Next phase

Phase 4 is ready to begin only from the committed, clean Phase 3 baseline.
