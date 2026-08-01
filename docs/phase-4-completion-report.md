# Phase 4 Completion Report

## Delivered

- Validated FFmpeg argv construction for the selected persistent V4L2 camera, MJPEG capture mode, explicit Pulse source, mono 48 kHz AAC, `libx264`, forced segment-boundary keyframes, and Matroska segments.
- A process-group-aware FFmpeg wrapper with bounded stdout/stderr readers, parsed `-progress` updates, graceful SIGINT stop, SIGTERM timeout escalation, and forced SIGKILL as the last resort.
- A headless foreground development recorder that creates private session directories, journals lifecycle events, persists manifests, verifies each finalized segment with FFprobe, and records SHA-256 checksums.
- A CLI development command: `--record --media-root ... --camera ... --microphone ...`; Ctrl-C asks FFmpeg to finalize safely. A synthetic-only duration option supports automated media tests without hardware.
- Synthetic integration and fault coverage for segmentation, short final files, FFmpeg failure, verifier failure, an output directory becoming unwritable, and preservation of earlier finalized segments.

## Files changed

- `src/usb_cctv_recorder/infrastructure/ffmpeg/`: command builder, progress parser, process wrapper, and FFprobe verifier.
- `src/usb_cctv_recorder/worker/`: foreground recording lifecycle and CLI worker control.
- `src/usb_cctv_recorder/infrastructure/persistence/manifest.py`: finalized-segment checksum, filename, duration, stop reason, and failure reason fields.
- `src/usb_cctv_recorder/__main__.py`, `Makefile`, and `README.md`: development CLI and automated-suite wiring/documentation.
- `tests/unit/`, `tests/integration/`, and `tests/fault_injection/`: Phase 4 coverage.

## Architecture compliance

- `domain` remains standard-library-only.
- FFmpeg, FFprobe, subprocesses, files, and checksums remain infrastructure concerns.
- The headless worker is a composition/use boundary; Qt remains untouched in `presentation` and does not own FFmpeg.
- No systemd service, IPC, GUI recording control, power inhibitor, hotplug recovery, retention, archive, or package work was added.

## Tests executed

- `ffmpeg -hide_banner -version`, `ffmpeg -hide_banner -h full`, `ffmpeg -hide_banner -h muxer=segment`, `ffmpeg -hide_banner -h muxer=matroska`, `ffprobe -hide_banner -h full`, and `ffmpeg -hide_banner -filters`
  - Result: verified the local FFmpeg 6.1.1/FFprobe option and synthetic-source support before use. The final synthetic command experimentally produced independently probeable MKV segments.
- `make ci`
  - Result: passed — Ruff format/lint, mypy, 76 unit/contract/integration/fault-injection tests at 90.34% coverage, dependency audit, source/wheel build, and wheel verification.
- `QT_QPA_PLATFORM=offscreen uv run pytest --no-cov tests/fault_injection/test_phase_4_recording_faults.py`
  - Result: passed — non-zero exit, verifier failure, and later-unwritable-output preservation checks.
- `uv run ruff check src tests && uv run mypy`
  - Result: passed — lint and static typing clean.

## Acceptance criteria

- [x] Synthetic recording produces multiple playable MKV files.
- [x] Normal stop produces a valid partial-duration final file.
- [x] Every finalized synthetic file contains expected H.264 video and AAC audio streams.
- [x] Earlier finalized files remain byte-identical after later verifier and write failures.
- [x] Manifest records segment files/checksums and terminal stop or failure reason when metadata remains writable.
- [x] FFmpeg command, resolved executable path, and FFmpeg/FFprobe versions are written to session diagnostics.

## Known limitations deferred by plan

- This is a foreground development control only; closing a terminal ends the worker unless it is allowed to finish, and systemd/IPC persistence belongs to Phase 5.
- No device-disconnect recovery, watchdog response, audio-only/video-only fallback, power inhibition, storage governor, library, archive, or GUI recording action exists yet.
- `libx264` is the only runtime-proven encoder selected here. Hardware/HEVC selection needs its own smoke-test policy in later work.
- If the session directory becomes unwritable, the recorder reports a persistence failure and preserves media; it cannot durably append the final failure state until write access is restored.

## Risks or decisions requiring user approval

- User approval was recorded after the Phase 4 report was reviewed.
- FFmpeg `-progress` is parsed and exposes warning/stalled health values, but automatic watchdog recovery is intentionally Phase 7 work.
- The current headless control is deliberately terminal-bound. Approve Phase 4 before adding the on-demand systemd worker and IPC in Phase 5.

## Next phase

Phase 5 is ready to begin only from the committed, clean Phase 4 baseline.
