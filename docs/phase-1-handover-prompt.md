# Phase 1 handover prompt

Implement **Phase 1 — Project scaffolding and quality gates** of `USB_CCTV_RECORDER_IMPLEMENTATION_PLAN.md`, and no later phase.

Before changing code, read `.codex/AGENTS.md` and the complete implementation plan. Confirm that the approved Phase 0 changes are committed; Phase 1 must not start from an uncommitted Phase 0 state.

Phase 0 is complete and user-approved. Preserve its facts and decisions:

- Ubuntu 24.04 amd64, KDE Plasma 5.27.12, X11, PipeWire-Pulse, systemd 255, FFmpeg 6.1.1, and uv 0.12.1.
- Use persistent camera `video-index0`; exclude the metadata-only `video-index1` sibling.
- Physical camera input is MJPEG 2560 × 1440 at 30 FPS; webcam audio is explicit mono 48 kHz, never the default Pulse source.
- 90 GB is the absolute managed-storage ceiling. The dynamic effective cap uses live free space minus the 20 GB OS and 8 GB emergency-finalization reserves.
- The real machine probe is local and Git-ignored under `.local/probes/`; committed fixtures and samples must stay sanitized.

For Phase 1, create only the repository scaffold, pinned project tooling and lockfile, Makefile quality gates, a minimal PySide6 window titled `USB CCTV Recorder`, a clean `--worker` entrypoint, CI, and initial architecture ADRs. Add the required import, Qt smoke, and CLI tests. Run every Phase 1 quality gate, provide the prescribed Phase 1 completion report, and stop for user approval.
