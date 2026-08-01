# USB CCTV Recorder

USB CCTV Recorder is a local desktop recorder for one USB camera and microphone on
Ubuntu/KDE. It is being implemented in phases. Phase 3 adds a setup page that discovers
V4L2 cameras by persistent `/dev/v4l/by-id` identity, discovers explicitly selected
Pulse sources, and runs a short camera/microphone test before enabling Start.

The setup page does not record yet: persistent recording is intentionally deferred to
Phase 4. FFmpeg encoder names shown by the capability probe are candidates only and
must still pass a runtime smoke test in that later phase.

## Development

Install the pinned development environment and run all non-hardware checks:

```text
make bootstrap
make ci
```

Launch the setup GUI with `uv run usb-cctv-recorder`; start the no-op worker entrypoint
with `uv run usb-cctv-recorder --worker`.
