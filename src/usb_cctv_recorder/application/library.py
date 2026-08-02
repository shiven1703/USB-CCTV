"""Application-facing library queries and evidence-safe actions."""

from __future__ import annotations

from .dto import LibraryDetails, LibraryFilter, LibraryItem
from .ports import LibraryCataloguePort


class LibraryService:
    """Keeps presentation code away from catalogue and media adapters."""

    def __init__(self, catalogue: LibraryCataloguePort) -> None:
        self._catalogue = catalogue

    def rebuild(self, media_root: str) -> int:
        from pathlib import Path

        return self._catalogue.rebuild(Path(media_root))

    def count(self, filters: LibraryFilter) -> int:
        return self._catalogue.count(filters)

    def page(self, filters: LibraryFilter, offset: int, limit: int) -> tuple[LibraryItem, ...]:
        if offset < 0 or limit <= 0:
            raise ValueError("page offset and limit must be positive")
        return self._catalogue.page(filters, offset, limit)

    def details(self, item_id: str) -> LibraryDetails:
        return self._catalogue.details(item_id)

    def set_protected(self, item_id: str, protected: bool) -> LibraryItem:
        return self._catalogue.set_protected(item_id, protected)

    def reverify(self, item_id: str) -> LibraryItem:
        return self._catalogue.reverify(item_id)
