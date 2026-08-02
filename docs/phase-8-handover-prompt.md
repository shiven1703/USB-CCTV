# Phase 8 handover prompt

Implement **Phase 8 — Library, playback, protection, and integrity UI** of
`USB_CCTV_RECORDER_IMPLEMENTATION_PLAN.md`, and no later phase.

Before changing code, read `.codex/AGENTS.md` and the complete implementation plan. Confirm the
user-approved Phase 7 files are committed at `074209a` and the worktree is clean. Read
`docs/phase-7-completion-report.md` before design or implementation. Do not start from an
uncommitted Phase 7 baseline.

Phases 0 through 7 are complete and user-approved. Preserve these established facts and
boundaries:

- Target baseline: Ubuntu 24.04.4 amd64, KDE Plasma 5.27.12/X11, Python 3.12.3, systemd 255,
  FFmpeg/ffprobe 6.1.1, PipeWire-Pulse, and `uv 0.12.1`.
- The camera is the persistent
  `/dev/v4l/by-id/usb-BC-250403-J_USB_2.0_Camera_2K_01.00.00-video-index0`; the microphone is
  the explicit mono 48 kHz Pulse source
  `alsa_input.usb-BC-250403-J_USB_2.0_Camera_2K_01.00.00-02.mono-fallback`. Never substitute a
  transient device or default audio source.
- Phase 4 owns FFmpeg/ffprobe, process groups, finalized-segment verification, manifests,
  checksums, and event journals. Phase 5 owns the current-user Unix-socket worker IPC. Phase 6
  owns runtime-only logind inhibition and the user-approved 5% off-AC critical-battery policy.
- Phase 7 owns udev identity re-resolution, watchdogs, retries, recovery journals, explicit gaps,
  quarantined interrupted media, and degraded capture. Its target-hardware unplug/reconnect
  acceptance passed; the multi-hour soak is deferred by the user.
- Preserve inward dependencies: `domain` uses only the standard library; `application` may import
  `domain`; infrastructure implements application ports; Qt remains presentation only. The GUI
  must never own authoritative files, FFmpeg processes, or direct SQLite access.

Implement only these Phase 8 deliverables:

- A Qt model/view Library page for originals, archives, gaps, and quarantined items. Use an
  incremental or paginated `QAbstractTableModel`/`QAbstractListModel`; do not build an unbounded
  widget tree.
- Filters for date, session, media class, protected state, validation state, and gap state.
- Read-only integrated playback for original and archive files, with seeking, volume, playback
  speed, and previous/next-segment controls. Verify the chosen supported Qt multimedia APIs locally
  before use. Playback must never rewrite, remux, repair, or otherwise mutate authoritative media.
- A recording-details panel, including explicit gap and failure facts from existing manifests and
  recovery journals.
- Durable protect/unprotect, open-containing-folder, and re-verify-integrity actions through
  application and infrastructure boundaries.
- A quarantine review UI and a catalogue rebuild command that reconstructs browseable state from
  media/manifests without modifying media bytes.

Do not implement archive transactions or archive queues, automatic retention/storage-pressure
management, package changes, multi-camera support, cloud/network features, media repair, or Phase
9+ work. Do not silently hide a missing, damaged, quarantined, or undecodable file: show an
explicit diagnostic state. Protected items remain counted as managed storage and must remain
excluded from any automatic deletion.

Before using Qt multimedia, desktop-folder launching, SQLite, FFmpeg/ffprobe, or filesystem APIs,
verify the exact supported API or command options against official documentation or local help.
Keep subprocess argv structured with `shell=False`. Do not use process liveness, file existence,
or a successful player launch as proof of valid media; re-verification must use the existing
authoritative verification/checksum path.

Required automated coverage:

- Model/view pagination or incremental loading, including filter combinations and empty results.
- Protect/unprotect persistence across restart/reload.
- Playback error handling for missing and unsupported/undecodable files without mutation.
- Catalogue rebuild from fixture directories, including missing-file reconciliation, without media
  byte changes.
- Checksum mismatch and quarantine diagnostic display.
- Gap timeline/details display from explicit Phase 7 recovery facts.
- Regression coverage for Phase 4 evidence verification, Phase 5 IPC ownership, and Phase 7
  recovery/quarantine behaviour.

Run `make ci`, fix every failure, provide `docs/phase-8-completion-report.md`, and then stop for
user approval. Do not begin Phase 9 in the same turn.
