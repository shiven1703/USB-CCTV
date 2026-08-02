# USB CCTV Recorder

USB CCTV Recorder is a local desktop recorder for one USB camera and microphone on
Ubuntu/KDE. It is being implemented in phases. Phases 7 and 8 add watchdog recovery and a
on-demand systemd user
worker boundary: a current-user-only Unix socket under `$XDG_RUNTIME_DIR/usb-cctv-recorder/`,
versioned closed commands (`status`, `start`, `stop`, `retry`, and `force_stop`), and a GUI
status reconnect that never owns or stops FFmpeg.

The setup GUI still does not own recording. The packaged static service has a three-starts-per-minute
limit, while a safe stop completes the recording without entering a worker failure state.
The setup page writes validated capture settings to a private XDG configuration file that the
worker reads before it starts; IPC never accepts device paths or FFmpeg arguments. While recording,
the worker holds logind sleep/idle inhibitors and a shutdown-delay inhibitor, and reports power
protection plus AC/battery state through the existing status connection. The setup page defaults to
preventing suspend/hibernate and offers an explicit lid-close option. At 5% battery without AC,
the worker safely stops and finalizes the active segment. During capture it monitors udev V4L2
events, video/audio progress, and output growth. A failure records a monotonic gap, finalizes or
quarantines the interrupted file, and starts a new AV, audio-only, or video-only segment after the
2/5/10/30/60-second retry schedule. Status exposes health, recovery, and a closed-protocol
**Retry now** action. Manual archive transactions, retention, and package installation are available.
Phase 4 uses the runtime-proven `libx264` software fallback; hardware and HEVC encoder
selection are not implemented. Phase 8 adds a paged Library tab for original, archive, gap, and
quarantined records. It displays damaged and missing files as diagnostics, supports durable
protect/unprotect and re-verification through the catalogue, and uses Qt's read-only media player
for original/archive playback. Playback never repairs, remuxes, or rewrites evidence.

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

Rebuild only the derived SQLite catalogue from existing media and manifests with:

```text
uv run usb-cctv-recorder --rebuild-catalogue --media-root /absolute/media/root
```

This command does not modify media bytes or manifests.

## Installation

The user-delivered release artifact is one amd64 Debian package:

```text
usb-cctv-recorder_<version>_amd64.deb
```

Install it through the KDE package installer. It brings the frozen Python/PySide application,
desktop entry, icons, and static on-demand user worker; it declares FFmpeg, PulseAudio utilities,
V4L utilities, and systemd as system dependencies. No virtual environment or terminal is needed
to launch **USB CCTV Recorder** from the KDE menu.

Removing the package preserves configuration, the derived catalogue, cache, and all media. See
the installed `/usr/share/doc/usb-cctv-recorder/README.Debian` for their exact XDG locations and
the safe upgrade/removal rule: stop an active recording before changing the package.
