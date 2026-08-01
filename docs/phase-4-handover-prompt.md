# Phase 4 handover prompt

Implement **Phase 4 — Minimal recording worker and safe segmentation** of `USB_CCTV_RECORDER_IMPLEMENTATION_PLAN.md`, and no later phase.

Before changing code, read `.codex/AGENTS.md` and the complete implementation plan. Confirm that the user-approved Phase 3 files are committed and the worktree is clean. Do not start from an uncommitted Phase 3 baseline. Read `docs/phase-3-completion-report.md` before design or implementation.

Phase 0 through Phase 3 are complete and user-approved. Preserve these established facts and boundaries:

- Target baseline: Ubuntu 24.04.4 amd64, KDE Plasma 5.27.12/X11, Python 3.12.3, systemd 255, FFmpeg/ffprobe 6.1.1, PipeWire-Pulse, and `uv 0.12.1`.
- The selected target camera is the persistent `/dev/v4l/by-id/usb-BC-250403-J_USB_2.0_Camera_2K_01.00.00-video-index0`; resolve it before recording and never persist a numeric `/dev/videoN` as its identity. Its `video-index1` sibling is metadata-only and excluded.
- The selected input mode is MJPEG, 2560 × 1440 at 30 FPS. Never use 2K YUYV: it is advertised at only 1 FPS.
- The selected microphone is the explicit mono 48 kHz Pulse source `alsa_input.usb-BC-250403-J_USB_2.0_Camera_2K_01.00.00-02.mono-fallback`; never capture from the audio-server default source.
- Phase 2 provides domain state machines, validated `RecorderConfiguration`, SQLite migrations/transactions, session manifests, append-only events, checksums, atomic publication, and XDG paths.
- Phase 3 provides application DTOs/preflight, a structured command runner with `shell=False`, V4L2/Pulse discovery, an FFmpeg capability probe, and a Qt preview test that releases all capture resources. The setup preflight passed on the target KDE session.
- Preserve inward dependencies: `domain` uses only the standard library; `application` may import `domain`; `infrastructure` implements application ports; Qt stays in `presentation`.

Implement only these Phase 4 deliverables:

- An FFmpeg recording command builder from validated structured settings, using only documented and locally verified FFmpeg options.
- An FFmpeg process wrapper with bounded stdout/stderr handling, process-group-aware graceful termination, timeout, and forced-kill escalation.
- FFmpeg progress parsing and explicit progress/health values suitable for the worker.
- A headless, CLI-only development recording control that creates a session directory, records synchronized video/audio into segmented MKV files, and safely stops.
- Session manifest and append-only event updates for the recording lifecycle.
- Final-file verification using FFprobe, including expected streams and plausible duration.
- Synthetic-media integration harness using verified FFmpeg test video and sine-audio sources; do not require the physical webcam in automated tests.

Do not implement systemd integration, persistent GUI/worker IPC, GUI recording controls, power inhibition, device hotplug recovery, library UI, archive workflows, retention/storage governor, package changes, or long-running service behaviour. The Phase 4 worker is intentionally headless and development-controlled only.

Before using any FFmpeg/FFprobe option, verify it against official documentation or the command's local help/version output. Pass commands as structured argument lists only: never use `shell=True` or concatenate untrusted command strings. Record resolved executable paths and versions in diagnostic logs. Treat zero FFmpeg exit status as insufficient until output verification succeeds.

Required automated coverage:

- Command-builder tests for validated camera/microphone identity, MJPEG input, selected capture mode, output profile, MKV segmentation, and rejection of invalid settings.
- Progress-parser tests for normal progress, malformed lines, stalls, and final progress.
- Process-wrapper tests for graceful stop, timeout, and forced-kill escalation without shell execution.
- Three-segment synthetic recording with short intervals, validation of every segment, and a safe stop during an active segment that produces a valid short final file.
- Fault tests for non-zero FFmpeg exit, verifier failure, and unwritable output. Prove earlier finalized segments remain unchanged after a later failure.
- Manifest/event tests covering start, segment finalization, successful stop, and failure reason.

Run `make ci`, fix every failure, provide the prescribed Phase 4 completion report, then stop for user approval. Perform no Phase 5 work in the same turn.
