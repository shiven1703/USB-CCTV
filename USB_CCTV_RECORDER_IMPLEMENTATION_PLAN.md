# USB CCTV Recorder — AI Agent Implementation Plan

**Document purpose:** This file is the implementation contract for an AI coding agent. Follow it phase by phase. Do not redesign the product, broaden the scope, or skip quality gates unless the user explicitly changes the requirements.

**Product name:** USB CCTV Recorder  
**Primary platform:** Kubuntu / Ubuntu desktop with KDE Plasma, systemd, PipeWire-Pulse or PulseAudio, one USB webcam with microphone  
**Distribution target:** One installable `.deb` package  
**Runtime model:** Native Qt GUI plus an on-demand systemd user worker  
**Media engine:** FFmpeg / ffprobe  
**Primary language:** Python 3  
**UI toolkit:** PySide6 / Qt Widgets  
**Database:** SQLite  
**Recording container:** Matroska (`.mkv`)

## Current implementation state — 2026-08-02

**Current phase:** Phase 11 — `.deb` packaging and desktop integration (not started)
**Overall state:** **PHASE 10 COMPLETE AND USER-APPROVED; PHASE 11 MAY BEGIN ONLY FROM THE COMMITTED, CLEAN PHASE 10 BASELINE**

**Current storage requirement:** The complete application-managed footprint must fit within a hard 90 GB decimal ceiling. On the currently probed system drive, the initial effective cap is expected to be approximately 76.2 GB after default safety reserves.

Phase 0 implementation, operational checks, and user approval are complete in commit `932a042`. Phase 1 scaffolding, quality gates, CI, tests, and ADRs are complete in commit `27286ec` and approved by the user. Phase 2 domain, persistence, and storage foundations are complete and user-approved; its completion report is `docs/phase-2-completion-report.md`. Phase 3 device discovery, capability probing, and preflight UI are complete and user-approved; its completion report is `docs/phase-3-completion-report.md`. The target KDE session confirmed the Phase 3 preflight test. Phase 4 minimal headless recording, segmentation, and verification are complete and user-approved; its completion report is `docs/phase-4-completion-report.md`. Phase 5 systemd user-service ownership and GUI/worker IPC are complete and user-approved; its completion report is `docs/phase-5-completion-report.md`. Phase 6 power inhibition and shutdown finalization are complete and user-approved in commit `2e9c259`; its completion report is `docs/phase-6-completion-report.md`. Phase 7 capture watchdog, failure recovery, and degraded modes are complete and user-approved in commit `074209a`; its completion report is `docs/phase-7-completion-report.md`. Phase 8 library, playback, protection, integrity UI, and catalogue rebuild are complete and user-approved; its completion report is `docs/phase-8-completion-report.md`. Phase 9 manual archive and evidence-safe archive transactions are complete and user-approved; its completion report is `docs/phase-9-completion-report.md`. Phase 10 automatic retention and the dynamic storage governor are complete and user-approved; its completion report is `docs/phase-10-completion-report.md`. The user explicitly approved the 5% off-AC critical-battery policy, waived the Phase 6 manual KDE power checks, and deferred the Phase 7 multi-hour soak after a successful target-hardware unplug/reconnect acceptance. Begin Phase 11 only from the clean committed Phase 10 baseline.

### Confirmed target environment

```text
Operating system: Ubuntu 24.04.4 LTS (Noble)
Architecture: x86_64 / amd64
Desktop: KDE Plasma 5.27.12
Session type: X11
Python: 3.12.3
Systemd: 255
FFmpeg / ffprobe: 6.1.1
Audio server: PipeWire 1.0.5 through PulseAudio compatibility
Default media filesystem: ext4
Current free space at probe time: approximately 104.2 GB
Power: AC online, battery fully charged
```

### Confirmed capture hardware

```text
Camera friendly name:
  USB 2.0 Camera 2K

Persistent video capture identity:
  /dev/v4l/by-id/usb-BC-250403-J_USB_2.0_Camera_2K_01.00.00-video-index0

Current transient node at probe time:
  /dev/video2

Metadata-only sibling node to exclude:
  /dev/video3
  /dev/v4l/by-id/usb-BC-250403-J_USB_2.0_Camera_2K_01.00.00-video-index1

Preferred physical input mode:
  MJPEG, 2560x1440, 30 FPS

Confirmed webcam microphone source:
  alsa_input.usb-BC-250403-J_USB_2.0_Camera_2K_01.00.00-02.mono-fallback

Microphone format:
  mono, 48000 Hz
```

### Phase 0 unresolved gates

The implementing agent must not begin Phase 1 until all items below are evidenced in a revised Phase 0 completion report:

1. `uv --version` succeeds in the normal user session.
2. `systemd-run --user --wait --collect /usr/bin/true` succeeds.
3. `systemctl --user --failed` is captured; every failed unit is named and classified as relevant or irrelevant to this product.
4. A temporary `systemd-inhibit` test is visible in `systemd-inhibit --list`.
5. The real machine probe output is excluded from Git, preferably under `.local/probes/` with `.local/` in `.gitignore`.
6. The committed probe fixture is sanitized but still models the real capture-node/metadata-node topology, 2K MJPEG mode, and webcam microphone.
7. The environment contract removes the incorrect 160 GB minimum-free-space requirement.
8. Storage policy is defined as a dynamic effective cap bounded by the 90 GB product ceiling, actual filesystem availability, operating-system reserve, and emergency finalization reserve.
9. All existing Phase 0 tests still pass after those corrections.
10. The user explicitly approves the revised environment contract.

---

## 1. How the implementing agent must work

### 1.1 Phase-gated workflow

Implement exactly one phase at a time.

For every phase:

1. Read this complete document before changing code.
2. Confirm the phase scope and list the files expected to change.
3. Implement the smallest complete vertical slice required by that phase.
4. Add or update automated tests in the same change.
5. Run all quality gates defined for the phase.
6. Fix every failure before reporting completion.
7. Produce a concise phase report containing:
   - Delivered functionality.
   - Files added or changed.
   - Commands executed.
   - Test results.
   - Known limitations that are explicitly deferred to later phases.
   - Any requirement ambiguity or environment incompatibility.
8. Stop and wait for user approval before starting the next phase.

Do not combine phases to move faster. Do not implement later-phase features early unless they are unavoidable prerequisites, and document the reason before doing so.

### 1.2 Anti-hallucination rules

The agent must:

- Verify platform-specific APIs and command-line options against official documentation before using them.
- Never invent FFmpeg flags, systemd directives, D-Bus interfaces, Qt APIs, or Linux device paths.
- Never assume `/dev/video0` is stable.
- Never assume the microphone name or PipeWire/PulseAudio source index is stable.
- Never assume a hardware encoder exists.
- Never assume that a 2K webcam supports every advertised resolution and frame rate on Linux.
- Never silently substitute a camera, microphone, codec, resolution, or storage location.
- Never claim that recording was continuous if a gap occurred.
- Never claim that compressed media can be restored to original quality.
- Never delete an original recording until a separately created archive has been fully verified and committed.
- Never continue after a failed integrity check.
- Never use placeholder implementations, fake success responses, TODO-only methods, or tests that merely assert constants.
- Never catch and suppress broad exceptions without logging context and moving the state machine to an explicit failure state.
- Never use `shell=True` for subprocess execution.
- Never execute commands built from untrusted string concatenation.

If a required API or behaviour cannot be verified, stop that phase and report the exact uncertainty.

### 1.3 Definition of done for every phase

A phase is done only when:

- The phase acceptance criteria pass.
- Unit tests pass.
- Relevant integration tests pass.
- Formatting, linting, and static type checks pass.
- New public behaviour is documented.
- Error paths are tested, not only happy paths.
- No known critical or high-severity defect is left unresolved.
- The implementation remains inside the architecture boundaries in this document.

---

## 2. Product outcome

USB CCTV Recorder is a lightweight local desktop application for a single home USB webcam and microphone.

The user workflow is:

1. Install one `.deb` package.
2. Open **USB CCTV Recorder** from the KDE application menu.
3. Select a camera and microphone.
4. Select resolution, frame rate, segment duration, recording directory, and storage policy.
5. Test video and audio.
6. Start recording.
7. Leave the laptop connected to AC power.
8. Allow the display to turn off, KDE to lock, and HDMI to be disconnected.
9. Reopen the UI later to inspect status.
10. Stop safely.
11. Browse original and archived recordings from the Library.
12. Manually archive, protect, verify, preview, export, move, or delete recordings through the UI.

Closing the GUI must not stop an active recording.

---

## 3. Required behaviour

### 3.1 Recording

The application must:

- Record one selected USB camera and one selected microphone.
- Use FFmpeg for capture, synchronization, encoding, segmentation, and muxing.
- Write synchronized video and audio into MKV segments.
- Continuously write data to disk; “segment duration” only controls how often a file is finalized and a new one starts.
- Allow segment duration to be configured in the UI.
- Provide presets of 5, 10, 15, 30, 60, and 120 minutes.
- Allow a custom duration from 1 to 360 minutes.
- Default to 60 minutes.
- Disable segment-duration editing while recording.
- Safely finalize a shorter active segment when the user stops before the configured boundary.
- Never discard a valid short final segment.
- Use persistent device identity where Linux exposes one.
- Record session metadata, selected devices, media settings, timestamps, failures, restarts, gaps, and validation results.

### 3.2 Default quality and storage profile

The implementation must separate **camera input mode** from **encoded output profile**. The verified camera input and the initial encoded output target are not the same thing.

Confirmed target-camera input baseline:

- V4L2 input pixel format: MJPEG.
- Input resolution: 2560 × 1440.
- Input frame rate: 30 FPS as advertised by the device.
- Capture identity: persistent `/dev/v4l/by-id/...-video-index0` path.
- Reject the sibling `video-index1` metadata node because it exposes no usable capture formats.

Initial encoded-output target:

- Output resolution: 2560 × 1440 when sustained soak testing passes.
- Output frame rate: configurable, initially 12 or 15 FPS for overnight use.
- Preferred video codec: HEVC/H.265 only when a runtime smoke test proves the selected encoder is usable and stable.
- Fallback codec: H.264.
- Preferred audio: mono 48 kHz AAC at a sensible high-quality bitrate.
- No noise suppression.
- No noise gate.
- No automatic removal of quiet audio.
- No artificial night-vision, brightening, denoising, or frame interpolation in version 1.

Encoder names shown by `ffmpeg -encoders` are candidates, not proof of runtime usability. NVENC, QSV, VAAPI, and V4L2 M2M encoders must each pass an actual short encode test before selection. Until then, `libx264` and `libx265` are the only software fallbacks known to be present.

If 2K recording cannot be sustained reliably within the thermal and storage budget, prefer 1920 × 1080 with predictable storage over uncontrolled file growth or unstable capture. Never silently change the profile; surface and log every fallback.

Storage-oriented default targets for the verified laptop:

- Live original target: no more than approximately **1.65 GB per recorded hour** under the default profile, or approximately **13.2 GB for an eight-hour night**.
- Suggested initial live rate budget: approximately 3.3–3.5 Mb/s video plus 128 kb/s mono audio, subject to encoder smoke testing and visual-quality review.
- Archive target: approximately **0.85–0.95 GB per recorded hour**, or approximately **6.8–7.6 GB for an eight-hour night**, while stream-copying the authoritative audio whenever compatible.
- These are planning targets, not promises. The application must use actual measured bytes per hour after each completed segment.
- If the selected codec cannot preserve acceptable quality within the target rate, reduce output frame rate first, then resolution, rather than silently exceeding the storage policy.
- The preflight UI must show projected session size and projected retention before Start is enabled.

### 3.3 Low-light behaviour

The webcam has no night vision.

The application must:

- Show a real preview before recording.
- Warn that video may be dark or low-detail in insufficient light.
- Continue recording audio normally even when the room is dark.
- Never claim that resolution implies good low-light performance.
- Never alter the image in ways that could create misleading visual artefacts.

### 3.4 Power and desktop-session behaviour

While recording:

- Display dimming is allowed.
- Display power-off is allowed.
- KDE screen locking is allowed.
- HDMI disconnection is allowed.
- System suspend must be blocked.
- Hibernation must be blocked.
- Idle-triggered sleep must be blocked.
- Lid-triggered sleep must be optionally blocked through a UI setting.
- The worker must remain alive when the GUI closes.
- Logging out of the KDE session is not a version-1 guarantee unless explicitly validated.

The UI must display whether power inhibition is active.

### 3.5 Safe stop

The normal stop flow must:

1. Move the session state to `STOPPING`.
2. Ask FFmpeg to terminate gracefully.
3. Keep the UI in `FINALIZING` state.
4. Wait for FFmpeg to close the MKV container.
5. Validate the final file has expected streams and a plausible duration.
6. Update the session manifest and database.
7. Flush durable metadata.
8. Release power inhibitors.
9. Stop the worker only after finalization completes.
10. Report a clear success or failure result.

A force stop must be a separate, explicit, last-resort action and must be logged as abnormal.

### 3.6 Webcam and microphone failure recovery

The application must detect and handle:

- Physical webcam disconnect.
- USB re-enumeration under a different `/dev/videoN` path.
- Camera present but no fresh frames.
- Microphone present but no fresh audio packets.
- FFmpeg process exit.
- FFmpeg process alive but media progress stalled.
- Output file no longer growing.
- Worker process crash.

Required recovery behaviour:

- Preserve every already-finalized segment unchanged.
- Attempt to finalize the active segment.
- Never append recovered footage to an uncertain file.
- Start a new segment after recovery.
- Log last good video time, last good audio time, recovery attempts, recovery time, and exact documented gap.
- Continue audio-only capture when video fails but audio remains available.
- Continue video-only capture when audio fails but video remains available.
- Do not create fake black video or fake silent audio and mark it healthy.
- Keep retrying until the device returns, the user stops, storage becomes critical, or shutdown occurs.
- Quarantine an interrupted file that cannot be verified; never delete it automatically.

Default retry schedule:

- Retry 1 after 2 seconds.
- Retry 2 after 5 seconds.
- Retry 3 after 10 seconds.
- Retry 4 after 30 seconds.
- Further retries every 60 seconds.

Default health thresholds:

- Warn after 5 seconds without video progress.
- Declare video stalled after 15 seconds without video progress.
- Warn after 5 seconds without audio progress.
- Declare audio stalled after 15 seconds without audio progress.
- Declare pipeline stalled after 15 seconds without output-file growth.

These thresholds may be configurable under an Advanced page, but ordinary users should not need to modify them.

### 3.7 Storage and retention

The product has a **90 GB decimal absolute application-managed ceiling**:

```text
90 GB = 90,000,000,000 bytes
```

This ceiling covers the complete managed root, including originals, archives, thumbnails, manifests, the database, quarantined media, derived share copies kept inside the managed root, and temporary archive outputs. The application must not intentionally exceed it.

The 90 GB value is still a ceiling, not a requirement that 90 GB must always be available. Calculate the effective managed-storage cap for the selected filesystem at runtime:

```text
effective_cap = max(
    0,
    min(
        user_configured_cap,
        90_000_000_000,
        current_managed_usage_bytes
          + currently_available_bytes
          - operating_system_reserve
          - emergency_finalization_reserve
    )
)
```

Recalculate the result before every session, before starting a new segment, and before every archive transaction. Use current available bytes plus current managed usage; do not derive the cap from total filesystem capacity alone.

Baseline reserve policy outside the managed cap:

- Operating-system reserve: configurable, default **20 GB** when the media root is on the system filesystem.
- Emergency finalization reserve: configurable, default **8 GB**. It protects active-segment finalization, database durability, and failure recovery.
- Never allow recording, archiving, exporting, or thumbnail generation to consume either reserve.
- On a separate non-system recording filesystem, the UI may recommend a smaller OS reserve, but the emergency finalization reserve still applies.

The current target laptop had approximately 104.2 GB available at probe time. With default 20 GB and 8 GB reserves and no existing managed media, the initial effective cap is therefore approximately **76.2 GB**, not 90 GB. The cap must rise or fall dynamically as unrelated filesystem usage changes.

Default logical allocation inside the effective cap:

- Recent original recordings: **52%**.
- Verified compressed archives: **33%**.
- Metadata, thumbnails, quarantine, and managed share copies: **5%**.
- Archive-transaction headroom: **10%**.

These are policy targets rather than partitions. Protected evidence may exceed a pool target, but total managed usage must still remain under the effective cap. When protected evidence prevents safe operation, warn and refuse to start another session rather than deleting it.

Retention targets:

- Target the latest **3 nights** as original-quality recordings when measured segment sizes make that feasible.
- Target at least **7 nights of total history** across originals and verified archives when measured sizes make that feasible.
- Do not guarantee either target. Calculate feasibility from actual recent bytes per recorded hour and planned session length.
- Archive the oldest eligible unprotected originals once the original pool is under pressure, even if they are newer than three days, but only through the fully verified archive transaction.
- Delete only the oldest eligible unprotected verified archive when the archive pool or total cap requires deletion.

The UI must show:

- Configured ceiling, always no greater than 90 GB.
- Calculated effective cap.
- Why the effective cap is lower, if applicable.
- Current managed usage by category.
- Filesystem free space.
- Operating-system reserve.
- Emergency finalization reserve.
- Archive-transaction headroom.
- Recent measured bytes per recorded hour.
- Estimated next-session size.
- Estimated 3-night original requirement.
- Estimated 7-night total-history requirement.
- Estimated achievable original nights and total-history nights.
- Whether the selected profile fits the current policy.

Required enforcement rules:

- Use actual byte counts for enforcement; estimates are advisory only.
- Stop safely before the filesystem or managed cap is exhausted.
- Reserve enough space to finish the active segment before opening it.
- Never delete a recording currently being written.
- Never delete protected, partial, interrupted-unverified, or quarantined evidence automatically.
- Never delete an original before its separately created archive is fully decoded, verified, atomically published, catalogued, and durably committed.
- A hard-coded 160 GB or 150 GB requirement is forbidden.
- A user-configured value greater than 90 GB must be rejected by validation rather than silently accepted.

### 3.8 Archiving

The Library must support both automatic and manual archiving.

Manual actions through the UI:

- Archive one original.
- Archive multiple selected originals.
- Archive an entire session/night.
- Archive oldest originals until a requested amount of space is free.
- Move an original to another archive drive without compression.
- Pause, resume, or cancel queued archive work.
- Protect or unprotect an original or archive.
- Verify integrity again.
- Preview an original or archive directly.
- Move an archive into the active-library view without pretending quality was restored.
- Create a separate share copy.
- Delete with explicit confirmation.

Archive rules:

- Never transcode a source in place.
- Create a separate temporary file.
- Re-encode video only.
- Copy the original encoded audio stream unchanged when container compatibility permits.
- Preserve timestamps and duration.
- Validate container, video stream, audio stream, duration, and full decode.
- Calculate checksums.
- Publish the archive only after validation.
- Delete the original only after commit and only if policy allows.
- A failed archive must leave the original untouched.
- Archived MKV files must remain directly playable in the Library.
- “Restore” means move or reclassify; it does not recreate discarded image quality.
- A share copy must never replace or modify the authoritative original/archive.

### 3.9 Evidence integrity

Every evidence-affecting operation must be explicit and auditable.

Required controls:

- SHA-256 checksum for every finalized authoritative media file.
- Append-only JSONL event log per session.
- Session JSON manifest stored beside media.
- SQLite catalogue for browsing and retention decisions.
- Atomic publish on the same filesystem.
- Copy-verify-commit-delete workflow across filesystems.
- Full decode verification before deleting a source.
- Clear state labels: Original, Archived, Protected, Interrupted Verified, Interrupted Unverified, Derived Share Copy.
- No silent repair, overwrite, remux, or transcode of an authoritative file.
- All timestamps stored as timezone-aware wall-clock time and monotonic durations.

The application must never represent checksums as independent proof of when a recording was made. They only prove that the bytes have not changed since the checksum was calculated.

### 3.10 Packaging

The repository must build one release artifact:

```text
dist/usb-cctv-recorder_<version>_amd64.deb
```

The package must install:

- Application binary and bundled Python/PySide runtime.
- KDE desktop entry.
- Application icon.
- On-demand systemd user worker unit.
- Required shared assets and default configuration.
- Package metadata and declared system dependencies.

Runtime must not require:

- A terminal.
- A user-created virtual environment.
- Root privileges.
- A permanently running daemon when no recording or archive job is active.

---

## 4. Explicit non-goals for version 1

Do not implement these unless the user changes the scope:

- Multiple simultaneous cameras.
- Remote access.
- Cloud upload.
- Streaming.
- Motion detection.
- Face recognition.
- Object detection.
- Home Assistant integration.
- Mobile application.
- Browser server.
- Electron.
- Database server.
- Automatic legal conclusions.
- Certified sound-level measurement.
- Automatic determination of who created a sound.
- Automatic image enhancement presented as original evidence.
- Logout-independent PipeWire/PulseAudio capture unless specifically validated.

---

## 5. Architecture

Use Clean Architecture with strict inward dependency flow.

```text
Presentation (PySide6)
        |
        v
Application use cases and ports
        |
        v
Domain models, policies, and state machines

Infrastructure adapters implement application ports:
- FFmpeg
- ffprobe
- V4L2 / v4l2-ctl
- PipeWire-Pulse / PulseAudio
- systemd user manager
- logind inhibitors
- udev
- SQLite
- filesystem
- checksums
```

### 5.1 Dependency rule

- `domain` imports only Python standard-library modules.
- `application` may import `domain` and standard library.
- `infrastructure` may import `application` ports and `domain` types.
- `presentation` may import application-facing services and view models, but must not call FFmpeg, SQLite, systemd, udev, or filesystem logic directly.
- Qt imports must remain inside presentation code except for an explicitly approved Qt-specific IPC adapter.
- Infrastructure details must never leak into domain entities.

### 5.2 Suggested repository structure

```text
usb-cctv-recorder/
├── AGENTS.md
├── README.md
├── IMPLEMENTATION_PLAN.md
├── CHANGELOG.md
├── LICENSE
├── pyproject.toml
├── uv.lock
├── Makefile
├── src/
│   └── usb_cctv_recorder/
│       ├── __init__.py
│       ├── __main__.py
│       ├── bootstrap.py
│       ├── domain/
│       │   ├── entities.py
│       │   ├── value_objects.py
│       │   ├── states.py
│       │   ├── policies.py
│       │   ├── events.py
│       │   └── errors.py
│       ├── application/
│       │   ├── ports.py
│       │   ├── commands.py
│       │   ├── queries.py
│       │   ├── dto.py
│       │   ├── recording_service.py
│       │   ├── archive_service.py
│       │   ├── retention_service.py
│       │   └── recovery_service.py
│       ├── infrastructure/
│       │   ├── commands/
│       │   │   └── runner.py
│       │   ├── devices/
│       │   │   ├── video_discovery.py
│       │   │   ├── audio_discovery.py
│       │   │   └── udev_monitor.py
│       │   ├── ffmpeg/
│       │   │   ├── capabilities.py
│       │   │   ├── command_builder.py
│       │   │   ├── process.py
│       │   │   ├── progress_parser.py
│       │   │   └── verifier.py
│       │   ├── power/
│       │   │   ├── logind.py
│       │   │   └── power_status.py
│       │   ├── persistence/
│       │   │   ├── sqlite.py
│       │   │   ├── migrations/
│       │   │   ├── manifest.py
│       │   │   └── event_journal.py
│       │   ├── storage/
│       │   │   ├── atomic_files.py
│       │   │   ├── checksums.py
│       │   │   ├── usage.py
│       │   │   └── archive_transaction.py
│       │   ├── ipc/
│       │   │   ├── protocol.py
│       │   │   ├── server.py
│       │   │   └── client.py
│       │   └── systemd/
│       │       └── user_service.py
│       ├── worker/
│       │   ├── main.py
│       │   ├── supervisor.py
│       │   ├── watchdog.py
│       │   └── recovery_journal.py
│       └── presentation/
│           └── qt/
│               ├── app.py
│               ├── main_window.py
│               ├── view_models/
│               ├── pages/
│               │   ├── setup_page.py
│               │   ├── recording_page.py
│               │   ├── library_page.py
│               │   ├── archive_page.py
│               │   └── settings_page.py
│               ├── dialogs/
│               └── widgets/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── contract/
│   ├── fault_injection/
│   ├── fixtures/
│   └── manual/
├── packaging/
│   ├── pyinstaller/
│   └── debian/
├── systemd/
│   └── usb-cctv-recorder-worker.service
├── assets/
├── scripts/
├── docs/
│   ├── adr/
│   ├── architecture.md
│   ├── media-pipeline.md
│   ├── failure-recovery.md
│   ├── evidence-integrity.md
│   └── release-checklist.md
└── .github/workflows/
```

### 5.3 Application processes

The installed application has one executable with two modes:

```text
usb-cctv-recorder
usb-cctv-recorder --worker
```

- Normal mode starts the GUI.
- Worker mode runs under an on-demand systemd user service.
- Only one worker may own an active recording session.
- The GUI communicates with the worker through a local Unix domain socket.
- The socket must live under `$XDG_RUNTIME_DIR/usb-cctv-recorder/`.
- Socket permissions must restrict access to the current user.
- IPC messages must be versioned and schema-validated.
- IPC must expose only predefined commands; never expose arbitrary shell or executable invocation.

### 5.4 User data locations

Follow XDG conventions:

```text
Configuration: $XDG_CONFIG_HOME/usb-cctv-recorder/
State:         $XDG_STATE_HOME/usb-cctv-recorder/
Cache:         $XDG_CACHE_HOME/usb-cctv-recorder/
Runtime:       $XDG_RUNTIME_DIR/usb-cctv-recorder/
Default media: ~/Videos/USB-CCTV-Recorder/
```

Use restrictive permissions. The application must default to a process umask equivalent to `0077` for private user data unless the user explicitly chooses a shared directory.

---

## 6. Domain model and state machines

### 6.1 Recording session states

```text
IDLE
PREFLIGHT
STARTING
RECORDING_AV
RECORDING_AUDIO_ONLY
RECORDING_VIDEO_ONLY
DEGRADED
RECOVERING
STOPPING
FINALIZING
COMPLETED
FAILED
```

State transitions must be explicit and tested. Invalid transitions must raise a domain error.

### 6.2 Segment states

```text
OPEN
FINALIZING
VERIFIED
INTERRUPTED_VERIFIED
INTERRUPTED_UNVERIFIED
QUARANTINED
ARCHIVE_QUEUED
ARCHIVING
ARCHIVE_VALIDATING
ARCHIVED_VERIFIED
PROTECTED
DELETED
```

Do not infer state only from filenames. The database and manifest are authoritative, and files must be reconciled during recovery.

### 6.3 Archive job states

```text
QUEUED
PRECHECK
TRANSCODING
FLUSHING
VALIDATING
PUBLISHING
COMMITTED
PAUSED
CANCELLED
FAILED
```

A source may be deleted only after `COMMITTED` and only when the requested policy allows deletion.

### 6.4 Health states

Track video, audio, output, worker, and power independently:

```text
UNKNOWN
HEALTHY
WARNING
STALLED
DISCONNECTED
RECOVERING
FAILED
```

### 6.5 Time model

Use:

- Timezone-aware wall-clock timestamps for user-visible records and manifests.
- UTC timestamps for stable interchange.
- Monotonic clock values for durations, watchdog thresholds, retry schedules, and gap length.

Do not calculate gap duration by subtracting wall-clock timestamps that may jump because of time synchronization or daylight-saving changes.

---

## 7. Persistence and evidence files

### 7.1 Default media layout

```text
~/Videos/USB-CCTV-Recorder/
├── originals/
│   └── 2026-08-01/
│       └── session-221408/
│           ├── segment-20260801T221408+0200.mkv
│           ├── segment-20260801T231408+0200.mkv
│           ├── session.json
│           ├── events.jsonl
│           └── recorder.log
├── archives/
│   └── 2026/
│       └── 07/
│           └── 24/
│               ├── segment-20260724T230000+0200.archive.mkv
│               └── archive-manifest.json
├── quarantine/
└── .archive-work/
```

Filenames must be filesystem-safe and collision-resistant. Do not include `:` characters.

### 7.2 SQLite catalogue

The SQLite catalogue must contain at least:

- Session ID.
- Segment ID.
- Absolute or root-relative file path.
- Media class: original, archive, share copy, quarantine.
- Start time, end time, and monotonic duration.
- Resolution and frame rate.
- Video codec and audio codec.
- Stream validation flags.
- File size.
- SHA-256 checksum.
- Protected flag.
- Archive source relationship.
- Recording gap flags.
- Error state.
- Created, updated, archived, moved, and deleted timestamps.

Use migrations. Never modify schema manually in production code.

Recommended SQLite settings must be evaluated and documented. Use transactions for every multi-record state change. Do not rely on autocommit for evidence-affecting workflows.

### 7.3 Atomic file rules

For same-filesystem publication:

1. Write to a unique temporary file.
2. Flush application buffers.
3. `fsync` the file.
4. Close the file.
5. Atomically rename with `os.replace`.
6. `fsync` the parent directory.
7. Commit catalogue state.

For cross-filesystem movement:

1. Copy source to a temporary destination file.
2. Flush and `fsync` destination.
3. Verify byte count and checksum.
4. Atomically rename on the destination filesystem.
5. `fsync` destination directory.
6. Update catalogue in a transaction.
7. Delete source only after commit.
8. `fsync` source directory if deletion occurs.

Implement these rules once in infrastructure helpers. Do not duplicate ad hoc file-move logic in UI code.

---

## 8. Clean-code requirements

### 8.1 General

- Use explicit names that reflect domain meaning.
- Keep functions focused on one responsibility.
- Prefer composition over inheritance.
- Keep side effects at infrastructure boundaries.
- Use immutable value objects where practical.
- Use dataclasses for domain data when appropriate.
- Use enums for finite states.
- Inject clocks, command runners, repositories, and filesystem adapters for testability.
- Do not use module-level mutable singletons.
- Do not store application state in Qt widgets.
- Do not let the GUI own the recording process.
- Do not let worker threads update Qt widgets directly.
- Prefer signals and slots for GUI state updates.
- Keep blocking I/O off the Qt GUI thread.
- Use context managers for resources.
- Make cancellation explicit.
- Include structured context in logs.

### 8.2 Error handling

- Define domain-specific exception types.
- Convert infrastructure exceptions into application-level failures at boundaries.
- Log stack traces at process boundaries.
- Show user-safe error messages without exposing shell commands or secrets.
- Preserve machine-readable error codes for diagnostics.
- Never treat an FFmpeg exit code of zero as sufficient evidence that output is valid.
- Never treat a file existing as sufficient evidence that it is complete.
- Never treat the FFmpeg process being alive as sufficient evidence that capture is healthy.
- Never delete or overwrite on an uncertain state.

### 8.3 Subprocess best practices

- Pass arguments as a list.
- Never use `shell=True`.
- Capture stdout and stderr separately where needed.
- Use bounded line readers to avoid deadlock.
- Set process groups where required for controlled termination.
- Implement graceful terminate, timeout, then forced kill.
- Record the exact executable version and resolved path.
- Validate return codes.
- Redact paths only in user-facing logs if they contain sensitive information; preserve complete local diagnostic logs.

### 8.4 Qt best practices

- Construct and manipulate widgets only on the GUI thread.
- Use model/view components for recording lists rather than creating unbounded widget trees.
- Use `QAbstractTableModel` or `QAbstractListModel` for the Library.
- Use `QSettings` only for UI preferences if chosen; core configuration must remain available to the worker through a non-Qt repository.
- Use `QSaveFile` only in the presentation layer when appropriate; core evidence files must use the shared atomic-file adapter.
- Never block the event loop waiting for FFmpeg, ffprobe, checksum, archive, database migration, or device probes.
- Ensure every background operation has cancellation and progress reporting.
- Make close-window behaviour explicit: minimize to tray or close only the GUI, never silently stop recording.

### 8.5 Python quality gates

Use:

- Ruff for formatting and linting.
- Mypy for static type checking.
- Pytest for tests.
- pytest-qt for Qt tests.
- Coverage reporting.
- pip-audit or equivalent dependency audit in CI.

Recommended commands exposed through `make`:

```text
make bootstrap
make format
make lint
make typecheck
make test
make test-integration
make test-faults
make package
make verify-package
make ci
```

`make ci` must run every non-hardware automated quality gate.

---

## 9. Testing strategy

### 9.1 Test pyramid

- Many domain and application unit tests.
- Contract tests for every infrastructure adapter.
- Integration tests using synthetic media.
- Fault-injection tests using fake processes and fake device events.
- A smaller manual hardware acceptance suite.
- Long-running soak tests before release.

### 9.2 Synthetic media

Automated recording tests must not require a physical webcam.

Use FFmpeg-generated test sources for integration tests, such as:

- Test video source.
- Generated sine-wave audio.
- Short configurable durations.
- Controlled process exits.
- Controlled progress stalls.

The exact supported FFmpeg source syntax must be verified before implementation.

### 9.3 Required test categories

- State-machine transitions.
- Invalid transition rejection.
- Storage byte accounting.
- Retention selection order.
- Protected-item exclusion.
- Atomic file publication.
- Cross-filesystem copy verification.
- Checksum mismatch handling.
- Manifest recovery.
- SQLite migration and rollback.
- FFmpeg command construction.
- FFmpeg progress parsing.
- Graceful stop.
- Forced-stop escalation.
- Camera disconnect.
- Camera stall.
- Audio stall.
- FFmpeg crash.
- Worker crash recovery.
- Archive failure at every transaction stage.
- Disk-full simulation.
- UI actions and disabled states.
- IPC authentication by filesystem permissions and protocol validation.
- Package install, launch, upgrade, and uninstall.

### 9.4 Test evidence

Each phase report must include exact commands and summarized output. Do not write “tests pass” without showing which suites ran.

---

## 10. Phase implementation plan

# Phase 0 — Environment contract and requirement freeze

## Goal

Confirm the actual Kubuntu environment before implementation choices become fixed.

## Current state

**State:** `PASS`
**Approval:** `APPROVED_BY_USER_2026-08-01`
**Phase 1 permission:** `GRANTED_AFTER_PHASE_0_CHANGES_ARE_COMMITTED`

The Phase 0 probe implementation, parser tests, no-write tests, and operational checks pass. The first agent-run probe could not access the desktop hardware because it ran outside the correct session. That result is superseded for hardware discovery by a second probe executed from the active KDE session.

### Confirmed passed items

- Ubuntu 24.04.4 LTS and x86_64 baseline recorded.
- KDE Plasma 5.27.12 and X11 session recorded.
- Python 3.12.3 and systemd 255 recorded.
- FFmpeg and ffprobe 6.1.1 detected.
- PipeWire-Pulse audio environment detected.
- Target 2K webcam detected.
- Stable camera alias detected.
- Capture node `/dev/video2` distinguished from metadata-only `/dev/video3`.
- MJPEG 2560 × 1440 at 30 FPS detected.
- Webcam microphone detected as mono 48 kHz.
- AC-online power state detected.
- ext4 recording filesystem and approximately 104.2 GB available space recorded.
- No privileged system changes were made by the probe.

### Open issues and mandatory corrections

1. **Dependency manager not yet evidenced**
   - Capture the output of `uv --version`.
   - Install `uv` in the user environment if the command fails.

2. **Systemd user manager operational test not yet evidenced**
   - Run `systemctl --user --failed`.
   - Identify the failed unit previously reported by the desktop session.
   - Classify whether it affects transient services, D-Bus, PipeWire, or the recorder worker.
   - Run `systemd-run --user --wait --collect /usr/bin/true` and require success.

3. **Power-inhibitor test not yet evidenced**
   - Hold a temporary inhibitor with `systemd-inhibit --what=sleep:idle --mode=block`.
   - Confirm it is visible in `systemd-inhibit --list`.
   - Do not permanently modify KDE or logind settings.

4. **Probe-data repository hygiene not yet evidenced**
   - Store the real report under `.local/probes/`.
   - Add `.local/` to `.gitignore`.
   - Ensure committed fixtures remove username, hostname, home paths, device serials, and other machine-specific values while retaining topology and capability semantics.

5. **Storage contract is incorrect in the current completion report**
   - Remove the claimed 160 GB minimum-free-space requirement.
   - Adopt the dynamic effective-cap formula in Section 3.7.
   - Record that the current filesystem cannot expose the full 90 GB cap while default safety reserves are active; the initial effective cap is approximately 76.2 GB when managed usage is zero.
   - Adopt a calculated three-night original target and seven-night total-history target, neither of which is unconditional.

6. **Environment contract must be updated with the real hardware baseline**
   - Persistent camera identity and metadata-node exclusion.
   - MJPEG 2560 × 1440 at 30 FPS input baseline.
   - Explicit webcam Pulse source name and mono 48 kHz format.
   - Explicit rule not to rely on the audio server default source.
   - Explicit rule that hardware encoder availability requires runtime smoke tests.

## Deliverables

- `docs/environment-contract.md`.
- Read-only `scripts/probe_environment.py`.
- Sanitized committed sample probe output.
- Real local probe output excluded from Git.
- ADR for supported OS baseline.
- Updated 90 GB storage-cap and retention policy.
- Operational evidence for systemd user service and inhibitor support.
- Revised Phase 0 completion report.

## Probe requirements

Collect without changing system settings:

- Kubuntu/Ubuntu version.
- KDE Plasma version.
- Session type.
- CPU architecture.
- Python version.
- `uv` version.
- systemd version.
- FFmpeg and ffprobe versions.
- PipeWire/PulseAudio status.
- Available V4L2 device paths and persistent aliases.
- Capture-capable versus metadata-only V4L2 nodes.
- Webcam-supported pixel formats, resolutions, and frame rates.
- Available audio sources.
- Hardware video encoder candidates.
- Current AC/battery state.
- Current inhibitors.
- systemd user-manager state and failed units.
- Current suspend and lid policies where readable without privilege.
- Filesystem type and available space for the default media directory.

## Tests

- Unit-test parsing of all probe outputs using committed sanitized fixtures.
- Test missing-command behaviour.
- Test malformed-output behaviour.
- Test camera capture-node versus metadata-node classification.
- Test stable device aliases when `/dev/videoN` changes.
- Test webcam microphone selection independent of the default audio source.
- Test that the probe performs no writes unless `--output` is explicitly supplied.
- Test that any output path is the only path written.
- Run `python3 -m py_compile scripts/probe_environment.py`.
- Run the complete Phase 0 unit test suite.
- Run `git diff --check`.

## Acceptance criteria

Phase 0 is approved only when all criteria below pass:

- Target OS, desktop, session type, and architecture are explicitly recorded.
- Actual webcam and microphone appear in the probe output.
- Capture node and metadata-only node are correctly distinguished.
- MJPEG 2560 × 1440 at 30 FPS is recorded as the preferred physical input baseline.
- The stable webcam microphone source is recorded explicitly.
- FFmpeg and ffprobe are available.
- `uv --version` succeeds.
- A transient systemd user unit succeeds.
- Every failed systemd user unit is named and impact-classified.
- A temporary sleep/idle inhibitor can be acquired and observed.
- Real probe data is excluded from source control.
- Sanitized fixtures preserve the real topology without personal identifiers.
- The 90 GB dynamic storage-cap policy replaces the incorrect 160 GB minimum and supersedes the earlier 150 GB ceiling.
- All Phase 0 automated tests pass after corrections.
- No privileged system change is made.
- User approves the revised environment contract.

## Required revised completion report

The implementing agent must report:

```text
Phase 0 state: PASS or FAIL
Environment-contract revision: <commit or file summary>
uv: <version or failure>
Transient user-service test: PASS or FAIL
Failed user units: <names and impact classification>
Inhibitor test: PASS or FAIL
Camera: <persistent alias>
Rejected metadata node: <persistent alias>
Camera mode: <pixel format, resolution, FPS>
Microphone: <stable source name and format>
Filesystem free bytes: <actual>
Configured product cap, maximum 90 GB: <actual>
Calculated effective cap: <actual>
OS reserve: <actual>
Emergency finalization reserve: <actual>
Git hygiene: PASS or FAIL
Tests executed: <exact commands and outcomes>
User approval requested: YES
```

## Stop gate

Do not start Phase 1 until every acceptance criterion passes and the user explicitly approves Phase 0.

---

# Phase 1 — Project scaffolding and quality gates

## Goal

Create a maintainable repository with no product functionality beyond a launchable placeholder window and worker entrypoint.

## Entry conditions

Phase 1 may begin only when:

- Phase 0 state is `PASS`.
- User approval is recorded.
- `uv` is installed and its version is recorded.
- The updated environment contract is committed.
- The real probe report is Git-ignored.
- The 90 GB ceiling, dynamic effective-cap semantics, and revised retention targets are accepted.
- systemd user service and inhibitor smoke tests pass.

If any entry condition is false, stop without scaffolding Phase 1.

## Deliverables

- Repository structure from Section 5.
- `pyproject.toml` with pinned direct dependencies.
- Committed lockfile.
- Ruff configuration.
- Mypy configuration.
- Pytest configuration.
- Coverage configuration.
- Makefile with standard commands.
- Minimal PySide6 window titled **USB CCTV Recorder**.
- `--worker` CLI mode that starts and exits cleanly.
- CI workflow for automated non-hardware checks.
- Initial architecture ADRs.

## Tests

- Unit test imports all packages.
- Qt smoke test opens and closes the main window.
- CLI test verifies normal and `--worker` modes.
- CI runs on the supported Ubuntu baseline.

## Acceptance criteria

- `make ci` passes from a clean checkout.
- No circular imports.
- No Qt import in domain or application packages.
- No business logic in the main window.
- Application version is exposed in one canonical location.
- The package can be built as a Python distribution.

## Stop gate

Provide the phase report and wait for approval.

---

# Phase 2 — Domain model, state machines, persistence foundations

## Goal

Implement the product’s authoritative states and persistence contracts before integrating hardware.

## Deliverables

- Domain entities and value objects.
- Session, segment, archive, and health state machines.
- Application ports for devices, media process, power, persistence, clock, filesystem, and system service.
- SQLite schema and migration runner.
- Session manifest model.
- Append-only JSONL event model.
- Atomic file helper.
- Checksum service.
- XDG path resolver.
- Configuration model with validation.

## Tests

- Exhaustive state-transition tests.
- Invalid-transition tests.
- SQLite migration forward tests.
- Transaction rollback tests.
- Manifest round-trip tests.
- Append-only event tests.
- Atomic rename and simulated interruption tests.
- Cross-filesystem copy adapter tests using temporary mounted or mocked filesystems.
- SHA-256 known-vector tests.
- Timezone and monotonic-duration tests.

## Acceptance criteria

- Every state transition is explicit.
- Evidence files cannot be published through a non-atomic application path.
- Database and manifest models agree on identifiers and timestamps.
- Domain code has no infrastructure imports.
- All persistence tests pass after simulated process interruption.

## Stop gate

Wait for approval before device integration.

---

# Phase 3 — Device discovery, capability probing, and preflight UI

## Goal

Allow the user to select and test the real camera and microphone without starting a persistent recording.

## Deliverables

- Video-device discovery adapter.
- Persistent V4L2 identity resolution.
- Audio-source discovery adapter.
- FFmpeg encoder and muxer capability probe.
- Device DTOs with friendly and stable identifiers.
- Setup page with camera, microphone, resolution, frame rate, segment duration, output directory, and storage estimate.
- Short-lived preview/test mode.
- Microphone activity indicator.
- Clear unsupported-mode and missing-device errors.

## Rules

- Store stable device identifiers, never only numeric indexes.
- On the confirmed target system, prefer the `...video-index0` persistent alias and exclude `...video-index1`.
- Exclude any V4L2 node that exposes only metadata or no capture formats.
- Prefer MJPEG input for the confirmed 2K camera; never choose 2K YUYV because the device advertises only 1 FPS for that mode.
- Explicitly select the webcam Pulse source; never rely on the audio server default source.
- Preview must release devices before recording starts.
- Do not open the same camera through two independent consumers unless capability has been verified.
- Do not claim audio is valid merely because a device is listed; test packets or level activity.

## Tests

- Unit tests using recorded `v4l2-ctl` and audio-source fixtures.
- Contract tests for command execution.
- Tests for duplicate friendly names.
- Tests for changing `/dev/videoN` numbers with the same persistent identity.
- Tests for no camera, no microphone, permission denied, and unsupported mode.
- pytest-qt tests for selection persistence and disabled Start state.

## Acceptance criteria

- The target webcam and microphone are selectable.
- The UI displays only verified supported modes.
- A preview and audio test succeeds on the target laptop.
- Failed preflight prevents Start.
- The preview releases all devices cleanly.
- Segment duration validates 1–360 minutes.

## Stop gate

Wait for user confirmation that preview and microphone test work on real hardware.

---

# Phase 4 — Minimal recording worker and safe segmentation

## Goal

Implement a headless worker capable of reliable segmented MKV recording and safe stop, initially without systemd or automatic recovery.

## Deliverables

- FFmpeg command builder.
- FFmpeg process wrapper.
- Progress parser.
- Configurable MKV segmentation.
- Session-directory creation.
- Session manifest and event journal updates.
- Graceful stop and final-file verification.
- Synthetic-media integration test harness.
- CLI-only development control for start and stop.

## Rules

- FFmpeg command lines must be assembled from validated structured settings.
- Segment switching must not reopen the physical webcam and microphone.
- Force keyframes or use a segmentation strategy that produces bounded, playable segment intervals; verify behaviour experimentally.
- Always verify both video and audio streams when both were expected.
- A short final segment is valid.

## Tests

- 3-segment synthetic recording with short segment intervals.
- Stop during an active segment.
- Verify all completed and final short segments.
- Verify audio/video duration tolerance.
- Simulate FFmpeg non-zero exit.
- Simulate verifier failure.
- Simulate output path becoming unwritable.
- Confirm earlier finalized segments remain unchanged after later failure.

## Acceptance criteria

- Synthetic recording produces multiple playable MKV files.
- Normal stop produces a valid partial-duration final file.
- Every file contains synchronized expected streams.
- No file is deleted after verifier failure.
- Manifest accurately lists files and stop reason.
- All FFmpeg commands and versions appear in diagnostic logs.

## Stop gate

Wait for approval before background-service integration.

---

# Phase 5 — Systemd user service and GUI/worker IPC

## Goal

Make recording independent of the terminal and GUI process.

## Deliverables

- On-demand systemd user unit.
- Restart-on-failure policy with bounded restart rate.
- Unix-domain-socket IPC protocol.
- Worker status query.
- Start, safe stop, retry, and force-stop commands.
- GUI reconnect to an existing worker.
- Single-active-session enforcement.
- Tray behaviour or explicit “close UI, keep recording” behaviour.

## IPC rules

- Version every request and response.
- Validate all fields.
- Reject unknown commands.
- Restrict socket access to the current user.
- Include command IDs for idempotency.
- Never send executable command strings over IPC.

## Tests

- Start worker, close GUI, reopen GUI, query status.
- Close terminal and confirm worker remains active.
- Reject second active recording.
- Worker restart after controlled crash.
- Stale socket cleanup.
- Invalid and oversized IPC message handling.
- Stop command idempotency.

## Acceptance criteria

- Closing the GUI does not stop recording.
- Reopening the GUI shows the active session accurately.
- A worker crash is visible and recovered by systemd according to policy.
- A deliberate Stop does not trigger restart.
- IPC cannot invoke arbitrary commands.

## Stop gate

Wait for approval.

---

# Phase 6 — Power inhibition and shutdown finalization

## Goal

Prevent overnight suspension while allowing screen-off, lock, and HDMI disconnection.

## Deliverables

- logind power-inhibitor adapter.
- UI setting for suspend/hibernate protection.
- UI setting for lid-close protection.
- Power-protection status display.
- Shutdown preparation handling.
- AC/battery status adapter.
- Graceful critical-battery stop policy.

## Required inhibitor design

Use the official logind inhibitor API or a verified supported wrapper. Prefer holding explicit inhibitor handles for the worker lifetime.

Required semantics:

- Block sleep, idle-triggered suspend, and hibernate while recording.
- Optionally block lid-triggered suspend.
- Delay normal shutdown long enough to finalize the active segment, subject to system limits.
- Release all inhibitors after stop.
- Never permanently modify the user’s KDE power configuration.

## Tests

- Adapter unit tests with a fake D-Bus service.
- Inhibitor acquisition failure.
- Inhibitor loss during recording.
- Critical-battery state transition.
- SIGTERM/systemd stop finalization.
- Manual desktop test with display off and KDE locked.
- Manual test with HDMI disconnected.
- Manual lid-close test only when the user enables it.

## Acceptance criteria

- Screen power-off does not stop recording.
- KDE lock does not stop recording.
- HDMI disconnection does not stop recording.
- Configured idle timeout does not suspend the laptop while recording.
- Active file is finalized on normal service stop/shutdown request within the configured timeout.
- Inhibitors are released after recording ends.

## Stop gate

Wait for approval after real overnight-power tests.

---

# Phase 7 — Capture watchdog, failure recovery, and degraded modes

## Goal

Detect webcam, microphone, FFmpeg, and worker failures and recover without damaging existing evidence.

## Deliverables

- udev hotplug monitor.
- Video-progress watchdog.
- Audio-progress watchdog.
- Output-growth watchdog.
- Worker heartbeat.
- Recovery journal.
- Retry scheduler.
- Audio-only emergency capture.
- Video-only emergency capture.
- Gap and recovery event recording.
- Quarantine workflow for unverified interrupted files.
- UI failure state and “Retry now” control.

## Recovery rules

- Never append to an uncertain segment.
- Always create a new file after recovery.
- If the camera path changes, re-resolve by persistent identity.
- If the device identity is ambiguous, require user selection.
- Do not create endless empty segments during retry.
- Do not treat a dark static frame alone as a hard failure.
- Packet/timestamp progression is the primary health signal.

## Tests

Fault-injection tests must cover:

- Physical-device removal event.
- Device return under another path.
- No video progress with process alive.
- No audio progress with process alive.
- Output file stops growing.
- FFmpeg exits unexpectedly.
- Worker crashes and restarts.
- Recovery while Stop is requested.
- Five repeated disconnect/reconnect cycles.
- Audio-only emergency segment.
- Video-only emergency segment.
- Interrupted file verifies successfully.
- Interrupted file fails verification and moves to quarantine.

Manual hardware tests:

- Unplug and reconnect the actual webcam.
- Leave the webcam running for several hours.
- Verify the library displays exact gaps and recovered segments.

## Acceptance criteria

- Completed segments remain byte-for-byte unchanged through every fault test.
- Gaps are explicit and accurately timed using monotonic clocks.
- Recovery always starts a new segment.
- The UI never reports “continuous” after a gap.
- Unverified interrupted files are never archived or deleted automatically.
- Recording resumes automatically when the same device returns.

## Stop gate

Wait for approval after hardware fault testing.

---

# Phase 8 — Library, playback, protection, and integrity UI

## Goal

Provide a trustworthy local media library for originals, archives, gaps, and quarantined items.

## Deliverables

- Library page using a Qt model/view implementation.
- Filters by date, session, media class, protected state, validation state, and gap state.
- Integrated playback for originals and archives.
- Seeking, volume, playback speed, previous/next segment.
- Recording details panel.
- Protect and unprotect actions.
- Open-containing-folder action.
- Re-verify integrity action.
- Quarantine review UI.
- Catalogue rebuild command from media/manifests.

## Rules

- Playback must open the existing file read-only.
- Preview must never rewrite, remux, or “fix” an authoritative file.
- Do not silently omit files that the player cannot decode; show a diagnostic state.
- Protected items count against storage but are excluded from automatic deletion.

## Tests

- Model/view pagination or incremental loading.
- Filter combinations.
- Protect/unprotect persistence.
- Playback error handling.
- Database rebuild from fixture directories.
- Missing-file reconciliation.
- Checksum mismatch display.
- Gap timeline display.

## Acceptance criteria

- Originals and archives can be previewed directly.
- Protected state survives restart.
- Gaps and failures are easy to locate.
- A damaged or missing file is shown explicitly, not hidden.
- Database can be rebuilt without changing media bytes.

## Stop gate

Wait for approval.

---

# Phase 9 — Manual archive and evidence-safe archive transactions

## Goal

Allow the user to archive existing recordings through the UI without risking the source.

## Deliverables

- Manual archive-selection UI.
- Archive queue.
- Archive profile selection.
- Same-drive compressed archive transaction.
- Cross-drive move-without-compression transaction.
- Pause, resume, and cancel.
- Full archive validation.
- Archive/source relationship in database and manifest.
- “Move to active library” action.
- Share-copy action.
- Progress and detailed failure UI.

## Required transaction

For compressed archive:

1. Confirm source is closed, stable, and verified.
2. Confirm sufficient working space.
3. Lock the source against concurrent mutation.
4. Write a unique `.partial` archive.
5. Transcode video.
6. Copy audio unchanged when compatible.
7. Flush and close output.
8. `fsync` output and parent directory.
9. Run ffprobe validation.
10. Run full decode validation.
11. Compare duration and expected streams.
12. Calculate checksum.
13. Atomically publish final archive.
14. Commit database and manifest.
15. Delete source only when the selected policy allows it.

For cancellation:

- Stop FFmpeg gracefully where possible.
- Leave the original untouched.
- Keep or remove the partial file according to explicit recovery policy.
- Never publish a cancelled partial.

## Tests

Inject failure at every numbered transaction step.

Additional tests:

- Cancel during transcode.
- Destination disconnect during cross-drive copy.
- Checksum mismatch.
- Full-decode failure.
- Duration mismatch.
- Audio stream missing.
- Application crash and restart with partial archive.
- Share-copy creation without authoritative-file mutation.
- Move-to-active-library does not claim restored quality.

## Acceptance criteria

- No failure path deletes or modifies the source.
- Only fully validated archives appear as `ARCHIVED_VERIFIED`.
- Archive audio matches the original encoded audio packets when stream copy is used.
- Archives preview directly.
- Share copies are labelled derived and never replace evidence.
- Recovery after crash identifies every partial transaction.

## Stop gate

Wait for approval.

---

# Phase 10 — Automatic retention and dynamic storage governor

## Goal

Enforce the 90 GB ceiling and the lower runtime-calculated effective cap while targeting three recent original nights and seven total-history nights when feasible, without risking protected evidence.

## Deliverables

- Byte-accurate storage accounting.
- Session-size estimator.
- Three-night original-feasibility estimator.
- Seven-night total-history feasibility estimator.
- Automatic archive scheduler.
- Oldest-unprotected-archive deletion policy.
- Working-reserve enforcement.
- Storage-pressure warnings.
- Safe-stop trigger before disk exhaustion.
- UI storage dashboard.
- Manual “free N GB” operation.

## Policy order

When space is needed:

1. Remove stale safe temporary files only after recovery analysis.
2. Delete oldest unprotected derived share copies.
3. Delete oldest unprotected verified archives.
4. Queue eligible unprotected originals for archive when recording is not active.
5. Refuse to delete protected or recent original evidence.
6. Stop recording safely if sufficient space cannot be recovered.

Do not run heavy archive transcoding while active recording is healthy unless the user explicitly overrides the default and the platform has passed performance testing.

## Tests

- Exact 90,000,000,000-byte absolute-ceiling calculations.
- Effective-cap calculations on filesystems with less free space than the configured ceiling.
- Operating-system and emergency-finalization-reserve subtraction and zero clamping.
- Current-machine case: 104.2 GB available, zero managed usage, 20 GB OS reserve, and 8 GB emergency reserve yields approximately 76.2 GB effective cap.
- Default pool-ratio calculations: 52% originals, 33% archives, 5% metadata/quarantine/share copies, and 10% transaction headroom.
- Validation rejects configured caps greater than 90 GB.
- Filesystem free-space lower than application cap.
- Protected media consumes most capacity.
- No eligible deletion candidate.
- Archive queue under pressure.
- Temporary archive exceeds reserve.
- Concurrent library refresh and retention decision.
- Safe stop before segment boundary because of critical storage.
- No deletion of current, partial, protected, or unverified files.

## Acceptance criteria

- Managed usage never intentionally exceeds 90,000,000,000 bytes or the lower runtime effective cap.
- The default policy targets three recent original nights and seven total-history nights only when measured sizes demonstrate feasibility.
- Pool pressure may trigger earlier archiving, but never unsafe deletion or in-place transcoding.
- The worker reserves space to finalize the active segment.
- The application safely stops instead of filling the filesystem.
- Protected evidence is never automatically deleted.
- All automatic actions are visible in the audit trail.
- UI estimates clearly distinguish estimate from actual usage.

## Stop gate

Wait for approval.

---

# Phase 11 — `.deb` packaging and desktop integration

## Goal

Produce a one-install package that works without a terminal or development environment.

## Deliverables

- PyInstaller one-folder build configuration.
- Debian packaging metadata.
- Declared system dependencies such as FFmpeg and relevant Linux utilities.
- KDE desktop entry.
- Icons in standard sizes.
- On-demand systemd user unit installation.
- Post-install user-service reload handling.
- Clean uninstall behaviour that preserves user media by default.
- Upgrade/migration handling.
- Package verification script.

## Packaging rules

- Do not use PyInstaller one-file mode.
- Do not bundle user recordings into package paths.
- Do not run the application as root.
- Do not enable a permanent worker at login.
- Do not delete user recordings on uninstall.
- Clearly document which configuration and catalogue files remain after uninstall.
- Build on the supported Ubuntu/Kubuntu baseline and architecture.

## Tests

In a clean supported VM:

- Install `.deb`.
- Launch from KDE menu.
- Start synthetic recording.
- Close GUI and reopen.
- Stop safely.
- Run manual archive.
- Upgrade package while no recording is active.
- Verify database migrations.
- Uninstall package.
- Confirm user media remains.
- Reinstall and rebuild catalogue.

## Acceptance criteria

- One `.deb` is the only required user-delivered artifact.
- No terminal steps are required for normal use.
- Application starts from KDE menu.
- Worker starts on demand and remains off otherwise.
- Package dependencies resolve on the supported OS.
- Upgrade does not corrupt configuration, database, or media.

## Stop gate

Wait for approval before release validation.

---

# Phase 12 — Soak testing, adversarial validation, and release

## Goal

Prove reliability on the actual laptop and webcam before version 1.0.

## Deliverables

- Release candidate `.deb`.
- Completed manual acceptance checklist.
- 12-hour minimum soak report.
- Fault-injection report.
- Archive-integrity report.
- Storage-governor report.
- Release notes.
- Known limitations.
- Recovery guide.

## Required real-hardware tests

1. Record for at least 12 continuous hours.
2. Use the intended 2K or selected fallback profile.
3. Use the configured segment duration.
4. Allow screen power-off.
5. Lock KDE.
6. Disconnect HDMI.
7. Confirm no suspend.
8. Unplug and reconnect webcam.
9. Confirm device may return under a different path.
10. Simulate or trigger camera stall if safely possible.
11. Kill FFmpeg and verify recovery.
12. Kill the worker and verify systemd recovery.
13. Stop midway through a segment.
14. Verify every completed segment and final partial segment.
15. Archive selected recordings manually.
16. Interrupt an archive operation.
17. Restart and recover the archive queue.
18. Preview original and archive files.
19. Create a share copy.
20. Exercise storage-pressure behaviour in a controlled test directory.
21. Verify every gap and error is visible in the UI and manifests.
22. Verify completed original files are byte-identical before and after unrelated failures.

## Release acceptance criteria

- No unexplained recording gap.
- Every explained gap has accurate timestamps and reason.
- No completed segment corruption.
- No original lost during archive tests.
- No protected evidence automatically removed.
- Safe stop consistently finalizes the active segment.
- UI remains responsive.
- CPU temperature and load remain acceptable for overnight operation.
- Storage growth matches the configured budget closely enough for the retention policy.
- Package installs and runs on the supported target without developer tools.
- All automated and manual release tests pass.

---

## 11. UI requirements by page

### 11.1 Setup page

Required controls:

- Camera selector.
- Microphone selector.
- Resolution selector.
- Frame-rate selector.
- Codec/profile selector with recommended default.
- Segment-duration selector and custom value.
- Recording location.
- Prevent suspend/hibernate switch.
- Ignore lid closure switch.
- Storage-cap display.
- Three-night original-retention and seven-night total-history feasibility estimates.
- Test camera and microphone button.
- Start button.

Start must remain disabled until required preflight checks pass.

### 11.2 Active recording page

Display:

- Session start time.
- Current mode: video+audio, audio-only, video-only, recovering.
- Camera identity and health.
- Microphone identity and health.
- Last video progress age.
- Last audio progress age.
- Output growth status.
- Current segment name and elapsed time.
- Next segment boundary.
- Power-inhibitor status.
- AC/battery status.
- Managed storage usage.
- Filesystem free space.
- Recovery attempt count.
- Last gap.
- Last error.

Actions:

- Stop safely.
- Retry now.
- Select replacement device only when automatic identity matching is impossible.
- Force stop behind a confirmation dialog.

### 11.3 Library page

Display and filters:

- Originals.
- Archives.
- Protected items.
- Interrupted verified.
- Interrupted unverified.
- Share copies.
- Sessions with gaps.
- Date range.
- Validation status.

Actions:

- Preview.
- Protect/unprotect.
- Verify.
- Archive.
- Move.
- Export share copy.
- Open folder.
- Delete with confirmation.
- Show manifest and events.

### 11.4 Archive page

Display:

- Queue.
- Current job.
- Source size.
- Estimated archive size.
- Temporary space required.
- Progress.
- Validation phase.
- Expected space recovered.
- Errors and retry state.

Actions:

- Archive selected.
- Archive oldest until N GB free.
- Pause.
- Resume.
- Cancel.
- Retry failed.
- Discard safe partial after confirmation.

### 11.5 Settings page

Include:

- Default segment duration.
- Default recording profile.
- Storage cap, validated in the range allowed by policy and never above 90 GB.
- Original-retention target, default 3 nights.
- Total-history target, default 7 nights across originals and archives.
- Operating-system reserve.
- Emergency finalization reserve.
- Archive-transaction headroom.
- Archive profile.
- Archive-only-when-not-recording switch.
- Watchdog thresholds under Advanced.
- Retry policy under Advanced.
- Log location.
- Diagnostics export.

Do not expose settings that the application cannot validate safely.

---

## 12. Logging and diagnostics

Use structured logs with stable event names.

Required fields where applicable:

- Event ID.
- Session ID.
- Segment ID.
- Archive job ID.
- Wall-clock UTC timestamp.
- Local timestamp and timezone offset.
- Monotonic timestamp.
- Severity.
- Component.
- State before and after.
- Device stable ID.
- File path.
- Error code.
- Human-readable message.
- Exception type and stack trace in diagnostic logs.

Do not log audio/video content. Do not add telemetry or network reporting.

Provide a UI action to export a diagnostics bundle containing logs, manifests, environment report, and configuration, but not media unless the user explicitly selects it.

---

## 13. Security and privacy

- No network listener.
- No remote API.
- No telemetry.
- No cloud dependency.
- Runtime as the logged-in user.
- Restrictive file permissions.
- IPC restricted to the user session.
- Validate every path stays within the selected managed root unless the user explicitly chooses an export destination.
- Resolve symlinks before destructive operations.
- Prevent path traversal.
- Do not follow unexpected symlinks during retention deletion.
- Require explicit confirmation for destructive user actions.
- Keep authoritative media read-only to application features that do not need mutation.
- Prefer opening previews with read-only file handles.

---

## 14. Performance constraints

- GUI must remain responsive during recording, hashing, probing, archive, and library scans.
- Heavy archive work must pause by default when recording starts.
- Hash and verification work must be bounded and cancellable.
- Library loading must be incremental for large histories.
- Avoid reading entire media files into memory.
- Use streaming checksums.
- Use bounded log retention outside evidence manifests.
- Avoid polling faster than necessary.
- Do not create one thread per file.
- Cap worker concurrency; archive jobs run one at a time by default.

---

## 15. Required ADRs

Create Architecture Decision Records for at least:

1. PySide6 instead of Electron.
2. FFmpeg as the media engine.
3. MKV as the authoritative recording container.
4. Static on-demand systemd user service.
5. Unix socket IPC.
6. SQLite plus per-session manifests.
7. Clean Architecture dependency boundaries.
8. Archive transaction and source-deletion policy.
9. 90 GB storage governor, three-night original target, and seven-night total-history target.
10. Power-inhibitor strategy.
11. Hardware encoder selection and fallback.
12. Packaging as PyInstaller one-folder inside `.deb`.

Every ADR must include context, decision, alternatives, consequences, and reversal conditions.

---

## 16. Prohibited shortcuts

The implementing agent must not:

- Replace the background worker with a GUI-owned subprocess.
- Replace MKV with plain MP4 for authoritative live capture without a new approved ADR.
- Use a single multi-hour open file without segmentation.
- Delete originals immediately after FFmpeg returns success.
- Skip full-decode validation before source deletion.
- Use file modification time as the sole evidence timestamp.
- Store only `/dev/video0` or numeric PulseAudio indexes.
- Disable global USB autosuspend or system power management without explicit user approval and an ADR.
- Run the whole application as root.
- edit KDE power configuration permanently.
- Auto-select a different webcam or microphone without clear disclosure.
- Merge recovered segments silently.
- Hide recording gaps.
- Re-encode audio during archive unless stream copy is impossible and the user explicitly chooses a compatible derived copy.
- Call an archive “restored original.”
- Let test fixtures substitute for real-hardware release testing.

---

## 17. Final agent completion format

At the end of each phase, respond using this exact structure:

```markdown
# Phase <N> Completion Report

## Delivered
- ...

## Files changed
- ...

## Architecture compliance
- ...

## Tests executed
- `command`
  - Result: ...

## Acceptance criteria
- [x] ...
- [ ] ... — reason

## Known limitations deferred by plan
- ...

## Risks or decisions requiring user approval
- ...

## Next phase
Phase <N+1> is ready to begin only after approval.
```

Do not begin the next phase in the same response.

---

## 18. Final product quality bar

The product is acceptable only when it behaves conservatively under uncertainty:

- Preserve existing evidence.
- Finalize cleanly when possible.
- Quarantine rather than delete when uncertain.
- Show failures instead of masking them.
- Resume into a new file rather than appending to a questionable one.
- Use actual byte counts rather than optimistic storage estimates.
- Require validation before state changes become authoritative.
- Keep every destructive action auditable.

The core rule is:

> Never overwrite, transcode in place, publish an incomplete result, hide a recording gap, or delete an original before a separately created replacement has been fully verified and committed.
