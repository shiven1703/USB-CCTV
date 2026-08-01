# Phase 2 handover prompt

Implement **Phase 2 — Domain model, state machines, persistence foundations** of `USB_CCTV_RECORDER_IMPLEMENTATION_PLAN.md`, and no later phase.

Before changing code, read `.codex/AGENTS.md` and the complete implementation plan. Confirm the Phase 1 completion commit (`27286ec`) is present and the worktree is clean. Do not start Phase 2 from an uncommitted Phase 1 baseline.

Phase 0 and Phase 1 are complete and user-approved. Preserve these established facts and decisions:

- Target baseline: Ubuntu 24.04.4 amd64, KDE Plasma 5.27.12/X11, Python 3.12.3, systemd 255, FFmpeg/ffprobe 6.1.1, PipeWire-Pulse, and `uv 0.12.1`.
- The camera uses persistent `video-index0`; its `video-index1` sibling is metadata-only. Physical input is MJPEG 2560 × 1440 at 30 FPS. The webcam microphone is the explicit mono 48 kHz Pulse source; never use the default source.
- The absolute managed-storage ceiling is 90,000,000,000 bytes. The dynamic effective cap reserves 20 GB for the OS and 8 GB for emergency finalization on the system filesystem.
- Phase 1 established `src/usb_cctv_recorder/`, canonical version metadata in `pyproject.toml`, PySide6 presentation-only Qt code, a separate worker entrypoint, pinned dependencies in `uv.lock`, `make ci`, and Ubuntu 24.04 CI.
- Preserve clean inward dependencies: `domain` uses only the standard library; `application` may import `domain`; `infrastructure` implements application ports; Qt imports stay in presentation.

For Phase 2, implement only the following foundations:

- Domain entities, immutable value objects where practical, domain errors, and explicit session, segment, archive-job, and health state machines.
- Application ports for devices, media process, power, persistence, clock, filesystem, and system service.
- SQLite schema, migration runner, and transaction boundary.
- Session manifest model and append-only JSONL event model.
- Shared atomic same-filesystem publish helper, cross-filesystem copy-and-verify helper, and streaming SHA-256 service.
- XDG path resolver and validated configuration model.

Do not implement camera/audio discovery, FFmpeg recording, preview UI, IPC, systemd service integration, power inhibition, retention, archives, or packaging. Do not place persistence, filesystem, or Qt logic in the domain or presentation layer.

Required Phase 2 tests include exhaustive valid and invalid state transitions, SQLite forward migration and rollback, manifest round trips, append-only event behavior, atomic publication with interruption simulation, cross-filesystem copy verification, SHA-256 known vectors, and timezone/monotonic-duration handling. Add tests for error paths as well as happy paths. Use synthetic or temporary filesystem fixtures only; do not require the webcam.

Run every Phase 2 quality gate through `make ci`, fix all failures, provide the prescribed Phase 2 completion report, and stop for user approval before Phase 3.
