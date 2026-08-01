# Phase 7 handover prompt

Implement **Phase 7 — Capture watchdog, failure recovery, and degraded modes** of
`USB_CCTV_RECORDER_IMPLEMENTATION_PLAN.md`, and no later phase.

Before changing code, read `.codex/AGENTS.md` and the complete implementation plan. Confirm the
user-approved Phase 6 files are committed at `2e9c259` and the worktree is clean. Read
`docs/phase-6-completion-report.md` before design or implementation. Do not start from an
uncommitted Phase 6 baseline.

Phase 0 through Phase 6 are complete and user-approved. Preserve these established facts and
boundaries:

- Target baseline: Ubuntu 24.04.4 amd64, KDE Plasma 5.27.12/X11, Python 3.12.3, systemd 255,
  FFmpeg/ffprobe 6.1.1, PipeWire-Pulse, and `uv 0.12.1`.
- The camera is the persistent
  `/dev/v4l/by-id/usb-BC-250403-J_USB_2.0_Camera_2K_01.00.00-video-index0`; resolve this identity
  for every attempt and never persist a `/dev/videoN` node. Reject its metadata-only
  `video-index1` sibling. Capture input is MJPEG, 2560 × 1440 at 30 FPS.
- The microphone is the explicit mono 48 kHz Pulse source
  `alsa_input.usb-BC-250403-J_USB_2.0_Camera_2K_01.00.00-02.mono-fallback`; never use the default
  source.
- Phase 4 owns FFmpeg/ffprobe, process groups, bounded graceful/forced termination, segment
  verification, manifests, event journaling, checksums, and preservation of already-finalized
  media. Do not duplicate or move media ownership into Qt.
- Phase 5 owns the static on-demand systemd user service, private worker configuration,
  current-user Unix-socket IPC, single-session supervision, and GUI reconnect. Preserve the
  closed protocol; only add predefined schema-validated status/action fields when Phase 7 needs
  them.
- Phase 6 owns worker-held runtime-only logind inhibition and bounded `SIGTERM` finalization. It
  uses a user-approved 5% off-AC critical-battery safe-stop policy. Do not alter KDE, logind, or
  global USB power settings.
- Preserve inward dependencies: `domain` uses only the standard library; `application` may import
  `domain`; `infrastructure` implements application ports; Qt remains in `presentation`.

Implement only these Phase 7 deliverables:

- A udev-based video-device hotplug monitor and identity re-resolution; verify the supported API
  locally before use. Treat an ambiguous identity as a user-visible selection requirement, never
  an automatic substitute.
- Video-progress, audio-progress, and output-growth watchdogs using monotonic time. Apply the
  plan thresholds: warn at 5 seconds and declare stalled at 15 seconds for each relevant signal.
- Worker heartbeat and explicit recovery journal state.
- Recovery scheduling of 2, 5, 10, 30, then 60-second retries. A recovery attempt must first stop
  and verify the active segment when possible; it must never append to an uncertain file.
- Verified interrupted-media handling: preserve an interrupted segment only when it verifies;
  otherwise quarantine it without deletion. Preserve all completed segments byte-for-byte.
- Explicit gap facts using monotonic duration plus wall-clock timestamps, with reason, attempts,
  and last good audio/video timestamps. Never report continuity across a gap.
- Audio-only emergency capture if video fails while audio remains healthy, and video-only emergency
  capture if audio fails while video remains healthy. Never synthesize black video or silent audio.
- Worker/UI health, recovery, gap, and retry-now status/actions through application and IPC
  boundaries. Qt remains display/control only.

Do not implement retention or storage-pressure handling, archive/library UI, package changes,
multi-camera support, cloud/network features, or Phase 8+ work. Do not permanently alter KDE,
logind, or USB power configuration. Do not silently choose a different camera or microphone.

Before using udev, PipeWire/Pulse, systemd, FFmpeg, or Qt APIs, verify the specific API and
command options against official documentation or local supported help. Keep subprocess argv
structured with `shell=False`. Never treat an FFmpeg process being alive, a zero return code, or a
file's existence as proof of healthy capture or valid media.

Required automated coverage:

- Fault-injection tests for device removal, persistent-identity return under a different
  `/dev/videoN`, video/audio progress stalls with a live process, output-growth stall, FFmpeg exit,
  stop while recovery is requested, and five repeated disconnect/reconnect cycles.
- Tests for each retry delay, bounded recovery state, exact monotonic gap duration, and durable
  manifest/event/recovery-journal facts.
- Tests proving completed segments remain byte-identical, recovery always creates a new segment,
  and a failed interrupted segment is quarantined rather than deleted or archived.
- Synthetic tests for audio-only and video-only emergency segments, including stream validation and
  explicit degraded-mode status.
- Socket/worker/UI regressions preserving Phase 5 reconnect/safe-stop and Phase 6 inhibitor/
  shutdown behavior.

Required manual target-hardware acceptance:

- Unplug and reconnect the webcam, including a changed transient video node if the kernel assigns
  one; verify a documented gap and a new segment after recovery.
- Leave capture running for several hours and confirm the UI exposes health, gaps, retries, and
  degraded modes accurately.
- Confirm already-finalized media remains byte-identical through each exercised failure.

Run `make ci`, fix every failure, provide the prescribed Phase 7 completion report, and then stop
for user approval. Do not begin Phase 8 in the same turn.
