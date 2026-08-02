# Phase 8 Completion Report

## Delivered

- Paged Qt model/view Library tab for originals, archives, quarantined media, and explicit Phase 7 gaps.
- SQLite catalogue rebuild from manifests, recovery journals, and media paths without modifying media bytes.
- Durable protect/unprotect, integrity re-verification, diagnostics, details, folder launch, and read-only Qt playback controls.
- `usb-cctv-recorder --rebuild-catalogue --media-root /absolute/path` command.

## Evidence safety

Playback only passes an existing local-file URL to Qt multimedia. Re-verification uses the existing
SHA-256 and ffprobe verifier; a missing file, checksum mismatch, or verification failure remains a
visible diagnostic. Catalogue rebuild changes only derived SQLite state.

## Verification

- Local PySide6 API inspection confirmed `QMediaPlayer.setSource`, seeking, playback rate,
  `QAudioOutput.setVolume`, media-error signals, `QUrl.fromLocalFile`, and
  `QDesktopServices.openUrl`.
- Local `ffprobe -h full` confirmed the existing `-show_streams`, `-show_format`, and `-of` use.
- `make ci` — pass: Ruff, mypy, 166 automated tests (including Phase 4, 5, and 7 regressions),
  90.13% coverage, integration/fault suites, dependency audit, build, and wheel verification.

## Deferred

Archive transactions/queues, automatic retention, media repair, and all Phase 9+ work remain out
of scope.
