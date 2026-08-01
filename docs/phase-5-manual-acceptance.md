# Phase 5 user-service acceptance

Start the temporary user service below from the repository root. It is equivalent to the
packaged worker service and enables the hardware acceptance check before the deferred package
phase:

```text
systemd-run --user --unit=usb-cctv-recorder-phase5-manual.service \
  --property=Restart=on-failure --property=RestartSec=1 --collect \
  --setenv=PYTHONPATH=$PWD/src \
  $PWD/.venv/bin/python -m usb_cctv_recorder --worker
```

The crash test does not open physical devices and refuses to crash a worker that reports an
active recording state:

```text
uv run python scripts/verify_phase_5_user_service.py \
  --unit=usb-cctv-recorder-phase5-manual.service
uv run python scripts/verify_phase_5_user_service.py \
  --unit=usb-cctv-recorder-phase5-manual.service --crash-test
```

Expected result: the crash test reports a new socket response and an incremented `NRestarts`
count within 15 seconds.

For real-hardware start and safe-stop acceptance, first configure the camera and microphone in
the GUI once. That saves the private worker configuration. Close the GUI, then run:

```text
uv run python scripts/verify_phase_5_user_service.py \
  --unit=usb-cctv-recorder-phase5-manual.service --command start
# Close and reopen the GUI: it must show recording_av and must not send Stop.
uv run python scripts/verify_phase_5_user_service.py \
  --unit=usb-cctv-recorder-phase5-manual.service --command stop
systemctl --user show usb-cctv-recorder-phase5-manual.service \
  --property=NRestarts --value
```

The start command opens the configured physical camera and microphone. The restart count must
not increase after safe stop. Send the command output and observed GUI status back for Phase 5
approval. Clean up afterwards:

```text
systemctl --user stop usb-cctv-recorder-phase5-manual.service
```

After packaging, repeat the same checks using `usb-cctv-recorder-worker.service` in place of
the temporary unit. That validates the installed static unit and `/usr/bin` executable.
