"""Phase 8 browse, diagnostics, and strictly read-only playback page."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSlider,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from usb_cctv_recorder.application.archive import ArchiveService
from usb_cctv_recorder.application.dto import LibraryDetails, LibraryFilter, LibraryItem
from usb_cctv_recorder.application.library import LibraryService

from ..library_model import LibraryTableModel


class _LibraryLoadThread(QThread):
    completed = Signal(object, int, bool)
    failed = Signal(str)

    def __init__(
        self,
        service: LibraryService,
        media_root: Path,
        filters: LibraryFilter,
        offset: int,
        limit: int,
        rebuild: bool,
    ) -> None:
        super().__init__()
        self._service = service
        self._media_root = media_root
        self._filters = filters
        self._offset = offset
        self._limit = limit
        self._rebuild = rebuild

    def run(self) -> None:
        try:
            if self._rebuild:
                self._service.rebuild(str(self._media_root))
            total = self._service.count(self._filters)
            items = self._service.page(self._filters, self._offset, self._limit)
            if not self.isInterruptionRequested():
                self.completed.emit(items, total, self._offset == 0)
        except Exception as error:  # Boundary: failures become visible diagnostics.
            if not self.isInterruptionRequested():
                self.failed.emit(str(error))


class _LibraryActionThread(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, action: Callable[[], LibraryItem]) -> None:
        super().__init__()
        self._action = action

    def run(self) -> None:
        try:
            item = self._action()
            if not self.isInterruptionRequested():
                self.completed.emit(item)
        except Exception as error:  # Boundary: preserve diagnostic information without a traceback.
            if not self.isInterruptionRequested():
                self.failed.emit(str(error))


class _LibraryDetailsThread(QThread):
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, service: LibraryService, item_id: str) -> None:
        super().__init__()
        self._service = service
        self._item_id = item_id

    def run(self) -> None:
        try:
            details = self._service.details(self._item_id)
            if not self.isInterruptionRequested():
                self.completed.emit(details)
        except Exception as error:  # Boundary: stale selections are ordinary during rebuild.
            if not self.isInterruptionRequested():
                self.failed.emit(str(error))


class LibraryPage(QWidget):
    """Qt is a catalogue client and media reader; it never owns authoritative files."""

    def __init__(
        self,
        service: LibraryService,
        media_root: Path,
        archive_selection_consumer: Callable[[tuple[str, ...]], None] | None = None,
        archive_service: ArchiveService | None = None,
    ) -> None:
        super().__init__()
        self._service = service
        self._media_root = media_root
        self._load_thread: _LibraryLoadThread | None = None
        self._action_thread: _LibraryActionThread | None = None
        self._details_thread: _LibraryDetailsThread | None = None
        self._archive_selection_consumer = archive_selection_consumer
        self._archive_service = archive_service
        self.model = LibraryTableModel()
        self.model.request_more.connect(self._load_more)

        self.date_filter = QLineEdit()
        self.date_filter.setPlaceholderText("YYYY-MM-DD")
        self.session_filter = QLineEdit()
        self.media_filter = _combo(("all", "original", "archive", "quarantine", "gap"))
        self.protected_filter = _combo(("all", "yes", "no"))
        self.validation_filter = _combo(("all", "verified", "unverified", "diagnostic"))
        self.gap_filter = _combo(("all", "has_gap", "gap", "none"))
        refresh = QPushButton("Refresh catalogue")
        refresh.clicked.connect(self.refresh)
        filters = QFormLayout()
        filters.addRow("Date", self.date_filter)
        filters.addRow("Session", self.session_filter)
        filters.addRow("Class", self.media_filter)
        filters.addRow("Protected", self.protected_filter)
        filters.addRow("Validation", self.validation_filter)
        filters.addRow("Gap", self.gap_filter)
        filters.addRow(refresh)

        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableView.SelectionMode.ExtendedSelection)
        self.table.selectionModel().currentRowChanged.connect(self._selected)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.status = QLabel("Catalogue not loaded")
        self.protect_button = QPushButton("Protect")
        self.unprotect_button = QPushButton("Unprotect")
        self.folder_button = QPushButton("Open containing folder")
        self.reverify_button = QPushButton("Re-verify integrity")
        self.archive_button = QPushButton("Archive selected")
        self.move_active_button = QPushButton("Move archive to active library (quality unchanged)")
        self.share_copy_button = QPushButton("Create derived share copy")
        self.play_button = QPushButton("Play")
        self.pause_button = QPushButton("Pause")
        self.previous_button = QPushButton("Previous segment")
        self.next_button = QPushButton("Next segment")
        for button, slot in (
            (self.protect_button, lambda: self._set_protected(True)),
            (self.unprotect_button, lambda: self._set_protected(False)),
            (self.folder_button, self._open_folder),
            (self.reverify_button, self._reverify),
            (self.archive_button, self._queue_archive_selection),
            (self.move_active_button, self._move_to_active_library),
            (self.share_copy_button, self._create_share_copy),
            (self.play_button, self._play_selected),
            (self.pause_button, self._player_pause),
            (self.previous_button, lambda: self._step_segment(-1)),
            (self.next_button, lambda: self._step_segment(1)),
        ):
            button.clicked.connect(slot)
            button.setEnabled(False)
        actions = QHBoxLayout()
        for button in (
            self.protect_button,
            self.unprotect_button,
            self.folder_button,
            self.reverify_button,
            self.archive_button,
            self.move_active_button,
            self.share_copy_button,
            self.play_button,
            self.pause_button,
            self.previous_button,
            self.next_button,
        ):
            actions.addWidget(button)

        self.video = QVideoWidget()
        # PulseAudio connection may block while a desktop audio service is unavailable. Playback
        # is optional, so defer that connection until the user explicitly presses Play.
        self.audio: QAudioOutput | None = None
        self.player: QMediaPlayer | None = None
        self.position = QSlider()
        self.position.setOrientation(Qt.Orientation.Horizontal)
        self.position.sliderMoved.connect(self._set_position)
        self.volume = QSlider()
        self.volume.setOrientation(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(100)
        self.volume.valueChanged.connect(self._set_volume)
        self.speed = _combo(("0.5×", "1×", "1.5×", "2×"))
        self.speed.setCurrentText("1×")
        self.speed.currentTextChanged.connect(self._set_speed)
        playback = QFormLayout()
        playback.addRow(self.video)
        playback.addRow("Position", self.position)
        playback.addRow("Volume", self.volume)
        playback.addRow("Speed", self.speed)

        layout = QVBoxLayout(self)
        layout.addLayout(filters)
        layout.addWidget(self.table)
        layout.addLayout(actions)
        layout.addWidget(self.details)
        layout.addLayout(playback)
        layout.addWidget(self.status)
        self.refresh()

    def refresh(self) -> None:
        self._start_load(0, self.model.page_size, rebuild=True)

    def _filters(self) -> LibraryFilter:
        protected_text = self.protected_filter.currentText()
        return LibraryFilter(
            date=self.date_filter.text() or None,
            session_id=self.session_filter.text() or None,
            media_class=_none_if_all(self.media_filter.currentText()),
            protected={"yes": True, "no": False}.get(protected_text),
            validation_state=_none_if_all(self.validation_filter.currentText()),
            gap_state=_none_if_all(self.gap_filter.currentText()),
        )

    def _load_more(self, offset: int, limit: int) -> None:
        self._start_load(offset, limit, rebuild=False)

    def _start_load(self, offset: int, limit: int, *, rebuild: bool) -> None:
        if self._load_thread is not None and self._load_thread.isRunning():
            return
        self.status.setText("Loading catalogue…")
        self._load_thread = _LibraryLoadThread(
            self._service, self._media_root, self._filters(), offset, limit, rebuild
        )
        self._load_thread.completed.connect(self._loaded)
        self._load_thread.failed.connect(self._failed)
        self._load_thread.start()

    def _loaded(self, items: object, total: int, reset: bool) -> None:
        if not isinstance(items, tuple) or not all(isinstance(item, LibraryItem) for item in items):
            self._failed("catalogue returned invalid rows")
            return
        typed_items = tuple(items)
        if reset:
            self.model.reset_items(typed_items, total)
        else:
            self.model.append_items(typed_items)
        self.status.setText(f"Showing {self.model.rowCount()} of {total} catalogue records")

    def _selected(self, *_ignored: object) -> None:
        item = self.model.item_at(self.table.currentIndex())
        is_media = item is not None and item.kind == "media"
        playable = is_media and item is not None and item.media_class in {"original", "archive"}
        for button in (self.protect_button, self.unprotect_button, self.reverify_button):
            button.setEnabled(is_media)
        for button in (
            self.folder_button,
            self.play_button,
            self.previous_button,
            self.next_button,
        ):
            button.setEnabled(playable)
        self.pause_button.setEnabled(playable)
        self.archive_button.setEnabled(
            bool(self._selected_archiveable_ids()) and self._archive_selection_consumer is not None
        )
        self.move_active_button.setEnabled(
            is_media
            and item is not None
            and item.media_class == "archive"
            and self._archive_service is not None
        )
        self.share_copy_button.setEnabled(
            is_media
            and item is not None
            and item.validation_state == "verified"
            and self._archive_service is not None
        )
        if item is None:
            self.details.clear()
            return
        self._details_thread = _LibraryDetailsThread(self._service, item.item_id)
        self._details_thread.completed.connect(self._details_loaded)
        self._details_thread.failed.connect(self._failed)
        self._details_thread.start()

    def _details_loaded(self, details: object) -> None:
        if isinstance(details, LibraryDetails):
            self.details.setPlainText("\n".join(f"{key}: {value}" for key, value in details.facts))

    def _set_protected(self, protected: bool) -> None:  # pragma: no cover - Qt action dispatch
        item = self.model.item_at(self.table.currentIndex())
        if item is None:
            return
        self._start_action(lambda: self._service.set_protected(item.item_id, protected))

    def _reverify(self) -> None:  # pragma: no cover - Qt action dispatch
        item = self.model.item_at(self.table.currentIndex())
        if item is not None:
            self._start_action(lambda: self._service.reverify(item.item_id))

    def _queue_archive_selection(self) -> None:  # pragma: no cover - Qt action dispatch
        if self._archive_selection_consumer is None:
            return
        selected = self._selected_archiveable_ids()
        if not selected:
            self._failed("Only verified, unprotected originals can be archived")
            return
        self._archive_selection_consumer(selected)
        self.status.setText(f"{len(selected)} original(s) selected for manual archive")

    def _selected_archiveable_ids(self) -> tuple[str, ...]:
        return tuple(
            item.item_id
            for index in self.table.selectionModel().selectedRows()
            if (item := self.model.item_at(index)) is not None
            and item.kind == "media"
            and item.media_class == "original"
            and not item.protected
            and item.validation_state == "verified"
            and item.segment_state in {"verified", "interrupted_verified"}
        )

    def _move_to_active_library(self) -> None:  # pragma: no cover - Qt action dispatch
        item = self.model.item_at(self.table.currentIndex())
        if item is not None and self._archive_service is not None:
            service = self._archive_service
            self._start_action(
                lambda: service.move_to_active_library(item.item_id, self._media_root)
            )

    def _create_share_copy(self) -> None:  # pragma: no cover - Qt action dispatch
        item = self.model.item_at(self.table.currentIndex())
        if item is None or item.file_path is None or self._archive_service is None:
            return
        service = self._archive_service
        destination = self._media_root / "share-copies" / Path(item.file_path).name
        self._start_action(lambda: service.create_share_copy(item.item_id, destination))

    def _start_action(self, action: Callable[[], LibraryItem]) -> None:  # pragma: no cover
        if self._action_thread is not None and self._action_thread.isRunning():
            return
        self._action_thread = _LibraryActionThread(action)
        self._action_thread.completed.connect(self._action_completed)
        self._action_thread.failed.connect(self._failed)
        self._action_thread.start()

    def _action_completed(self, item: object) -> None:
        if isinstance(item, LibraryItem):
            self.model.replace_item(item)
            self.status.setText("Catalogue action completed")

    def _open_folder(self) -> None:  # pragma: no cover - desktop integration
        item = self.model.item_at(self.table.currentIndex())
        if item is None or item.file_path is None:
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(item.file_path).parent))):
            self._failed("Desktop could not open the containing folder")

    def _play_selected(self) -> None:  # pragma: no cover - requires a desktop audio backend.
        item = self.model.item_at(self.table.currentIndex())
        if item is None or item.file_path is None:
            return
        if item.validation_state == "diagnostic":
            self._failed(f"Playback unavailable: {item.error_state or 'media has a diagnostic'}")
            return
        player = self._ensure_player()
        player.setSource(QUrl.fromLocalFile(item.file_path))
        player.play()

    def _player_pause(self) -> None:  # pragma: no cover - requires a desktop audio backend.
        if self.player is not None:
            self.player.pause()

    def _set_speed(
        self, label: str
    ) -> None:  # pragma: no cover - requires a desktop audio backend.
        if self.player is not None:
            self.player.setPlaybackRate(float(label.removesuffix("×")))

    def _set_position(
        self, position: int
    ) -> None:  # pragma: no cover - requires a desktop audio backend.
        if self.player is not None:
            self.player.setPosition(position)

    def _set_volume(
        self, value: int
    ) -> None:  # pragma: no cover - requires a desktop audio backend.
        if self.audio is not None:
            self.audio.setVolume(value / 100)

    def _ensure_player(
        self,
    ) -> QMediaPlayer:  # pragma: no cover - requires a desktop audio backend.
        if self.player is not None:
            return self.player
        audio = QAudioOutput(self)
        player = QMediaPlayer(self)
        player.setAudioOutput(audio)
        player.setVideoOutput(self.video)
        player.errorOccurred.connect(self._playback_error)
        player.mediaStatusChanged.connect(self._media_status_changed)
        player.positionChanged.connect(self.position.setValue)
        player.durationChanged.connect(self.position.setMaximum)
        audio.setVolume(self.volume.value() / 100)
        player.setPlaybackRate(float(self.speed.currentText().removesuffix("×")))
        self.audio = audio
        self.player = player
        return player

    def _step_segment(self, direction: int) -> None:  # pragma: no cover - view navigation
        current = self.table.currentIndex().row()
        playable_rows = [
            row
            for row, item in enumerate(self.model.items)
            if item.kind == "media" and item.media_class in {"original", "archive"}
        ]
        if current not in playable_rows:
            return
        target = playable_rows.index(current) + direction
        if 0 <= target < len(playable_rows):
            self.table.selectRow(playable_rows[target])
            self._play_selected()

    def _playback_error(self, _error: QMediaPlayer.Error, message: str) -> None:
        if self.player is not None:
            self.player.stop()
        self._failed(f"Playback failed: {message or 'unsupported or undecodable media'}")

    def _media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.InvalidMedia:
            self._failed("Playback failed: unsupported or undecodable media")

    def _failed(self, message: str) -> None:
        self.status.setText(f"Diagnostic: {message}")


def _combo(values: tuple[str, ...]) -> QComboBox:
    combo = QComboBox()
    combo.addItems(values)
    return combo


def _none_if_all(value: str) -> str | None:
    return None if value == "all" else value
