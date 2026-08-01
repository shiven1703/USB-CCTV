# USB CCTV Recorder

USB CCTV Recorder is a local desktop recorder for one USB camera and microphone on
Ubuntu/KDE. It is being implemented in phases. Phase 6 adds runtime-only power protection to the
on-demand systemd user
worker boundary: a current-user-only Unix socket under `$XDG_RUNTIME_DIR/usb-cctv-recorder/`,
versioned closed commands (`status`, `start`, `stop`, `retry`, and `force_stop`), and a GUI
status reconnect that never owns or stops FFmpeg.

The setup GUI still does not own recording. The static service is installed by the later
packaging phase; its configured `Restart=on-failure` policy has a three-starts-per-minute
limit, while a safe stop completes the recording without entering a worker failure state.
The setup page writes validated capture settings to a private XDG configuration file that the
worker reads before it starts; IPC never accepts device paths or FFmpeg arguments. While recording,
the worker holds logind sleep/idle inhibitors and a shutdown-delay inhibitor, and reports power
protection plus AC/battery state through the existing status connection. The setup page defaults to
preventing suspend/hibernate and offers an explicit lid-close option. At 5% battery without AC,
the worker safely stops and finalizes the active segment. Recovery, library, archive, retention,
and package installation remain deferred.
Phase 4 uses the runtime-proven `libx264` software fallback; hardware and HEVC encoder
selection are not implemented.

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
