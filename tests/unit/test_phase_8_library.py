"""Phase 8 catalogue, integrity action, and paged Qt model coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtMultimedia import QMediaPlayer

from usb_cctv_recorder.application.dto import LibraryDetails, LibraryFilter, LibraryItem
from usb_cctv_recorder.application.library import LibraryService
from usb_cctv_recorder.infrastructure.ffmpeg.verifier import MediaVerificationError, VerifiedMedia
from usb_cctv_recorder.infrastructure.persistence.library_catalogue import SQLiteLibraryCatalogue
from usb_cctv_recorder.infrastructure.persistence.sqlite import SQLiteCatalogue
from usb_cctv_recorder.infrastructure.storage.checksums import Sha256Service
from usb_cctv_recorder.presentation.qt.library_model import LibraryTableModel
from usb_cctv_recorder.presentation.qt.pages.library_page import (
    LibraryPage,
    _LibraryActionThread,
    _LibraryDetailsThread,
    _LibraryLoadThread,
)


class _Verifier:
    def __init__(self, failure: str | None = None) -> None:
        self.failure = failure

    def verify(self, path: Path, **_kwargs: object) -> VerifiedMedia:
        if self.failure:
            raise MediaVerificationError(self.failure)
        return VerifiedMedia(path, 1.0, "h264", "aac")


def _catalogue(tmp_path: Path, verifier: _Verifier | None = None) -> SQLiteLibraryCatalogue:
    return SQLiteLibraryCatalogue(
        SQLiteCatalogue(tmp_path / "state" / "catalogue.sqlite"),
        verifier=verifier,  # type: ignore[arg-type]
    )


def _write_session(root: Path, *, missing: bool = False, with_gap: bool = True) -> Path:
    session = root / "originals" / "2026-08-02" / "session-fixture"
    session.mkdir(parents=True)
    media = session / "segment-000000.mkv"
    if not missing:
        media.write_bytes(b"original-media")
    manifest = {
        "schema_version": 1,
        "session_id": "6a96b607-08cb-4b72-b282-84b816ef6f5d",
        "state": "completed",
        "created_at": "2026-08-02T10:00:00+00:00",
        "updated_at": "2026-08-02T10:10:00+00:00",
        "segment_ids": ["segment-1"],
        "segments": [
            {
                "segment_id": "segment-1",
                "filename": media.name,
                "duration_seconds": 60.0,
                "sha256": Sha256Service().digest_file(media) if not missing else "expected",
            }
        ],
        "stop_reason": "user_requested",
        "failure_reason": None,
    }
    (session / "session.json").write_text(json.dumps(manifest))
    if with_gap:
        (session / "recovery.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "state": "recording_av",
                    "attempt": 1,
                    "retry_at_monotonic": None,
                    "gaps": [
                        {
                            "reason": "video_disconnected",
                            "started_at": "2026-08-02T10:01:00+00:00",
                            "ended_at": "2026-08-02T10:01:03+00:00",
                            "started_monotonic": 1.0,
                            "duration_seconds": 3.0,
                            "attempts": 1,
                            "last_good_video_monotonic": 0.9,
                            "last_good_audio_monotonic": 1.0,
                        }
                    ],
                }
            )
        )
    return media


def test_catalogue_rebuild_filters_gaps_and_reconciles_missing_media(tmp_path: Path) -> None:
    root = tmp_path / "media"
    _write_session(root)
    quarantined = root / "quarantine" / "fixture" / "broken.mkv"
    quarantined.parent.mkdir(parents=True)
    quarantined.write_bytes(b"quarantined")
    catalogue = _catalogue(tmp_path)

    assert catalogue.rebuild(root) == 2
    assert catalogue.count(LibraryFilter()) == 3
    assert len(catalogue.page(LibraryFilter(media_class="original"), 0, 10)) == 1
    assert len(catalogue.page(LibraryFilter(media_class="quarantine"), 0, 10)) == 1
    gap = catalogue.page(LibraryFilter(gap_state="gap"), 0, 10)[0]
    assert gap.kind == "gap"
    assert dict(catalogue.details(gap.item_id).facts)["Reason"] == "video_disconnected"
    assert catalogue.page(LibraryFilter(media_class="archive"), 0, 10) == ()

    (root / "originals" / "2026-08-02" / "session-fixture" / "segment-000000.mkv").unlink()
    catalogue.rebuild(root)
    item = catalogue.page(LibraryFilter(media_class="original"), 0, 10)[0]
    assert item.validation_state == "diagnostic"
    assert item.error_state == "missing_file"


def test_protection_survives_reload_and_rebuild(tmp_path: Path) -> None:
    root = tmp_path / "media"
    _write_session(root, with_gap=False)
    database = tmp_path / "state" / "catalogue.sqlite"
    catalogue = SQLiteLibraryCatalogue(SQLiteCatalogue(database))
    catalogue.rebuild(root)
    item = catalogue.page(LibraryFilter(), 0, 10)[0]

    assert catalogue.set_protected(item.item_id, True).protected
    catalogue._catalogue.close()
    reloaded = SQLiteLibraryCatalogue(SQLiteCatalogue(database))
    assert reloaded.page(LibraryFilter(protected=True), 0, 10)[0].item_id == item.item_id
    reloaded.rebuild(root)
    assert reloaded.page(LibraryFilter(protected=True), 0, 10)[0].item_id == item.item_id


def test_reverify_reports_checksum_mismatch_missing_and_decode_failure_without_mutation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "media"
    media = _write_session(root, with_gap=False)
    catalogue = _catalogue(tmp_path)
    catalogue.rebuild(root)
    item = catalogue.page(LibraryFilter(), 0, 10)[0]
    before = media.read_bytes()

    media.write_bytes(b"changed-media")
    mismatch = catalogue.reverify(item.item_id)
    assert mismatch.error_state == "checksum_mismatch"
    assert media.read_bytes() == b"changed-media"

    media.unlink()
    assert catalogue.reverify(item.item_id).error_state == "missing_file"

    media.write_bytes(before)
    failing = _catalogue(tmp_path / "decode", _Verifier("unsupported codec"))
    failing.rebuild(root)
    failing_item = failing.page(LibraryFilter(), 0, 10)[0]
    assert (
        failing.reverify(failing_item.item_id).error_state
        == "verification_failed: unsupported codec"
    )


def test_catalogue_uses_incremental_pages_and_combined_filters(tmp_path: Path) -> None:
    root = tmp_path / "media"
    _write_session(root, with_gap=False)
    archives = root / "archives" / "2026" / "08"
    archives.mkdir(parents=True)
    (archives / "archive.mkv").write_bytes(b"archive")
    catalogue = _catalogue(tmp_path)
    catalogue.rebuild(root)
    original = catalogue.page(LibraryFilter(media_class="original"), 0, 1)[0]
    catalogue.set_protected(original.item_id, True)

    filters = LibraryFilter(
        date="2026-08-02",
        media_class="original",
        protected=True,
        validation_state="verified",
        gap_state="none",
    )
    assert catalogue.count(filters) == 1
    assert len(catalogue.page(filters, 0, 1)) == 1
    assert catalogue.page(filters, 1, 1) == ()


def test_catalogue_rebuild_surfaces_unmanifested_and_interrupted_media(tmp_path: Path) -> None:
    root = tmp_path / "media"
    media = _write_session(root, with_gap=False)
    session = media.parent
    (session / "extra.mkv").write_bytes(b"partial")
    (session / "events.jsonl").write_text(
        json.dumps(
            {
                "event_type": "segment_interrupted_verified",
                "payload": {"filename": media.name},
            }
        )
        + "\nnot-json\n"
    )
    catalogue = _catalogue(tmp_path)
    catalogue.rebuild(root)
    originals = catalogue.page(
        LibraryFilter(session_id="6a96b607-08cb-4b72-b282-84b816ef6f5d"), 0, 10
    )
    assert {item.segment_state for item in originals} == {
        "interrupted_verified",
        "interrupted_unverified",
    }


def test_library_service_validates_pages_and_delegates(tmp_path: Path) -> None:
    root = tmp_path / "media"
    _write_session(root, with_gap=False)
    service = LibraryService(_catalogue(tmp_path))
    assert service.rebuild(str(root)) == 1
    item = service.page(LibraryFilter(), 0, 1)[0]
    assert service.count(LibraryFilter()) == 1
    assert service.details(item.item_id).item == item
    assert service.set_protected(item.item_id, True).protected
    with pytest.raises(ValueError, match="page offset"):
        service.page(LibraryFilter(), -1, 1)


def _item(*, item_id: str = "item", diagnostic: str | None = None) -> LibraryItem:
    return LibraryItem(
        item_id,
        "media",
        "session",
        "original",
        "/tmp/media.mkv",
        "2026-08-02T10:00:00+00:00",
        1.0,
        False,
        "diagnostic" if diagnostic else "verified",
        "none",
        "verified",
        diagnostic,
    )


def test_qt_table_model_requests_bounded_next_page() -> None:
    model = LibraryTableModel(page_size=1)
    model.reset_items((_item(item_id="first"),), total=2)

    requests: list[tuple[int, int]] = []
    model.request_more.connect(lambda offset, limit: requests.append((offset, limit)))
    model.fetchMore()
    assert requests == [(1, 1)]
    model.append_items((_item(item_id="second"),))
    assert model.rowCount() == 2
    assert not model.canFetchMore()


def test_playback_missing_and_unsupported_diagnostics_do_not_mutate_media(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    media = tmp_path / "invalid.mkv"
    media.write_bytes(b"not playable")

    class _Service:
        def rebuild(self, _root: str) -> int:
            return 1

        def count(self, _filters: LibraryFilter) -> int:
            return 1

        def page(
            self, _filters: LibraryFilter, _offset: int, _limit: int
        ) -> tuple[LibraryItem, ...]:
            return (
                LibraryItem(
                    "invalid",
                    "media",
                    "session",
                    "original",
                    str(media),
                    "2026-08-02T10:00:00+00:00",
                    1.0,
                    False,
                    "verified",
                    "none",
                    "verified",
                    None,
                ),
            )

        def details(self, _item_id: str) -> LibraryDetails:
            return LibraryDetails(_item(), ())

        def set_protected(self, _item_id: str, _protected: bool) -> LibraryItem:
            return _item()

        def reverify(self, _item_id: str) -> LibraryItem:
            return _item()

    page = LibraryPage(LibraryService(_Service()), tmp_path)  # type: ignore[arg-type]
    qtbot.addWidget(page)
    qtbot.waitUntil(lambda: page.model.rowCount() == 1)
    page.table.setCurrentIndex(page.model.index(0, 0))
    before = media.read_bytes()
    # The error callback is the unit boundary; invoking a platform media backend for corrupt
    # bytes is a manual integration concern and can block on unavailable codecs.
    page._playback_error(QMediaPlayer.Error.FormatError, "unsupported codec")
    assert "Playback failed: unsupported codec" in page.status.text()
    assert media.read_bytes() == before

    page.model.replace_item(_item(item_id="invalid", diagnostic="missing_file"))
    page.table.setCurrentIndex(page.model.index(0, 0))
    page._play_selected()
    assert "Playback unavailable: missing_file" in page.status.text()


def test_library_service_threads_and_page_handlers_cover_success_and_diagnostics(
    qtbot: pytest.QtBot, tmp_path: Path
) -> None:
    item = _item()

    class _Service:
        def rebuild(self, _root: str) -> int:
            return 1

        def count(self, _filters: LibraryFilter) -> int:
            return 1

        def page(
            self, _filters: LibraryFilter, _offset: int, _limit: int
        ) -> tuple[LibraryItem, ...]:
            return (item,)

        def details(self, _item_id: str) -> LibraryDetails:
            return LibraryDetails(item, (("Path", "x"),))

        def set_protected(self, _item_id: str, protected: bool) -> LibraryItem:
            return item

        def reverify(self, _item_id: str) -> LibraryItem:
            return item

    service = LibraryService(_Service())  # type: ignore[arg-type]
    loaded: list[object] = []
    loader = _LibraryLoadThread(service, tmp_path, LibraryFilter(), 0, 1, True)
    loader.completed.connect(lambda *values: loaded.append(values))
    loader.run()
    assert loaded
    action = _LibraryActionThread(lambda: item)
    actions: list[object] = []
    action.completed.connect(actions.append)
    action.run()
    assert actions == [item]
    details_thread = _LibraryDetailsThread(service, item.item_id)
    details: list[object] = []
    details_thread.completed.connect(details.append)
    details_thread.run()
    assert details

    page = LibraryPage(service, tmp_path)
    qtbot.addWidget(page)
    qtbot.waitUntil(lambda: page.model.rowCount() == 1)
    page._loaded("bad", 1, True)
    assert "invalid rows" in page.status.text()
    page._loaded((item,), 2, False)
    assert page.model.rowCount() == 2
    page._action_completed(item)
    page._details_loaded(LibraryDetails(item, (("Fact", "value"),)))
    assert "Fact: value" in page.details.toPlainText()
    page._selected()
    page._set_speed("2×")
    assert page.player is None
    page._player_pause()
    page._media_status_changed(QMediaPlayer.MediaStatus.InvalidMedia)
    assert "unsupported" in page.status.text()
