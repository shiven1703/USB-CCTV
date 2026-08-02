# Phase 12 release-validation log

This is the durable evidence ledger for the Phase 12 release candidate. Do not
mark a case passed from automated coverage or a previous phase report. Record
the actual command, start/end timestamps with offsets, configuration, evidence
paths, observed state transitions, and every unexpected result when a case is
run.

## Candidate identity

| Field | Value |
| --- | --- |
| Status | AUTOMATED BASELINE PASS; HARDWARE VALIDATION NOT STARTED |
| Source commit | `0906bb8620805cb806a940acfc6ad9ced4d18fbd` |
| Source ref | `development` |
| Baseline | Ubuntu 24.04.4 amd64; KDE Plasma 5.27.12/X11; Python 3.12.3; systemd 255; FFmpeg/ffprobe 6.1.1; PipeWire-Pulse |
| Capture identity | `/dev/v4l/by-id/usb-BC-250403-J_USB_2.0_Camera_2K_01.00.00-video-index0` |
| Capture input | MJPEG, 2560x1440, 30 FPS |
| Microphone source | `alsa_input.usb-BC-250403-J_USB_2.0_Camera_2K_01.00.00-02.mono-fallback` |
| Package | `dist/usb-cctv-recorder_0.1.0_amd64.deb` (final build 2026-08-02T20:19:42+02:00) |
| Package SHA-256 | `5f845d45e1db0cbb0bd95e2c5956878c08ac39e9fb8cb277f60a3b42e93ec19b` |
| Automated baseline | `make ci` passed on 2026-08-02; 226 tests, 90.08% coverage; formatting, lint, mypy, audit, package build, and package verification passed |
| Direct package verification | `UV_CACHE_DIR=/tmp/usb-cctv-uv-cache uv run python scripts/verify_package.py dist/usb-cctv-recorder_0.1.0_amd64.deb` passed 2026-08-02T20:20:30+02:00 |

## Rules for every run

- Use the persistent camera identity and the explicit microphone source above. Never use a
  `/dev/videoN` path or the default Pulse source as a substitute.
- Perform storage-pressure, archive-interruption, and fault tests only below a deliberately
  chosen controlled test media root. It must not contain production evidence.
- Before each disruptive case, save SHA-256 checksums, manifests, event journals, and the
  catalogue state. Compare completed originals after the case.
- Preserve failed, skipped, and environment-limited cases as failures of release acceptance
  unless the user explicitly approves a documented limitation.
- Store raw outputs outside Git (for example under `.local/phase-12/`) and record their paths
  here. Do not commit real camera identifiers, media, or private diagnostics.

## Manual acceptance checklist

| ID | Case | Status | Evidence to record |
| --- | --- | --- | --- |
| H-01 | At least 12 hours of continuous recording using the selected 2K profile or documented fallback and configured segment duration | WAIVED BY USER 2026-08-02 | User explicitly authorized skipping the long-running soak; no soak evidence exists |
| H-02 | Screen power-off, KDE lock, and HDMI disconnect do not suspend or stop capture | OPTIONAL — WAIVED BY USER 2026-08-02 | No new Phase 12 evidence; Phase 6 manual desktop acceptance was previously waived by the user |
| H-03 | Webcam unplug/reconnect, including changed transient path, recovers by persistent identity | OPTIONAL — WAIVED BY USER 2026-08-02 | No new Phase 12 evidence; Phase 7 target-hardware unplug/reconnect acceptance is documented |
| H-04 | Safe camera-stall exercise records a visible, explained recovery result | OPTIONAL — WAIVED BY USER 2026-08-02 | No Phase 12 hardware evidence |
| H-05 | Killing FFmpeg produces a recovered new segment and an explicit gap | OPTIONAL — WAIVED BY USER 2026-08-02 | Automated Phase 7 fault coverage only; no Phase 12 hardware evidence |
| H-06 | Killing the worker produces on-demand systemd recovery and an explicit gap | OPTIONAL — WAIVED BY USER 2026-08-02 | Automated/systemd recovery evidence only; no Phase 12 hardware evidence |
| H-07 | Mid-segment safe stop verifies all completed segments and the final partial segment | OPTIONAL — WAIVED BY USER 2026-08-02 | Automated Phase 4 coverage only; no Phase 12 hardware evidence |
| H-08 | Archive selected originals, interrupt work, restart/recover queue, preview both forms, and create a share copy | OPTIONAL — WAIVED BY USER 2026-08-02 | Automated Phase 9 and Phase 11 evidence only; no Phase 12 hardware evidence |
| H-09 | Controlled storage pressure reports errors/gaps in UI and manifests, safely stops when required, and preserves originals | OPTIONAL — WAIVED BY USER 2026-08-02 | Phase 10 controlled harness passed; no Phase 12 UI/manual evidence |
| H-10 | Clean supported-target package installation and normal GUI operation require no developer tools | PASS — inherited Phase 11 evidence | Supported KDE/X11 clean-VM lifecycle and current candidate frozen-runtime verifier passed |

## Required report sections

### Soak report

Status: **WAIVED BY USER 2026-08-02**

The user explicitly authorized skipping the long-running soak. No soak evidence exists, so this
remains a documented release limitation rather than a passed test.

### Fault-injection report

Status: **OPTIONAL — WAIVED BY USER 2026-08-02**

No new Phase 12 hardware fault evidence was collected. The user explicitly categorized this
validation as optional; automated prior-phase evidence remains available but is not equivalent to
a fresh hardware run.

### Archive-integrity report

Status: **OPTIONAL — WAIVED BY USER 2026-08-02**

No new Phase 12 archive run was collected. The user explicitly categorized this validation as
optional. Phase 9 automated transaction evidence and Phase 11 clean-VM archive acceptance remain
the available supporting evidence.

### Storage-governor report

Status: **OPTIONAL — WAIVED BY USER 2026-08-02**

No new Phase 12 storage run was collected. The user explicitly categorized this validation as
optional. The available Phase 10 controlled harness was:

```text
uv run python scripts/verify_phase_10_storage.py --base-directory /absolute/controlled-test-parent
```

## Release decision

Status: **RELEASE APPROVED BY USER 2026-08-02**

The automated baseline and candidate package verification pass. The user explicitly categorized
H-01 through H-09 as optional limitations and approved this release on 2026-08-02. These cases
are not passed and have no new Phase 12 evidence.
