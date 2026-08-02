# Phase 11 clean-VM package acceptance

Run this checklist only on the supported Ubuntu 24.04.4 amd64 / KDE Plasma 5.27 X11 baseline.
It deliberately uses the release `.deb`, never the checkout or a development virtual environment.

## Build the upgrade artifact

Before snapshotting or creating the clean VM, build the normal initial package and a higher-version
package-manager upgrade fixture in separate output directories:

```text
uv run python scripts/build_deb.py
uv run python scripts/build_deb.py --package-version 0.1.1 \
  --artifact-directory dist/phase-11-upgrade
```

This produces:

```text
dist/usb-cctv-recorder_0.1.0_amd64.deb
dist/phase-11-upgrade/usb-cctv-recorder_0.1.1_amd64.deb
```

The fixture has a genuinely higher Debian version and exercises the package-manager upgrade path
without modifying the source version. Use a real newer release artifact instead when validating
application changes between two releases.

## Automated lifecycle and GUI smoke test

Copy the release `.deb` files and `scripts/verify_clean_vm_lifecycle.py` to the VM. From a normal
user's KDE/X11 terminal (not root), run:

```text
python3 verify_clean_vm_lifecycle.py /absolute/path/usb-cctv-recorder_0.1.0_amd64.deb \
  --upgrade-package /absolute/path/usb-cctv-recorder_0.1.1_amd64.deb
```

The `--upgrade-package` artifact must have a strictly newer Debian version. Omit it only when an
upgrade artifact is unavailable; the script then reports that the upgrade check was skipped.
It asks for `sudo` only to install/remove packages, and uses the installed frozen application for
synthetic AV media, ffprobe validation, and catalogue rebuild. It verifies that the worker is
inactive when idle, `static`, starts and stops on demand, and that media, the catalogue, and a
private configuration-retention sentinel survive upgrade, uninstall, and reinstall. It leaves its
media at `~/Videos/USB-CCTV-Recorder-phase-11-clean-vm-test/` for inspection. It also validates
the installed desktop entry and launches, closes, and relaunches the frozen GUI after initial
install, upgrade, and reinstall.

## Required manual KDE checks

1. Confirm **USB CCTV Recorder** is visibly present in the KDE application menu. (The automated
   check validates the desktop file and frozen GUI launch, but cannot observe the menu visually.)
2. Configure the actual test profile, start a real camera/microphone recording, close the GUI,
   reopen it, and safely stop the session.
3. Use the Library/Archive UI to archive one synthetic or short test recording. Verify original/
   archive relationships and media checksums remain intact.
4. After the automated upgrade, inspect the preserved real configuration and catalogue in the GUI.
   After reinstall, rebuild the catalogue in the UI and confirm the same recordings return without
   byte changes.

Do not run package upgrades or removal while an active recording exists. The package guard refuses
that operation for the invoking graphical user so the recording can be stopped and finalized first.
