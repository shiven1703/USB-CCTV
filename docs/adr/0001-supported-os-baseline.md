# ADR 0001: Supported OS baseline

## Context

USB CCTV Recorder is a local desktop application for one USB webcam and microphone. Its worker, media engine, and power-inhibition design depend on Linux systemd, V4L2, PipeWire-Pulse or PulseAudio, and KDE integration.

## Decision

Support amd64 Kubuntu/Ubuntu 24.04 LTS as the initial baseline. On the verified target, use the camera's persistent `video-index0` identity and MJPEG 2560 × 1440 at 30 FPS physical input; reject its metadata-only sibling. Explicitly select the webcam microphone source rather than the Pulse server default. Validate every selected encoder in the target KDE session before recording support is implemented.

## Alternatives considered

- Support every Ubuntu release immediately.
- Build against a non-systemd Linux desktop.
- Treat FFmpeg encoder listing as proof of usable hardware acceleration.

## Consequences

The package and CI baseline will target Ubuntu 24.04 amd64. The application will capability-probe each target machine and will use a software fallback only after later phases validate its storage and reliability profile. The operating context must preserve the 90 GB managed ceiling and calculated effective cap; it must not treat total filesystem capacity as available recording space.

## Reversal conditions

Add another OS baseline only after its KDE, systemd, audio stack, V4L2 capture, packaging, and long-running recording behaviour have passed the same acceptance suite.
