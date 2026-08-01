# USB CCTV Recorder

USB CCTV Recorder is a local desktop recorder for one USB camera and microphone on
Ubuntu/KDE. It is being implemented in phases; Phase 1 provides only the launchable
Qt shell and a clean worker entrypoint.

## Development

Install the pinned development environment and run all non-hardware checks:

```text
make bootstrap
make ci
```

Launch the placeholder GUI with `uv run usb-cctv-recorder`; start the no-op worker
entrypoint with `uv run usb-cctv-recorder --worker`.
