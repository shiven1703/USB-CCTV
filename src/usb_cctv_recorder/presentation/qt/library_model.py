"""Incremental Qt table model for catalogue rows."""

from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt, Signal

from usb_cctv_recorder.application.dto import LibraryItem


class LibraryTableModel(QAbstractTableModel):
    """A bounded model; the page supplies each requested catalogue page asynchronously."""

    request_more = Signal(int, int)

    _HEADERS = ("When", "Session", "Class", "Validation", "Gap", "Protected", "Diagnostic")

    def __init__(self, page_size: int = 100) -> None:
        super().__init__()
        self._page_size = page_size
        self._items: list[LibraryItem] = []
        self._total = 0
        self._loading = False

    def rowCount(  # noqa: N802
        self, parent: QModelIndex | QPersistentModelIndex = QModelIndex(), /
    ) -> int:
        return 0 if parent.isValid() else len(self._items)

    def columnCount(  # noqa: N802
        self, parent: QModelIndex | QPersistentModelIndex = QModelIndex(), /
    ) -> int:
        return 0 if parent.isValid() else len(self._HEADERS)

    def data(
        self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole
    ) -> object:  # pragma: no cover - Qt view callback
        if not index.isValid() or role != Qt.ItemDataRole.DisplayRole:
            return None
        item = self._items[index.row()]
        values = (
            item.started_at,
            item.session_id,
            item.media_class,
            item.validation_state,
            item.gap_state,
            "yes" if item.protected else "no",
            item.error_state or "",
        )
        return values[index.column()]

    def headerData(  # noqa: N802
        self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole
    ) -> object:
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self._HEADERS[section]
        return None

    def canFetchMore(  # noqa: N802
        self, parent: QModelIndex | QPersistentModelIndex = QModelIndex(), /
    ) -> bool:
        return not parent.isValid() and not self._loading and len(self._items) < self._total

    def fetchMore(  # noqa: N802
        self, parent: QModelIndex | QPersistentModelIndex = QModelIndex(), /
    ) -> None:
        if not self.canFetchMore(parent):
            return
        self._loading = True
        self.request_more.emit(len(self._items), self._page_size)

    def reset_items(self, items: tuple[LibraryItem, ...], total: int) -> None:
        self.beginResetModel()
        self._items = list(items)
        self._total = total
        self._loading = False
        self.endResetModel()

    def append_items(self, items: tuple[LibraryItem, ...]) -> None:
        start = len(self._items)
        if items:
            self.beginInsertRows(QModelIndex(), start, start + len(items) - 1)
            self._items.extend(items)
            self.endInsertRows()
        self._loading = False

    def replace_item(self, item: LibraryItem) -> None:
        for row, existing in enumerate(self._items):
            if existing.item_id == item.item_id:
                self._items[row] = item
                first = self.index(row, 0)
                last = self.index(row, len(self._HEADERS) - 1)
                self.dataChanged.emit(first, last)
                return

    def item_at(self, index: QModelIndex) -> LibraryItem | None:
        if not index.isValid() or index.row() >= len(self._items):
            return None
        return self._items[index.row()]

    @property
    def items(self) -> tuple[LibraryItem, ...]:
        return tuple(self._items)

    @property
    def page_size(self) -> int:
        return self._page_size
