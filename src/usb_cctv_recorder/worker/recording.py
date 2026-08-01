"""Headless Phase 4 recording control; service ownership is deliberately deferred."""

from __future__ import annotations

import os
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from usb_cctv_recorder.domain.entities import RecordingSession
from usb_cctv_recorder.domain.states import SessionState
from usb_cctv_recorder.domain.value_objects import SegmentId, SessionId, UtcTimestamp
from usb_cctv_recorder.infrastructure.commands.runner import StructuredCommandRunner
from usb_cctv_recorder.infrastructure.ffmpeg.process import FfmpegProcess, ProcessResult
from usb_cctv_recorder.infrastructure.ffmpeg.verifier import FfprobeVerifier, MediaVerificationError
from usb_cctv_recorder.infrastructure.persistence.event_journal import (
    JournalEvent,
    JsonlEventJournal,
)
from usb_cctv_recorder.infrastructure.persistence.manifest import (
    ManifestSegment,
    ManifestStore,
    SessionManifest,
)
from usb_cctv_recorder.infrastructure.storage.atomic_files import AtomicPublishError
from usb_cctv_recorder.infrastructure.storage.checksums import Sha256Service


class RecordingFailure(RuntimeError):
    """A recording could not be made authoritative without risking existing segments."""


@dataclass(frozen=True, slots=True)
class StartedRecording:
    session_id: SessionId
    directory: Path
    arguments: tuple[str, ...]


class HeadlessRecordingController:
    """Owns one foreground development recording and verifies files as they close."""

    def __init__(
        self,
        media_root: Path,
        command_factory: Callable[[Path], tuple[str, ...]],
        *,
        process: FfmpegProcess | None = None,
        verifier: FfprobeVerifier | None = None,
        checksums: Sha256Service | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not media_root.is_absolute():
            raise ValueError("media root must be absolute")
        self._media_root = media_root
        self._command_factory = command_factory
        self._arguments: tuple[str, ...] = ()
        self._process = process or FfmpegProcess()
        self._verifier = verifier or FfprobeVerifier()
        self._checksums = checksums or Sha256Service()
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._session: RecordingSession | None = None
        self._directory: Path | None = None
        self._manifest_store = ManifestStore()
        self._journal: JsonlEventJournal | None = None
        self._manifest: SessionManifest | None = None
        self._verified_names: set[str] = set()

    @property
    def manifest(self) -> SessionManifest:
        if self._manifest is None:
            raise RecordingFailure("recording has not started")
        return self._manifest

    @property
    def session_directory(self) -> Path:
        if self._directory is None:
            raise RecordingFailure("recording has not started")
        return self._directory

    def start(self) -> StartedRecording:
        if self._session is not None:
            raise RecordingFailure("only one headless recording may be active")
        now = self._timestamp()
        session_id = SessionId.new()
        directory = self._create_session_directory(now)
        self._directory = directory
        self._arguments = self._command_factory(directory / "segment-%06d.mkv")
        self._journal = JsonlEventJournal(directory / "events.jsonl")
        self._session = RecordingSession(session_id, SessionState.IDLE, now)
        self._move_session(SessionState.PREFLIGHT)
        self._move_session(SessionState.STARTING)
        self._manifest = SessionManifest(session_id, SessionState.STARTING, now, now)
        self._save_manifest()
        self._append_event("session_starting", {"arguments": list(self._arguments)})
        self._write_diagnostic("ffmpeg_arguments=" + repr(self._arguments))
        self._write_diagnostic("ffmpeg=" + self._executable_diagnostic("ffmpeg"))
        self._write_diagnostic("ffprobe=" + self._executable_diagnostic("ffprobe"))
        try:
            self._process.start(self._arguments)
        except Exception as error:
            self._fail(f"FFmpeg start failed: {error}")
            raise RecordingFailure("FFmpeg could not be started") from error
        self._move_session(SessionState.RECORDING_AV)
        self._save_manifest()
        self._append_event("session_started", {"mode": "video_audio"})
        return StartedRecording(session_id, directory, self._arguments)

    def poll(self) -> ProcessResult | None:
        self._require_started()
        self._finalize_closed_segments(include_active=not self._process.is_running())
        if self._process.is_running():
            return None
        result = self._process.wait()
        if not result.graceful_stop_requested:
            self._fail(f"FFmpeg exited unexpectedly with return code {result.returncode}")
            raise RecordingFailure(self.manifest.failure_reason or "FFmpeg exited unexpectedly")
        return result

    def stop(self, graceful_timeout_seconds: float = 10) -> ProcessResult:
        self._require_started()
        if self._session is None:
            raise AssertionError("session unexpectedly absent")
        if self._session.state == SessionState.RECORDING_AV:
            self._move_session(SessionState.STOPPING)
        self._append_event("stop_requested", {"reason": "user_requested"})
        result = self._process.stop(graceful_timeout_seconds)
        self._move_session(SessionState.FINALIZING)
        self._save_manifest(stop_reason="user_requested")
        try:
            self._finalize_closed_segments(include_active=True)
        except RecordingFailure:
            raise
        if result.forced_kill:
            self._fail("FFmpeg required forced kill; active output is not authoritative")
            raise RecordingFailure(self.manifest.failure_reason or "forced kill")
        if result.returncode not in {0, 255}:
            self._fail(f"FFmpeg safe stop returned {result.returncode}")
            raise RecordingFailure(self.manifest.failure_reason or "FFmpeg safe stop failed")
        self._move_session(SessionState.COMPLETED)
        self._save_manifest(stop_reason="user_requested")
        self._append_event("session_stopped", {"returncode": result.returncode})
        return result

    def run_until_complete(self, poll_seconds: float = 0.1) -> ProcessResult:
        if poll_seconds <= 0:
            raise ValueError("poll interval must be positive")
        while self._process.is_running():
            self._finalize_closed_segments(include_active=False)
            time.sleep(poll_seconds)
        result = self._process.wait()
        self._finalize_closed_segments(include_active=True)
        if result.returncode != 0:
            self._fail(f"FFmpeg exited unexpectedly with return code {result.returncode}")
            raise RecordingFailure(self.manifest.failure_reason or "FFmpeg exited unexpectedly")
        self._move_session(SessionState.STOPPING)
        self._move_session(SessionState.FINALIZING)
        self._save_manifest(stop_reason="duration_completed")
        self._move_session(SessionState.COMPLETED)
        self._save_manifest(stop_reason="duration_completed")
        self._append_event("session_stopped", {"returncode": result.returncode})
        return result

    def _finalize_closed_segments(self, *, include_active: bool) -> None:
        candidates = sorted(self.session_directory.glob("segment-*.mkv"))
        if not include_active and candidates:
            candidates.pop()
        for path in candidates:
            if path.name in self._verified_names:
                continue
            try:
                verified = self._verifier.verify(path)
                digest = self._checksums.digest_file(path)
            except (MediaVerificationError, OSError) as error:
                self._fail(f"segment verification failed for {path.name}: {error}")
                raise RecordingFailure(
                    self.manifest.failure_reason or "segment verification failed"
                ) from error
            segment_id = str(SegmentId.new())
            segment = ManifestSegment(segment_id, path.name, verified.duration_seconds, digest)
            self._verified_names.add(path.name)
            self._save_manifest(
                segments=self.manifest.segments + (segment,),
                segment_ids=self.manifest.segment_ids + (segment_id,),
            )
            self._append_event(
                "segment_finalized",
                {
                    "segment_id": segment_id,
                    "filename": path.name,
                    "duration_seconds": verified.duration_seconds,
                    "sha256": digest,
                    "video_codec": verified.video_codec,
                    "audio_codec": verified.audio_codec,
                },
            )

    def _create_session_directory(self, now: UtcTimestamp) -> Path:
        local = now.value.astimezone()
        directory = (
            self._media_root
            / "originals"
            / local.strftime("%Y-%m-%d")
            / f"session-{local.strftime('%Y%m%dT%H%M%S%z')}-{str(SessionId.new())[:8]}"
        )
        directory.mkdir(mode=0o700, parents=True, exist_ok=False)
        return directory

    def _move_session(self, target: SessionState) -> None:
        if self._session is None:
            raise RecordingFailure("recording has not started")
        self._session = self._session.move_to(target)
        if self._manifest is not None:
            self._save_manifest()

    def _save_manifest(
        self,
        *,
        segments: tuple[ManifestSegment, ...] | None = None,
        segment_ids: tuple[str, ...] | None = None,
        stop_reason: str | None = None,
        failure_reason: str | None = None,
    ) -> None:
        if self._manifest is None or self._session is None:
            raise RecordingFailure("recording has not started")
        self._manifest = replace(
            self._manifest,
            state=self._session.state,
            updated_at=self._timestamp(),
            segments=self._manifest.segments if segments is None else segments,
            segment_ids=self._manifest.segment_ids if segment_ids is None else segment_ids,
            stop_reason=self._manifest.stop_reason if stop_reason is None else stop_reason,
            failure_reason=(
                self._manifest.failure_reason if failure_reason is None else failure_reason
            ),
        )
        try:
            self._manifest_store.save(self.session_directory / "session.json", self._manifest)
        except (AtomicPublishError, OSError) as error:
            raise RecordingFailure(f"unable to persist session manifest: {error}") from error

    def _append_event(self, event_type: str, payload: dict[str, object]) -> None:
        if self._journal is None:
            raise RecordingFailure("recording has not started")
        self._journal.append(JournalEvent(event_type, self._timestamp(), payload))

    def _fail(self, reason: str) -> None:
        if self._session is not None and self._session.state not in {
            SessionState.COMPLETED,
            SessionState.FAILED,
        }:
            self._move_session(SessionState.FAILED)
        if self._manifest is not None:
            self._save_manifest(failure_reason=reason)
        if self._journal is not None:
            self._append_event("session_failed", {"reason": reason})

    def _write_diagnostic(self, line: str) -> None:
        path = self.session_directory / "recorder.log"
        descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        try:
            os.write(descriptor, (line + "\n").encode("utf-8"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _executable_diagnostic(name: str) -> str:
        path = shutil.which(name)
        if path is None:
            return "unavailable"
        result = StructuredCommandRunner().run((path, "-version"))
        version = (
            result.stdout.splitlines()[0]
            if result.succeeded and result.stdout
            else "version unavailable"
        )
        return f"path={path} {version}"

    def _timestamp(self) -> UtcTimestamp:
        return UtcTimestamp(self._clock())

    def _require_started(self) -> None:
        if self._session is None:
            raise RecordingFailure("recording has not started")
