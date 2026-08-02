# Phase 11 handover prompt

Implement **Phase 11 — `.deb` packaging and desktop integration** of
`USB_CCTV_RECORDER_IMPLEMENTATION_PLAN.md`, and no later phase.

Before changing code, read `.codex/AGENTS.md` and the complete implementation plan. Confirm the
user-approved Phase 10 implementation is the current committed `HEAD` and the worktree is clean.
Read `docs/phase-10-completion-report.md`, `docs/adr/0004-on-demand-systemd-user-worker.md`, and
`docs/adr/0012-pyinstaller-one-folder-deb.md` before design or implementation. Do not start from
an uncommitted Phase 10 baseline.

Phases 0 through 10 are complete and user-approved. Preserve these facts and boundaries:

- Target baseline: Ubuntu 24.04.4 amd64, KDE Plasma 5.27.12/X11, Python 3.12.3, systemd 255,
  FFmpeg/ffprobe 6.1.1, PipeWire-Pulse, and `uv 0.12.1`.
- Preserve the selected persistent camera identity and explicit Pulse microphone source. Never
  substitute a transient video node or default audio source.
- Phase 4 owns FFmpeg/ffprobe, finalized media verification, manifests, checksums, and event
  journals. Phase 5 owns worker IPC and the static on-demand systemd user-worker lifecycle.
  Phase 6 owns inhibition and critical-battery safe stop. Phase 7 owns recovery, gaps,
  quarantine, and degraded capture.
- Phase 8 owns the paged Qt Library, the derived SQLite catalogue, protected-state persistence,
  read-only playback, diagnostics, and catalogue rebuild. Phase 9 owns durable archive
  transactions and source/archive relationships. Phase 10 owns retention policy, storage
  accounting, and safe storage-pressure decisions.
- Preserve inward dependencies: `domain` is standard-library-only; `application` may import
  `domain`; infrastructure implements ports; presentation remains Qt-only.

Implement only the Phase 11 deliverables:

- A PyInstaller **one-folder** build configuration and a `.deb` that is the only user-delivered
  artifact.
- Debian metadata with accurately declared runtime dependencies, including FFmpeg and required
  Linux utilities not bundled by PyInstaller.
- A KDE desktop entry and appropriately sized standard icon assets.
- Installation of the existing static, on-demand systemd user unit, with post-install user-daemon
  reload handling. Do not enable the worker permanently at login.
- Clean uninstall behaviour: preserve all user recordings by default and document retained
  configuration and catalogue locations.
- Upgrade and migration handling when no recording is active.
- A package-verification script that exercises the built artifact without needing a development
  environment at normal-user runtime.

Apply these packaging constraints exactly:

- Do not use PyInstaller one-file mode and do not require a Python virtual environment after
  installation.
- Do not bundle user recordings into package paths, run the application as root, or make the
  worker a permanent login daemon.
- Do not delete user recordings during uninstall. Do not claim that user data is removed unless
  the user explicitly chooses a separate data-removal action.
- Keep the application and worker command paths relocatable within the installed package; preserve
  the Phase 5 IPC/service ownership model.
- Build and test on the supported Ubuntu/Kubuntu amd64 baseline. Do not implement Phase 12 soak
  testing, release approval, multi-camera, cloud/network, or media-repair work.

Before using PyInstaller, Debian packaging helpers, systemd user-service installation mechanisms,
or desktop-entry/icon formats, verify exact local support with their installed help/version output
or official documentation. Keep subprocess execution structured with `shell=False`. Do not use
root for normal application execution.

Required automated and clean-VM/package coverage includes:

- Building the one-folder executable and `.deb`, then validating artifact contents and declared
  dependencies.
- Installing the `.deb` in a clean supported VM; launching from the KDE menu; starting synthetic
  recording; closing and reopening the GUI; safely stopping; and running a manual archive.
- Verifying the worker starts on demand and remains off otherwise.
- Upgrading while no recording is active, preserving configuration, catalogue migrations, and
  media integrity.
- Uninstalling while preserving user media, then reinstalling and rebuilding the catalogue.
- Regressions for worker IPC, storage-governor audit/state persistence, and source/archive safety.

Run `make ci`, fix every failure, provide `docs/phase-11-completion-report.md`, and then stop for
user approval before Phase 12. Do not begin Phase 12 in the same turn.
