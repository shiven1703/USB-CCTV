"""Real FFmpeg Phase 9 archive validation with synthetic AV media."""

from __future__ import annotations

import json
from pathlib import Path

from usb_cctv_recorder.application.dto import (
    ArchiveProfile,
    ArchiveProfileKind,
    ArchiveRequest,
    LibraryFilter,
)
from usb_cctv_recorder.infrastructure.commands.runner import StructuredCommandRunner
from usb_cctv_recorder.infrastructure.persistence.library_catalogue import SQLiteLibraryCatalogue
from usb_cctv_recorder.infrastructure.persistence.sqlite import SQLiteCatalogue
from usb_cctv_recorder.infrastructure.storage.archive_transaction import ArchiveTransactionManager
from usb_cctv_recorder.infrastructure.storage.checksums import Sha256Service


def test_real_ffmpeg_archive_is_playable_and_keeps_audio_stream(tmp_path: Path) -> None:
    root = tmp_path / "media"
    session = root / "originals" / "2026-08-02" / "session-fixture"
    session.mkdir(parents=True)
    source = session / "segment-000000.mkv"
    generated = StructuredCommandRunner(timeout_seconds=30).run(
        (
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x240:rate=10",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:sample_rate=48000",
            "-t",
            "1",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            "-f",
            "matroska",
            "-n",
            str(source),
        )
    )
    assert generated.succeeded, generated.stderr
    checksum = Sha256Service().digest_file(source)
    (session / "session.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "session_id": "6a96b607-08cb-4b72-b282-84b816ef6f5d",
                "state": "completed",
                "created_at": "2026-08-02T10:00:00+00:00",
                "updated_at": "2026-08-02T10:10:00+00:00",
                "segment_ids": ["segment-1"],
                "segments": [
                    {
                        "segment_id": "segment-1",
                        "filename": source.name,
                        "duration_seconds": 1.0,
                        "sha256": checksum,
                    }
                ],
                "stop_reason": "user_requested",
                "failure_reason": None,
            }
        )
    )
    catalogue = SQLiteLibraryCatalogue(SQLiteCatalogue(tmp_path / "state" / "catalogue.sqlite"))
    catalogue.rebuild(root)
    manager = ArchiveTransactionManager(catalogue)
    manager.enqueue(
        ArchiveRequest(("segment-1",), ArchiveProfile(ArchiveProfileKind.COMPRESSED), str(root))
    )

    job = manager.run_next()

    assert job is not None and job.state.value == "committed"
    archive = Path(job.destination_path)
    assert archive.is_file()
    verified = manager._verifier.verify(archive)
    manager._verifier.verify_full_decode(archive)
    assert verified.video_streams == 1
    assert verified.audio_streams == 1
    assert manager._verifier.audio_packet_hashes(source) == manager._verifier.audio_packet_hashes(
        archive
    )
    assert catalogue.page(LibraryFilter(media_class="archive"), 0, 1)[0].file_path == str(archive)
