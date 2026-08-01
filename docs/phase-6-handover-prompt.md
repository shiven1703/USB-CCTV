# Phase 6 handover prompt

Implement **Phase 6 — Power inhibition and shutdown finalization** of
`USB_CCTV_RECORDER_IMPLEMENTATION_PLAN.md`, and no later phase.

Before changing code, read `.codex/AGENTS.md` and the complete implementation plan. Confirm the
user-approved Phase 5 files are committed and the worktree is clean. Read
`docs/phase-5-completion-report.md` before design or implementation. Do not start from an
uncommitted Phase 5 baseline.

Phase 0 through Phase 5 are complete and user-approved. Preserve these facts and boundaries:

- Target baseline: Ubuntu 24.04.4 amd64, KDE Plasma 5.27.12/X11, Python 3.12.3, systemd 255,
  FFmpeg/FFprobe 6.1.1, PipeWire-Pulse, and `uv 0.12.1`.
- The selected camera is the persistent
  `/dev/v4l/by-id/usb-BC-250403-J_USB_2.0_Camera_2K_01.00.00-video-index0`; resolve it before
  recording and never persist `/dev/videoN`. Its `video-index1` sibling is metadata-only. Input
  is MJPEG, 2560 × 1440 at 30 FPS.
- The selected microphone is the explicit mono 48 kHz Pulse source
  `alsa_input.usb-BC-250403-J_USB_2.0_Camera_2K_01.00.00-02.mono-fallback`; never use the audio
  server default source.
- Phase 4 owns validated FFmpeg/FFprobe adapters, segment creation, process groups, bounded
  graceful/forced process lifecycle handling, manifests, events, and checksums. Do not move
  FFmpeg ownership into Qt.
- Phase 5 owns private worker-readable capture configuration, the on-demand systemd user unit,
  current-user Unix-socket IPC, single-session worker supervision, and GUI status reconnect.
  Real recording, reconnect, safe stop, crash/restart, and GUI close/reopen acceptance passed.
- The current worker handles service `SIGTERM` only by cleaning up its socket. Safe active-recording
  finalization during shutdown is deliberately Phase 6 work and must replace that limited behavior.
- Preserve inward dependencies: `domain` uses only the standard library; `application` may import
  `domain`; `infrastructure` implements application ports; Qt remains in `presentation`.

Implement only these Phase 6 deliverables:

- A logind power-inhibitor adapter using the official API or a locally verified supported wrapper.
- Worker-held inhibitors while recording that block sleep, idle-triggered suspend, and hibernate;
  optional lid-close blocking must remain an explicit setting.
- User-visible power-protection status through application/presentation boundaries, without Qt
  owning the inhibitor handle.
- Bounded systemd `SIGTERM`/normal-shutdown finalization: stop FFmpeg safely, verify/persist the
  final segment, update manifests/events, release inhibitors, and exit only after the outcome is
  known or the documented timeout policy is reached.
- AC/battery status adapter and the specified graceful critical-battery stop policy.

Do not implement device hotplug recovery, watchdog recovery, audio-only/video-only fallback,
retention/storage governor, library/archive UI, package changes, or Phase 7+ functionality. Do
not permanently modify KDE, logind, or the user’s power configuration.

Before using logind D-Bus APIs, `systemd-inhibit`, systemd unit behavior, or Qt APIs, verify every
API, directive, and command-line option against official documentation or local command/API help.
Keep every subprocess argv structured with `shell=False`. Do not claim that power protection works
until the target KDE desktop manual checks pass.

Required automated coverage:

- Inhibitor adapter acquisition, release, status, and acquisition-failure tests using a fake D-Bus
  service or verified wrapper boundary.
- Inhibitor release after normal safe stop, failure, and finalization timeout.
- Worker `SIGTERM` tests proving an active segment follows the safe-finalization flow within the
  bounded timeout and that already finalized media remains unchanged.
- Tests for shutdown/finalization failure context, manifest/event durability, and worker exit code.
- AC/battery adapter tests, critical-battery transition, and UI power-status tests.
- Socket/worker regression tests proving Phase 5 reconnect and safe-stop behavior is preserved.

Required manual target-desktop acceptance:

- Start recording, turn the display off, lock KDE, and disconnect HDMI; recording must continue.
- Confirm the configured idle timeout does not suspend the laptop while recording.
- Confirm the worker safely finalizes the active segment after a normal service stop/shutdown
  request and releases all inhibitors.
- Run the lid-close check only when the user explicitly enables that setting.

Run `make ci`, fix every failure, provide the prescribed Phase 6 completion report, and then stop
for user approval. Do not begin Phase 7 in the same turn.
