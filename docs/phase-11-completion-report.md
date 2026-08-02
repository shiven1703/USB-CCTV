# Phase 11 Completion Report

## Delivered

- A pinned PyInstaller 6.21.0 one-folder build, installed inside the Debian package below
  `/usr/lib/usb-cctv-recorder/`, with a `/usr/bin/usb-cctv-recorder` launcher that resolves the
  application relative to its installed location.
- One amd64 release artifact at `dist/usb-cctv-recorder_0.1.0_amd64.deb`. It includes the frozen
  Python/PySide runtime, static on-demand user unit, KDE desktop entry, scalable SVG, and 16/24/
  32/48/64/128/256/512-pixel hicolor PNG icons.
- Accurate package dependencies: bootloader libraries derived with `dpkg-shlibdeps`, plus the
  externally invoked runtime tools `ffmpeg`, `pulseaudio-utils`, `v4l-utils`, and `systemd`.
- A static user unit with no `[Install]` section. Worker start reloads the current user manager
  before starting; `postinst` also reloads the invoking sudo user's manager when its session bus is
  available. Nothing enables the worker at login.
- The Setup-page recording control now starts the static user service before issuing the closed
  `start` IPC command, exposes **Stop safely** while active, and stops the idle user service after
  accepted safe-stop finalization. Closing the GUI still never stops a recording.
- Safe package lifecycle handling. The removal/upgrade guard refuses replacement for the invoking
  user if its worker is active, and uninstall does not remove configuration, catalogue, cache, or
  recordings. Installed and project documentation name all retained XDG/default-media locations.
- `scripts/verify_package.py`, which validates the built artifact and runs the extracted frozen
  launcher as a normal user to create/probe synthetic AV media and rebuild the derived catalogue.
- `scripts/verify_clean_vm_lifecycle.py`, a clean-KDE-VM lifecycle harness for installation,
  static/on-demand worker behaviour, frozen-GUI launch/close/reopen smoke checks, synthetic media,
  optional newer-package upgrade, uninstall preservation, reinstall, and catalogue rebuild.
- A supported-baseline clean-VM acceptance checklist covering KDE launch, on-demand worker,
  archive, no-active-recording upgrade, uninstall preservation, reinstall, and catalogue rebuild.

## Files changed

- `Makefile`, `pyproject.toml`, and `uv.lock`
- `packaging/pyinstaller/entrypoint.py` and `packaging/pyinstaller/usb_cctv_recorder.spec`
- `packaging/debian/control.in`, desktop entry, maintainer scripts, and `README.Debian`
- `scripts/build_deb.py`, `scripts/verify_package.py`, and `scripts/verify_clean_vm_lifecycle.py`
- `assets/usb-cctv-recorder.svg`
- `systemd/usb-cctv-recorder-worker.service` and the user-service adapter
- Packaging/bootstrap tests, `README.md`, and `docs/phase-11-clean-vm-checklist.md`

## Architecture compliance

- Packaging stays outside the `domain`, `application`, infrastructure adapters, and Qt
  presentation dependency boundaries.
- The existing GUI-to-static-user-worker IPC ownership model is retained. Packaging adds no GUI
  subprocess worker and no permanent login daemon.
- User configuration, SQLite catalogue, journals, and authoritative media remain in their existing
  XDG/user-selected locations and are never staged into the package.

## Tests executed

- `UV_CACHE_DIR=/tmp/usb-cctv-uv-cache make ci`
  - Result: PASS. Ruff format/lint, mypy, 226 tests, IPC integration, fault tests, dependency
    audit, Debian build, and extracted-artifact verifier passed. Coverage: 90.08%.
- `UV_CACHE_DIR=/tmp/usb-cctv-uv-cache uv run python scripts/verify_package.py dist/usb-cctv-recorder_0.1.0_amd64.deb`
  - Result: PASS. Validated control metadata, package contents, desktop entry, static worker unit,
    PNG assets, frozen `--help`, synthetic AV recording, ffprobe streams, and catalogue rebuild.
- `QT_QPA_PLATFORM=offscreen UV_CACHE_DIR=/tmp/usb-cctv-uv-cache uv run pytest --no-cov tests/unit/test_phase_11_packaging.py tests/unit/test_phase_11_clean_vm_script.py tests/unit/test_application_shell.py`
  - Result: PASS. 17 tests passed.
- Local tool support verified before implementation:
  - `uv --version`, `dpkg-deb --help`, `dpkg-shlibdeps --help`, `desktop-file-validate --help`,
    `xdg-icon-resource --help`, `systemctl --version`, and `systemd-analyze --help`.

## Acceptance criteria

- [x] One `.deb` is the only user-delivered artifact.
- [x] The package installs the frozen application, desktop entry, icons, static user unit, and
  declared runtime dependencies.
- [x] The packaged worker starts on demand and is never enabled permanently at login.
- [x] Normal-user package verification uses no development environment at runtime.
- [x] Upgrade/removal protects an active invoking-user worker and preserves all user data by default.
- [x] Automated regressions cover worker IPC, storage-governor persistence, archive/source safety,
  and package contracts.
- [x] Clean supported-VM KDE-menu, GUI recording continuity/safe stop, archive, upgrade, uninstall,
  and reinstall acceptance. The user ran the clean KDE/X11 lifecycle harness successfully with
  the `0.1.0` and `0.1.1` artifacts and confirmed the manual menu and UI checks.

## Known limitations deferred by plan

- Phase 12 real-hardware soak, adversarial validation, release approval, and release notes are not
  started.
- Multi-camera, network/cloud features, and media repair remain out of scope.

## Risks or decisions requiring user approval

- None for Phase 11. The user approved the completed clean-VM acceptance evidence.

## Next phase

Phase 12 is ready to begin from the committed Phase 11 baseline.
