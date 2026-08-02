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

    def __init__(self, service: LibraryService, media_root: Path) -> None:
        super().__init__()
        self._service = service
        self._media_root = media_root
        self._load_thread: _LibraryLoadThread | None = None
        self._action_thread: _LibraryActionThread | None = None
        self._details_thread: _LibraryDetailsThread | None = None
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
        self.table.selectionModel().currentRowChanged.connect(self._selected)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.status = QLabel("Catalogue not loaded")
        self.protect_button = QPushButton("Protect")
        self.unprotect_button = QPushButton("Unprotect")
        self.folder_button = QPushButton("Open containing folder")
        self.reverify_button = QPushButton("Re-verify integrity")
        self.play_button = QPushButton("Play")
        self.pause_button = QPushButton("Pause")
        self.previous_button = QPushButton("Previous segment")
        self.next_button = QPushButton("Next segment")
        for button, slot in (
            (self.protect_button, lambda: self._set_protected(True)),
            (self.unprotect_button, lambda: self._set_protected(False)),
            (self.folder_button, self._open_folder),
            (self.reverify_button, self._reverify),
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
            self.play_button,
            self.pause_button,
            self.previous_button,
            self.next_button,
        ):
            actions.addWidget(button)

        self.video = QVideoWidget()
        self.audio = QAudioOutput(self)
        self.player = QMediaPlayer(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.errorOccurred.connect(self._playback_error)
        self.player.mediaStatusChanged.connect(self._media_status_changed)
        self.position = QSlider()
        self.position.setOrientation(Qt.Orientation.Horizontal)
        self.position.sliderMoved.connect(self.player.setPosition)
        self.player.positionChanged.connect(self.position.setValue)
        self.player.durationChanged.connect(self.position.setMaximum)
        self.volume = QSlider()
        self.volume.setOrientation(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(100)
        self.volume.valueChanged.connect(lambda value: self.audio.setVolume(value / 100))
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

    def _play_selected(self) -> None:
        item = self.model.item_at(self.table.currentIndex())
        if item is None or item.file_path is None:
            return
        if item.validation_state == "diagnostic":
            self._failed(f"Playback unavailable: {item.error_state or 'media has a diagnostic'}")
            return
        self.player.setSource(QUrl.fromLocalFile(item.file_path))
        self.player.play()

    def _player_pause(self) -> None:
        self.player.pause()

    def _set_speed(self, label: str) -> None:
        self.player.setPlaybackRate(float(label.removesuffix("×")))

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
