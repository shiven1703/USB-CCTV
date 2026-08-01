# Phase 5 Completion Report

## Delivered

- Static on-demand systemd user unit with `Restart=on-failure`, a 5-second restart delay, and a bounded rate of three starts per 60 seconds. Runtime data is private through `RuntimeDirectory=usb-cctv-recorder`, mode `0700`, and `UMask=0077`.
- A current-user Unix-domain socket at `$XDG_RUNTIME_DIR/usb-cctv-recorder/worker.sock`. It validates the private parent directory, socket type and owner, removes only verified stale sockets, checks `SO_PEERCRED`, and creates a mode-`0600` socket.
- The worker handles service `SIGTERM` by leaving its IPC loop and removing its socket. Active-recording finalization on system shutdown remains the explicit Phase 6 boundary.
- A length-framed, JSON, protocol-version-1 schema with no extensible payload fields. It supports only `status`, `start`, `stop`, `retry`, and `force_stop`; all requests require canonical UUID command IDs.
- A worker supervisor that owns the sole recording controller, caches command-ID results, rejects incompatible duplicate IDs, makes safe stop idempotent, reports duplicate starts as current state, and logs protocol version, command ID, state changes, force-stop use, and errors.
- Private worker-readable capture configuration persisted from validated setup selection. The worker resolves the persistent camera alias only when it starts a recording and still never receives device paths or FFmpeg settings through IPC.
- A systemd adapter using structured `systemctl --user` argv, plus a Qt background status reconnect. Closing the window never issues a stop request.
- Synthetic socket integration: start a recording, disconnect/reconnect a client, query active status, and safely stop the recording.

## Files changed

- `systemd/usb-cctv-recorder-worker.service`
- `src/usb_cctv_recorder/infrastructure/ipc/`
- `src/usb_cctv_recorder/infrastructure/systemd/user_service.py`
- `src/usb_cctv_recorder/worker/`
- `src/usb_cctv_recorder/infrastructure/ffmpeg/process.py`
- `src/usb_cctv_recorder/presentation/qt/main_window.py`, `bootstrap.py`, and `__main__.py`
- `tests/unit/test_phase_5_*.py` and `tests/integration/test_phase_5_socket_worker.py`
- `README.md`

## Verification

- Local systemd manuals and help were checked for `ExecStart=`, `Restart=`, `RestartSec=`, `RestartPreventExitStatus=`, `StartLimitIntervalSec=`, `StartLimitBurst=`, `RuntimeDirectory=`, `UMask=`, and `NoNewPrivileges=`. Local PySide6 API help was checked for `QThread`, `start`, and interruption support; socket API help was checked for Unix `bind`, `getsockopt`, and `SO_PEERCRED`.
- `systemd-analyze verify systemd/usb-cctv-recorder-worker.service` parsed the unit. It correctly reported that `/usr/bin/usb-cctv-recorder` is not executable in the development checkout; the executable is installed only by the deferred packaging phase.
- `systemd-run --user --wait --collect /usr/bin/true` passed in the target desktop user manager.
- Transient user-service recovery was exercised from this checkout: the worker returned `idle`, was killed with `SIGKILL`, restarted through `Restart=on-failure`, advanced `NRestarts` from 0 to 1, and returned `idle` through a new socket connection. The temporary unit was then stopped.
- Manual real-hardware acceptance passed: the configured camera and microphone started recording, a new client reconnected with `recording_av`, safe stop reached `completed`, and `NRestarts` remained unchanged. The user also closed and reopened the GUI during recording and confirmed it displayed `recording_av`.
- `make ci` passed: Ruff format/lint, mypy, 116 tests across unit/contract/integration/fault suites at 90.26% coverage, dependency audit, source/wheel build, and wheel verification.

## Deferred limitations

- The static unit is not installed by this source checkout; package-install lifecycle validation belongs to the later packaging phase. Synthetic socket integration does not require the physical webcam.
- Power inhibition, systemd SIGTERM finalization, hotplug/watchdog recovery, degraded capture, retention, archive, and library work remain deferred to their specified later phases.

## Stop gate

Phase 5 acceptance criteria passed and user approval was recorded. Phase 6 may begin only from
this clean committed baseline.
