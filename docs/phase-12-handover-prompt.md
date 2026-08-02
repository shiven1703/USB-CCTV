# Phase 12 handover prompt

Implement **Phase 12 — Soak testing, adversarial validation, and release** of
`USB_CCTV_RECORDER_IMPLEMENTATION_PLAN.md`, and no later phase.

Before changing code, read `.codex/AGENTS.md` and the complete implementation plan. Confirm the
user-approved Phase 11 implementation is the current committed `HEAD` and the worktree is clean.
Read `docs/phase-11-completion-report.md`, `docs/phase-11-clean-vm-checklist.md`, and the relevant
Phase 4 through Phase 10 completion reports before preparing tests or release evidence. Do not
start from an uncommitted Phase 11 baseline.

Phases 0 through 11 are complete and user-approved. Preserve these facts and boundaries:

- Target baseline: Ubuntu 24.04.4 amd64, KDE Plasma 5.27.12/X11, Python 3.12.3, systemd 255,
  FFmpeg/ffprobe 6.1.1, PipeWire-Pulse, and `uv 0.12.1`.
- Use the configured persistent camera identity and explicit Pulse microphone source. Never
  substitute a transient `/dev/video*` node or default audio source.
- The Phase 11 `.deb` is the normal-user delivery artifact. The static user worker is on-demand;
  do not enable it permanently at login or run the application as root.
- Phase 4 owns media verification, manifests, checksums, and event journals. Phase 5 owns worker
  IPC and GUI/service ownership. Phase 6 owns inhibition and critical-battery safe stop. Phase 7
  owns recovery, gaps, quarantine, and degraded capture. Phase 8 owns the derived catalogue and
  Library UI. Phase 9 owns archive transactions. Phase 10 owns retention and storage pressure.
- Preserve inward dependencies: `domain` is standard-library-only; `application` may import
  `domain`; infrastructure implements ports; presentation remains Qt-only.

Phase 12 is release validation, not feature development. Produce a release candidate `.deb`, a
completed manual acceptance checklist, a 12-hour minimum soak report, fault-injection report,
archive-integrity report, storage-governor report, release notes, known limitations, and recovery
guide. Record commands, timestamps, configuration, observed state transitions, evidence paths,
and every unexpected result in durable project documentation.

Run the required real-hardware tests on the actual laptop and webcam:

1. Record continuously for at least 12 hours using the intended 2K profile or documented fallback
   and the configured segment duration.
2. Allow screen power-off, lock KDE, disconnect HDMI, and confirm the laptop does not suspend.
3. Unplug and reconnect the webcam, including a return under a different transient path; simulate
   or trigger a camera stall where safe.
4. Kill FFmpeg and verify recovery; kill the worker and verify systemd recovery.
5. Stop midway through a segment and verify every completed and final partial segment.
6. Archive selected recordings; interrupt archive work; restart and recover the queue; preview
   originals and archives; and create a share copy.
7. Exercise storage pressure only in a controlled test directory. Verify gaps and errors appear in
   both UI and manifests, and prove completed originals remain byte-identical through unrelated
   failures.

Apply the release acceptance criteria exactly: no unexplained recording gap; accurate timestamps
and reasons for every explained gap; no completed-segment corruption; no original loss during
archive tests; no protected-evidence deletion; consistent safe-stop finalization; responsive UI;
acceptable CPU temperature/load; storage growth compatible with the configured budget; successful
package installation without developer tools; and all automated and manual release tests passing.

Never perform destructive tests against production evidence. Use an explicitly designated
controlled test media root for storage-pressure, interruption, and fault tests; preserve manifests,
checksums, and hashes before and after every disruptive operation. Do not conceal failed, skipped,
or environment-limited tests. A product defect is a release blocker unless the user explicitly
approves a documented limitation; do not broaden scope into new features, multi-camera support,
cloud/network functionality, media repair, or a later phase.

Run `make ci` before reporting. Provide a concise `docs/phase-12-completion-report.md` in the
implementation-plan completion format, including the evidence for every real-hardware test and any
blocked criterion. Stop for explicit user release approval; do not begin any later phase in the
same turn.
