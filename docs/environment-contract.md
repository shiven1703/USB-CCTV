# Environment contract

This Phase 0 contract records the target KDE-session probe from 2026-08-01. Its operational checks and user approval are complete in commit `932a042`; Phase 1 is complete and approved in commit `27286ec`.

## Supported baseline decision

- OS baseline: Ubuntu 24.04.4 LTS (Noble), amd64, KDE Plasma 5.27.12, X11.
- Python: 3.12.3; systemd: 255; FFmpeg and ffprobe: 6.1.1.
- Audio: PipeWire 1.0.5 through PulseAudio compatibility.
- Camera: use the persistent `...video-index0` alias for USB 2.0 Camera 2K. Its transient probe path was `/dev/video2`.
- Reject the sibling `...video-index1` node (transient `/dev/video3`): it has no capture formats and is metadata-only.
- Physical input baseline: MJPEG, 2560 × 1440, 30 FPS. Do not select 2K YUYV, which is limited to 1 FPS.
- Microphone: explicitly select `alsa_input.usb-BC-250403-J_USB_2.0_Camera_2K_01.00.00-02.mono-fallback`, mono 48 kHz. Never use the audio server default source as a substitute.
- Default media location: `~/Videos/USB-CCTV-Recorder/`; its existing parent is probed without creating the media directory.

## Storage policy

The absolute application-managed ceiling is **90,000,000,000 bytes**. It is not a minimum-free-space requirement and supersedes the earlier 150 GB ceiling.

```text
effective_cap = max(0, min(
  user_configured_cap,
  90_000_000_000,
  current_managed_usage_bytes + currently_available_bytes
    - operating_system_reserve - emergency_finalization_reserve
))
```

Recalculate the cap before a session, segment, or archive transaction. On the probed system filesystem, approximately 104.2 GB available bytes, zero managed usage, a 20 GB operating-system reserve, and an 8 GB emergency-finalization reserve yield an initial effective cap of approximately **76.2 GB**. The cap must change with available space; it must never consume either reserve.

The plan targets three original-quality nights and seven total-history nights only when actual measured segment sizes make that feasible. The initial rate budgets are planning targets, not promises: approximately 1.65 GB/hour live and 0.85–0.95 GB/hour archived. Hardware encoder names listed by FFmpeg are candidates only; each must pass a later runtime smoke test before selection.

## Required approval evidence

The real, machine-specific report belongs under `.local/probes/` and is Git-ignored. The committed sample is sanitized and preserves only the target topology.

Run the probe from the logged-in KDE session with the webcam and microphone connected:

```text
python3 scripts/probe_environment.py --output .local/probes/environment-probe.json
```

Approval requires the report to show the selected capture and microphone sources, and Phase 0’s `uv`, transient-user-service, failed-unit, and inhibitor checks must pass. The probe is read-only except when `--output` explicitly writes the chosen report file.

The report’s configured logind values are not effective defaults; later power-inhibitor work must query and validate effective runtime behaviour.
