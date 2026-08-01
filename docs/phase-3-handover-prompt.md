# Phase 3 handover prompt

Implement **Phase 3 — Device discovery, capability probing, and preflight UI** of `USB_CCTV_RECORDER_IMPLEMENTATION_PLAN.md`, and no later phase.

Before changing code, read `.codex/AGENTS.md` and the complete implementation plan. Confirm that the user-approved Phase 2 files have been committed and that the worktree is clean. Phase 2 was approved on 2026-08-01, but no Phase 2 commit existed when this handover was created; do not invent a commit hash. Create or obtain that commit before beginning Phase 3.

Phase 0, Phase 1, and Phase 2 are complete and user-approved. Preserve these established facts and boundaries:

- Target baseline: Ubuntu 24.04.4 amd64, KDE Plasma 5.27.12/X11, Python 3.12.3, systemd 255, FFmpeg/ffprobe 6.1.1, PipeWire-Pulse, and `uv 0.12.1`.
- The target webcam’s stable capture identity is `/dev/v4l/by-id/usb-BC-250403-J_USB_2.0_Camera_2K_01.00.00-video-index0`. Its `video-index1` sibling is metadata-only and must be excluded. The confirmed physical input mode is MJPEG, 2560 × 1440 at 30 FPS. Do not select 2K YUYV: it is only advertised at 1 FPS.
- The webcam microphone is the explicit mono 48 kHz Pulse source `alsa_input.usb-BC-250403-J_USB_2.0_Camera_2K_01.00.00-02.mono-fallback`. Never use the Pulse/PipeWire default source.
- The absolute managed-storage ceiling is 90,000,000,000 bytes. Default system-filesystem reserves are 20 GB for the OS and 8 GB for emergency finalization.
- Phase 1 established the `src/usb_cctv_recorder/` layout, canonical version metadata, PySide6 presentation-only Qt code, a separate worker entrypoint, pinned dependencies, `make ci`, and Ubuntu 24.04 CI.
- Phase 2 added standard-library-only domain models and explicit session, segment, archive-job, and health state machines; application ports and validated configuration; XDG path resolution; SQLite migrations/transactions; atomic manifest publishing; append-only JSONL events; and SHA-256/atomic copy helpers. See `docs/phase-2-completion-report.md`.
- Preserve inward dependencies: `domain` uses only the standard library; `application` may import `domain`; `infrastructure` implements application ports; Qt imports stay in `presentation`.

Implement only these Phase 3 deliverables:

- V4L2 video-device discovery, including stable identity resolution, friendly names, supported capture modes, and rejection of metadata-only/unusable nodes.
- PipeWire-Pulse/PulseAudio source discovery with friendly and stable identifiers.
- FFmpeg encoder and muxer capability probing. Candidate encoders are not considered usable until a later runtime smoke test; Phase 3 may report candidates only.
- Device DTOs for the UI, retaining both friendly labels and persistent identifiers so duplicate friendly names remain unambiguous.
- A Qt Setup page for camera, microphone, supported resolution/frame-rate selection, 1–360 minute segment duration, output directory, and a storage estimate from the validated configuration. Start must remain disabled until preflight succeeds.
- Short-lived preview/test mode and microphone activity indication. It must release every opened device before a recording attempt can begin. Do not run two independent consumers of the same camera unless the capability is verified.
- Clear missing-device, permission-denied, unsupported-mode, and preflight-failure presentation.

Do not implement recording, FFmpeg recording command construction, segmentation, persistent worker IPC, systemd integration, power inhibition, retention, archive workflows, or package changes. Do not place subprocess, filesystem, device, PulseAudio, or Qt logic in the domain.

Required tests:

- Unit tests using the committed V4L2 and Pulse source fixtures, plus fixtures for duplicate friendly names, no devices, permission denied, and unsupported modes.
- Contract tests for structured command execution. Never use `shell=True` or assemble an untrusted command string.
- Stable-identity tests where `/dev/videoN` changes while the persistent by-id path remains the same.
- Tests proving `video-index1`/metadata-only nodes and unsupported modes are excluded.
- pytest-qt tests for selection persistence, preflight errors, and Start disabled until all prerequisites are valid.
- Tests that preview/test cleanup releases opened resources on both success and failure.

Before using V4L2, pactl/PulseAudio, or FFmpeg command-line options, verify each option against official documentation or the command’s local help/version output. Use synthetic fixtures for automated tests; the real webcam is only for the final manual acceptance check.

Run `make ci`, fix every failure, and provide a concise Phase 3 completion report. Then perform the real-hardware preview and microphone activity check on the target laptop. Stop and wait for user confirmation before Phase 4.
