# Phase 5 handover prompt

Implement **Phase 5 — Systemd user service and GUI/worker IPC** of `USB_CCTV_RECORDER_IMPLEMENTATION_PLAN.md`, and no later phase.

Before changing code, read `.codex/AGENTS.md` and the complete implementation plan. Confirm that the user-approved Phase 4 files are committed and that the worktree is clean. Read `docs/phase-4-completion-report.md` before design or implementation. Do not start from an uncommitted Phase 4 baseline.

Phase 0 through Phase 4 are complete and user-approved. Preserve these established facts and boundaries:

- Target baseline: Ubuntu 24.04.4 amd64, KDE Plasma 5.27.12/X11, Python 3.12.3, systemd 255, FFmpeg/ffprobe 6.1.1, PipeWire-Pulse, and `uv 0.12.1`.
- The target camera remains the persistent `/dev/v4l/by-id/usb-BC-250403-J_USB_2.0_Camera_2K_01.00.00-video-index0`; resolve it before recording and never persist a numeric `/dev/videoN` identity. Its `video-index1` sibling is metadata-only. The selected camera input is MJPEG, 2560 × 1440 at 30 FPS.
- The selected microphone remains the explicit mono 48 kHz Pulse source `alsa_input.usb-BC-250403-J_USB_2.0_Camera_2K_01.00.00-02.mono-fallback`; never use the audio-server default source.
- Phase 2 supplies the state machines, validated configuration, XDG paths, SQLite foundations, atomic manifests, append-only events, checksums, and private filesystem conventions.
- Phase 3 supplies device discovery/preflight and structured `shell=False` command execution. The target KDE preflight test passed.
- Phase 4 supplies validated FFmpeg/FFprobe adapters, safe segmented MKV creation, bounded process-group lifecycle handling, progress parsing, a headless foreground controller, manifest segment facts, and synthetic-media integration/fault tests. Do not replace it with a GUI-owned subprocess.
- Preserve inward dependencies: `domain` uses only the standard library; `application` may import `domain`; `infrastructure` implements application ports; Qt remains in `presentation`.

Implement only these Phase 5 deliverables:

- An on-demand systemd **user** service for the worker, including a bounded restart-on-failure policy that does not restart after a deliberate safe stop.
- A local Unix-domain socket IPC protocol under `$XDG_RUNTIME_DIR/usb-cctv-recorder/`, restricted to the current user.
- Versioned, schema-validated predefined requests and responses for `status`, `start`, safe `stop`, `retry`, and explicit last-resort `force-stop`.
- Command IDs and idempotent semantics where the protocol needs them, particularly safe stop. Reject malformed, unknown, oversized, or repeated-incompatible messages.
- Single-active-session enforcement in the worker. Starting an active session twice must return state, not launch another FFmpeg process.
- GUI reconnect/status integration sufficient for the existing application to show an existing worker status and explicit close-window behaviour that does not stop recording. Keep GUI subprocess ownership out of the design.
- Service/socket lifecycle cleanup, stale-socket handling, and diagnostic logging with protocol version, command ID, state changes, and failure context.

Do not implement power inhibition, shutdown finalization, device hotplug recovery, watchdog recovery, audio-only/video-only fallback, retention/storage governor, library/archive UI, package changes, or Phase 6+ functionality. Do not expose arbitrary executable invocation, shell commands, file paths, or FFmpeg argument strings through IPC.

Before using systemd, Unix-socket, or Qt APIs, verify every command-line option, unit directive, and API behavior against official documentation or the local command/API help. Keep every subprocess argv structured with `shell=False`. Re-check the Phase 0 user-manager capability (`systemd-run --user --wait --collect /usr/bin/true`) before claiming the service integration works on the target desktop.

Required automated coverage:

- Protocol parsing/serialization tests for each supported request and response, protocol-version rejection, unknown command rejection, missing/invalid fields, command-ID semantics, and maximum message size.
- Unix-socket permission and peer-access tests proving access is current-user-only; reject a stale, unsafe, or wrong-type socket path.
- Worker tests for status before start, normal start, safe-stop idempotency, retry state, explicit force-stop logging, second-start rejection, and process crash state.
- Service adapter tests for generated unit arguments/directives, manager failures, intentional-stop non-restart, bounded restart rate, and stale socket cleanup.
- GUI tests for reconnecting to an active worker and closing the GUI without sending a stop request.
- Integration tests that start an on-demand user worker, record synthetic media through the socket, close/reopen the GUI or client, query status, and safely stop. They must not require the physical webcam.
- Fault tests for malformed/oversized IPC frames, socket permission failure, worker crash, stale socket, and duplicate command delivery.

Run `make ci`, fix every failure, provide the prescribed Phase 5 completion report, and then stop for user approval. Do not begin Phase 6 in the same turn.
