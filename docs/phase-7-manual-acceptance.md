# Phase 7 webcam hotplug acceptance

First configure the selected camera and microphone once in the GUI. This writes the private worker
configuration; the setup page does not own the recorder process.

From the repository root, start the temporary user worker:

```text
systemd-run --user --unit=usb-cctv-recorder-phase7-manual.service \
  --property=Restart=on-failure --property=RestartSec=1 --collect \
  --setenv=PYTHONPATH=$PWD/src \
  $PWD/.venv/bin/python -m usb_cctv_recorder --worker
```

Then run the guided acceptance harness. It starts capture, prompts only for cable removal and
reconnection, verifies recovery evidence and finalized-media checksums, safely stops capture, and
writes an optional report outside Git:

```text
uv run python scripts/verify_phase_7_hotplug.py \
  --report .local/probes/phase-7-hotplug-report.json
```

Expected result: `"result": "pass"`, a documented gap, and `recording_av` after reconnect—even
when the same selected webcam returns as another `/dev/videoN`. The harness does not treat process
liveness or file existence as proof of success.

Stop the temporary worker when finished:

```text
systemctl --user stop usb-cctv-recorder-phase7-manual.service
```
