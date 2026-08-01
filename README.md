# USB CCTV Recorder

USB CCTV Recorder is a local desktop recorder for one USB camera and microphone on
Ubuntu/KDE. It is being implemented in phases. Phase 4 adds a foreground, headless
development recorder that builds a validated FFmpeg command, writes segmented MKV files,
verifies each completed file with FFprobe, and records a durable manifest and event trail.

The setup GUI still does not own recording. Background systemd operation, GUI controls,
IPC, power inhibition, recovery, library, archive, and retention work remain deliberately
deferred to later phases. Phase 4 uses the runtime-proven `libx264` software fallback;
hardware and HEVC encoder selection are not implemented.

## Development

Install the pinned development environment and run all non-hardware checks:

```text
make bootstrap
make ci
```

Launch the setup GUI with `uv run usb-cctv-recorder`. The hardware foreground development
control accepts only explicit camera and Pulse identities and is safely stopped with Ctrl-C:

```text
uv run usb-cctv-recorder --record --media-root /absolute/media/root \
  --camera /dev/v4l/by-id/<selected-video-index0> --microphone <selected-pulse-source>
```

For CI-only synthetic media, use `--synthetic-duration-seconds`; it never opens hardware.
