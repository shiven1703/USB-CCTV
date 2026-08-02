# Phase 10 completion report

## Delivered

- Byte-accurate accounting of managed originals, verified archives, metadata, quarantine,
  derived share copies, and temporary transaction work, plus explicitly separate capacity and
  retention estimates.
- A persisted configurable storage cap with an absolute 90,000,000,000-byte ceiling, operating
  system reserve, emergency-finalization reserve, and runtime filesystem-free-space cap.
- A storage dashboard that shows actual usage, effective capacity, category pools, session-size
  estimates, and three-original-night/seven-history-night feasibility.
- An auditable storage governor with the required safety order: recovery analysis and stale
  temporary work, unprotected derived share copies, then unprotected verified archives. It never
  automatically deletes originals, protected evidence, current work, quarantine, or unverified
  media.
- Idle-only archive queueing through the existing Phase 9 transaction boundary. Healthy active
  recording does not start archive work.
- Working-reserve checks at recording start and segment boundaries. Unrecoverable pressure sends
  a critical-storage safe-stop request before the active segment can exhaust finalization space.
- Setup dashboard/configuration and an Archive-page manual safe-free-space action. Every automatic
  governor action is written to `.storage-audit.jsonl`.
- `scripts/verify_phase_10_storage.py`, a disposable acceptance harness that does not touch
  production evidence.

## Architecture compliance

- The application layer defines storage policy, dashboard, decisions, and the governor port;
  filesystem scanning, SQLite eligibility checks, journalling, and ordered deletion remain
  infrastructure concerns.
- The governor uses the existing Phase 9 archive transaction manager for recovery and archive
  queueing; it does not bypass archive validation or source-deletion rules.
- Qt remains a client of application services and does not directly own SQLite, authoritative
  files, or FFmpeg processes.
- Recording, IPC, recovery, quarantine, and archive transaction ownership remain in their
  existing phases.

## Tests executed

- `UV_CACHE_DIR=/tmp/usb-cctv-uv-cache make ci`
  - Result: 212 automated tests passed; format, lint, and mypy passed; coverage met the required
    90% threshold.
- `QT_QPA_PLATFORM=offscreen UV_CACHE_DIR=/tmp/usb-cctv-uv-cache uv run pytest --no-cov tests/integration -q`
  - Result: 4 passed, 1 skipped because the sandbox does not permit Unix socket binding.
- Manual automated storage acceptance supplied by the user:
  - `scripts/verify_phase_10_storage.py --base-directory /home/shivam/Videos/test`
  - Result: `pass`; it reclaimed 9,000,000 bytes in the required share-copy then archive order,
    preserved current/protected/quarantined/unverified media, wrote the audit journal, and raised
    the expected critical safe-stop decision under the forced pressure scenario.

## Acceptance criteria

- [x] The cap is never intentionally exceeded; it is clamped by runtime free space and reserves.
- [x] Retention estimates are advisory and explicitly separated from actual usage.
- [x] Retention actions preserve protected, current, partial, quarantined, and unverified media.
- [x] Archive queueing is idle-only and continues to use Phase 9 durable transactions.
- [x] The worker reserves active-segment finalization space and safely stops under unrecoverable
  pressure.
- [x] Automatic actions are auditable and the manual safe-free-space action is available.
- [x] The automated and user-run acceptance checks pass.

## Known limitations deferred by plan

- Debian packaging, release validation, multi-camera support, cloud/network features, and media
  repair remain out of scope for Phase 10.

## Next phase

Phase 10 is complete and user-approved. Phase 11 may begin only from the committed, clean Phase 10 baseline.
