# Phase 9 Completion Report

## Delivered

- Manual archive selection from the Library, including multiple originals, a session selector, and an explicit oldest-first “free N GB” selection.
- Archive tab with profile selection, durable queue state, progress, pause, resume, cancel, retry, and visible detailed failures.
- Same-drive compressed archive transactions using FFmpeg video re-encode and `-c:a copy`; cross-drive archive transactions copy bytes without compression.
- Source precheck, advisory source lock, working-space check, temporary output, fsync, ffprobe stream/container validation, full decode, duration/stream comparison, ordered encoded-audio packet SHA-256 comparison, checksum, atomic publication, archive manifest, and catalogue commit.
- Source deletion only after the archive is fully committed and only when explicitly selected. Failed/cancelled work leaves the source untouched and partial/recovery state visible.
- SQLite migration for durable archive-job details and source/archive relationships that survive catalogue rebuilds. Archive manifests retain the source relationship after an explicitly deleted original.
- “Move archive to active library (quality unchanged)” and “Create derived share copy” actions. The archive label remains archive; share copies are stored as `share_copy` and never replace authoritative media.

## Files changed

- `src/usb_cctv_recorder/application/archive.py`
- `src/usb_cctv_recorder/application/dto.py`
- `src/usb_cctv_recorder/application/ports.py`
- `src/usb_cctv_recorder/bootstrap.py`
- `src/usb_cctv_recorder/infrastructure/ffmpeg/verifier.py`
- `src/usb_cctv_recorder/infrastructure/persistence/library_catalogue.py`
- `src/usb_cctv_recorder/infrastructure/persistence/migrations/versions.py`
- `src/usb_cctv_recorder/infrastructure/storage/archive_transaction.py`
- `src/usb_cctv_recorder/presentation/qt/main_window.py`
- `src/usb_cctv_recorder/presentation/qt/pages/archive_page.py`
- `src/usb_cctv_recorder/presentation/qt/pages/library_page.py`
- `tests/unit/test_persistence_foundations.py`
- `tests/unit/test_phase_9_archive.py`
- `tests/integration/test_phase_9_archive.py`

## Architecture compliance

- `domain` remains standard-library-only. Archive orchestration is application-facing; FFmpeg, SQLite, checksums, durable filesystem operations, and manifests remain infrastructure concerns.
- Qt only calls `ArchiveService` on background threads. It does not invoke FFmpeg, SQLite, or filesystem operations directly.
- Existing recording, IPC, recovery, quarantine, and playback ownership boundaries are unchanged.

## Tests executed

- `UV_CACHE_DIR=/tmp/usb-cctv-uv-cache make ci`
  - Result: the combined command’s test stage passed **197 tests** at **90.03% coverage**. The execution wrapper truncates the later combined stream, so its remaining targets were also run individually below.
- `QT_QPA_PLATFORM=offscreen UV_CACHE_DIR=/tmp/usb-cctv-uv-cache uv run pytest --no-cov tests/integration -q`
  - Result: 5 passed.
- `make test-faults`
  - Result: 8 passed.
- `make audit`
  - Result: no known vulnerabilities.
- `make verify-package`
  - Result: source distribution and wheel built; wheel archive verification passed.

Phase 9-specific coverage includes every numbered archive transaction stage, cancellation during transcode, destination-copy failure, decode/duration/audio-packet failures, source preservation, crash/restart partial recovery, direct verified archive playback facts, derived share-copy safety, and active-library reclassification.

## Acceptance criteria

- [x] No tested failure path modifies or deletes the original source.
- [x] Archives are catalogued only after probe, decode, stream/duration, audio-packet, checksum, atomic-publication, and manifest checks succeed.
- [x] Same-drive compressed and cross-drive uncompressed transactions are distinct and durable.
- [x] Archive queue cancellation, recovery visibility, and failure detail are available in the UI.
- [x] Archives remain direct library media; share copies remain derived and are accurately labelled.

## Known limitations deferred by plan

- Automatic retention, storage-pressure policy, scheduling, and automatic “free space” execution remain Phase 10 work. Phase 9’s “free N GB” control only selects eligible oldest originals for explicit manual queueing.
- Packaging as a `.deb`, multi-camera support, network/cloud features, and media repair remain out of scope.

## Risks or decisions requiring user approval

- No new decision is required. Manual hardware acceptance is still appropriate before release, particularly archive throughput on the target laptop while idle.

## Next phase

Phase 10 is ready to begin only after approval.
