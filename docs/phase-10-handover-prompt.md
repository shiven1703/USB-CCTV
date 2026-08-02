# Phase 10 handover prompt

Implement **Phase 10 — Automatic retention and dynamic storage governor** of
`USB_CCTV_RECORDER_IMPLEMENTATION_PLAN.md`, and no later phase.

Before changing code, read `.codex/AGENTS.md` and the complete implementation plan. Confirm the
user-approved Phase 9 implementation is the current committed `HEAD` and the worktree is clean.
Read `docs/phase-9-completion-report.md` before design or implementation. Do not start from an
uncommitted Phase 9 baseline.

Phases 0 through 9 are complete and user-approved. Preserve these facts and boundaries:

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
- Phase 9 owns archive profiles, durable archive transactions and journals, full archive
  validation, archive/source relationships, move-to-active-library, and derived share copies.
  The Phase 10 governor must call those application/infrastructure boundaries rather than
  duplicating or weakening archive validation.
- Preserve inward dependencies: `domain` is standard-library-only; `application` may import
  `domain`; infrastructure implements ports; presentation remains Qt-only.

Implement only the Phase 10 deliverables:

- Byte-accurate accounting for all application-managed storage categories, including originals,
  verified archives, metadata, quarantine, share copies, temporary transaction work, and reserved
  space.
- Runtime effective-cap and session-size estimators, plus explicit three-recent-original-night and
  seven-total-history-night feasibility estimates. Clearly label estimates separately from actual
  usage.
- Enforce the absolute 90,000,000,000-byte ceiling and the lower runtime effective cap after
  operating-system and emergency-finalization reserves. Reject configured caps above 90 GB.
- A governor and archive scheduler that can plan action under pressure, a storage dashboard,
  warnings, a manual “free N GB” action, and an auditable record of every automatic action.
- Working-reserve enforcement and a safe-stop signal before the disk can prevent finalization of
  the active segment.

Apply the policy order exactly when space is needed:

1. Remove only stale, known-safe temporary files after recovery analysis.
2. Delete the oldest unprotected derived share copies.
3. Delete the oldest unprotected verified archives.
4. Queue eligible unprotected originals for the existing Phase 9 archive transaction only when
   recording is not active.
5. Refuse to delete protected or recent original evidence.
6. Stop recording safely if enough space cannot be recovered.

Do not run heavy archive transcoding while healthy recording is active unless a user explicitly
overrides the default and the platform has passed performance testing. Never automatically delete
current, partial, protected, interrupted-unverified, quarantined, or unverified media. Never
transcode, repair, remux, or overwrite an original in place. Any source deletion remains governed
by the fully verified and durably committed Phase 9 archive transaction; the retention governor
must not invent a shortcut. Preserve archive source relationships and audit visibility throughout.

Do not implement Phase 11 packaging, release validation, multi-camera support, cloud/network
features, media repair, or Phase 12+ work. Do not refactor capture, recovery, IPC, library, or
archive ownership boundaries except for narrowly required application ports and catalogue fields.

Before using filesystem capacity APIs, SQLite, Qt APIs, or scheduler/concurrency primitives,
verify exact local support or official documentation. Use structured subprocess argv with
`shell=False`. Keep all destructive actions explicit, eligibility-checked, ordered, and recorded.

Required automated coverage includes the Phase 10 plan tests: exact 90,000,000,000-byte cap
calculations; lower filesystem-free-space effective caps; OS/emergency reserve subtraction and
zero clamping; the current-machine 104.2 GB minus 20 GB minus 8 GB approximately 76.2 GB case;
the 52% originals, 33% archives, 5% metadata/quarantine/share copies, and 10% transaction-headroom
allocation ratios; rejection of caps above 90 GB; protected-capacity and no-candidate cases;
archive queue pressure; temporary work exceeding reserve; concurrent library refresh/governor
decisions; critical-storage safe stop before a segment boundary; and proof that current, partial,
protected, and unverified files are never deleted. Also cover regressions for Phase 4 media
verification, Phase 5 IPC ownership, Phase 7 recovery/quarantine, and Phase 9 archive safety.

Run `make ci`, fix every failure, provide `docs/phase-10-completion-report.md`, and then stop for
user approval. Do not begin Phase 11 in the same turn.
