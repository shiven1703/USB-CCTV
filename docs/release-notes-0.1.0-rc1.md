# USB CCTV Recorder 0.1.0-rc1 release notes

Status: **release approved by user on 2026-08-02; optional Phase 12 hardware limitations are documented.**

## Included

- Local single-camera MKV recording with configured persistent V4L2 camera identity and explicit
  Pulse microphone source.
- Segmented capture, safe finalization, FFprobe validation, SHA-256 checksums, manifests, and
  append-only event journals.
- On-demand systemd user worker with private Unix-socket control; closing the GUI does not stop an
  active recording.
- Suspend/idle inhibition, critical-battery safe stop, recovery journals, watchdog recovery,
  degradation, and quarantine for uncertain media.
- Library integrity/protection controls, manual archive transactions, derived share copies, and
  storage-governor safeguards.
- One amd64 Debian package containing the frozen application, KDE integration, and static
  on-demand user unit. Uninstall preserves user media and user data.

## Validation status

The automated and package validation passed. The user approved release while categorizing the
real-hardware soak, adversarial, archive-integrity, and controlled-storage validation as optional
limitations. Their status is documented in [the validation log](phase-12-validation-log.md).
