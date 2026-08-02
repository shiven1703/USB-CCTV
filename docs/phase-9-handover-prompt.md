# Phase 9 handover prompt

Implement **Phase 9 — Manual archive and evidence-safe archive transactions** of
`USB_CCTV_RECORDER_IMPLEMENTATION_PLAN.md`, and no later phase.

Before changing code, read `.codex/AGENTS.md` and the complete implementation plan. Confirm the
user-approved Phase 8 implementation is the current committed `HEAD` and the worktree is clean.
Read `docs/phase-8-completion-report.md` before design or implementation. Do not start from an
uncommitted Phase 8 baseline.

Phases 0 through 8 are complete and user-approved. Preserve these facts and boundaries:

- Target baseline: Ubuntu 24.04.4 amd64, KDE Plasma 5.27.12/X11, Python 3.12.3, systemd 255,
  FFmpeg/ffprobe 6.1.1, PipeWire-Pulse, and `uv 0.12.1`.
- Preserve the selected persistent camera identity and explicit Pulse microphone source. Never
  substitute a transient video node or default audio source.
- Phase 4 owns FFmpeg/ffprobe, finalized media verification, manifests, checksums, and event
  journals. Phase 5 owns worker IPC. Phase 6 owns inhibition and critical-battery safe stop.
  Phase 7 owns recovery, gaps, quarantine, and degraded capture.
- Phase 8 owns the paged Qt Library, the derived SQLite catalogue, protected-state persistence,
  read-only playback, diagnostics, and catalogue rebuild. Qt must remain a client: it must not
  directly own SQLite, authoritative files, or FFmpeg processes.
- Preserve inward dependencies: `domain` is standard-library-only; `application` may import
  `domain`; infrastructure implements ports; presentation remains Qt-only.

Implement only the Phase 9 deliverables:

- Manual selection UI for one or more originals, sessions, and requested free-space archiving.
- An archive queue with pause, resume, and cancel; clear progress and detailed failure state.
- Same-drive compressed archive transaction and cross-drive move-without-compression transaction.
- Archive profile selection, source/archive relationship persistence, and move-to-active-library
  and derived share-copy actions with accurate labels.
- Full source/output validation, including ffprobe checks, full decode, duration/stream comparison,
  checksums, atomic publication, durable catalogue/manifest commit, and post-commit-only source
  deletion when explicitly selected.
- Recovery visibility for every partial archive transaction after application crash or restart.

Apply the plan's numbered archive transaction exactly. Never transcode, repair, remux, or overwrite
the source in place. Never delete a source until its archive is fully decoded, verified, atomically
published, catalogued, and durably committed. A cancelled or failed transaction leaves the source
untouched and never publishes a partial. Protected, quarantined, interrupted-unverified, and active
media are ineligible. A share copy is derived, never authoritative evidence.

Do not implement automatic retention, storage-pressure policy, archive scheduling, packaging,
multi-camera support, cloud/network features, media repair, or Phase 10+ work. Do not change the
existing capture, recovery, IPC, or library ownership boundaries except for narrowly required
application ports and catalogue fields.

Before using FFmpeg/ffprobe, filesystem atomic operations, SQLite, or Qt APIs, verify exact local
support or official documentation. Use structured subprocess argv with `shell=False`. A process
exit code, file existence, or checksum alone is not sufficient proof of valid media.

Required automated coverage includes failure injection at every numbered archive-transaction step;
cancellation during transcode; destination disconnect; checksum/decode/duration/audio failures;
crash/restart partial recovery; source byte preservation; direct archive playback; safe share-copy
creation; and regressions for Phase 4 verification, Phase 5 IPC ownership, and Phase 7 quarantine.

Run `make ci`, fix every failure, provide `docs/phase-9-completion-report.md`, and then stop for
user approval. Do not begin Phase 10 in the same turn.
