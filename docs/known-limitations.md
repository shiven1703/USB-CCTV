# Known limitations

This document distinguishes product boundaries from release-validation status. A Phase 12 release
is blocked by any unmet required acceptance criterion, regardless of whether it appears here.

## Product boundaries

- One local USB camera and microphone only; no multi-camera capture.
- No remote access, cloud upload, streaming, telemetry, browser service, mobile client, motion
  detection, or automated image/audio interpretation.
- Authoritative footage is not repaired or enhanced. A verified archive is a distinct derived
  recording; it does not restore original image quality.
- Logout-independent PipeWire/PulseAudio capture is not a version-1 guarantee.
- Hardware encoders and HEVC are not selected without a runtime smoke test. The runtime-proven
  fallback is `libx264`.

## Operational limits

- The worker uses the configured stable camera alias and explicit microphone source. It refuses to
  silently substitute another camera or audio source.
- The 90 GB application ceiling is further reduced by live filesystem availability and configured
  operating-system and emergency-finalization reserves.
- The user must stop an active recording before package upgrade or removal.
- The 12-hour real-hardware soak and remaining Phase 12 adversarial/manual hardware checks were
  explicitly categorized as optional by the user on 2026-08-02. No new Phase 12 hardware evidence
  exists; see [the validation log](phase-12-validation-log.md).
