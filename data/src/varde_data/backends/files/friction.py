"""Files backend for the canonical append-only friction log."""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from varde_data.backends.sqlite.friction import SqliteFrictionIndex
from varde_data.learn_store_mode import files_writer
from varde_data.testing import MemoryFriction


class FilesFriction(MemoryFriction):
    """Friction repository backed by ``friction.jsonl``."""

    def __init__(
        self, root: Path, *, redactor: Callable[[str], tuple[str, int]] | None = None
    ) -> None:
        super().__init__(root, redactor=redactor)
        self.cache = SqliteFrictionIndex(self.root)

    def _refresh_for_read(self) -> None:
        self.cache.refresh()

    def event_log(self):
        return super().event_log()

    def _state(self):
        state = super()._state()
        mapping = self.cache.read_mapping()
        slugs = mapping.get("item_slugs", {})
        return replace(
            state,
            items=[
                replace(
                    item,
                    slug=str(
                        self._imported_slugs.get(
                            item.event_id, slugs.get(item.event_id, item.slug)
                        )
                    ),
                )
                for item in state.items
            ],
        )

    def _item(self, identifier):
        if isinstance(identifier, int) or str(identifier).isdecimal():
            requested_id = int(identifier)
            state = self._state()
            item_ids = self.cache.read_mapping().get("items", {})
            for index, item in enumerate(state.items):
                if int(item_ids.get(item.event_id, -1)) == requested_id:
                    return index, item
        return super()._item(identifier)

    def append_event(self, event):
        with files_writer(self.root, "friction"):
            self._refresh_for_read()
            return super().append_event(event)

    def append_events(self, events):
        with files_writer(self.root, "friction"):
            self._refresh_for_read()
            return super().append_events(events)

    def list_items(self, **kwargs):
        self._refresh_for_read()
        return super().list_items(**kwargs)

    def show(self, identifier: str, *, offset: int = 0, limit: int = 100):
        self._refresh_for_read()
        return super().show(identifier, offset=offset, limit=limit)

    def export_items(self):
        self._refresh_for_read()
        return super().export_items()

    def list_recurrences(self, *, offset: int = 0, limit: int = 100):
        self._refresh_for_read()
        return super().list_recurrences(offset=offset, limit=limit)

    def add(self, request):
        self._refresh_for_read()
        item = super().add(request)
        self._refresh_for_read()
        return self._item(item.event_id)[1]

    def set_status(self, request):
        self._refresh_for_read()
        return super().set_status(request)

    def record_adoption(self, request):
        self._refresh_for_read()
        return super().record_adoption(request)

    def import_entries(self, entries, *, dry_run: bool = False):
        if not dry_run:
            self._refresh_for_read()
        result = super().import_entries(entries, dry_run=dry_run)
        if result.id_map:
            self.cache.persist_mapping(result.id_map)
        return result

    def import_events(self, events, *, dry_run: bool = False):
        if not dry_run:
            self._refresh_for_read()
        return super().import_events(events, dry_run=dry_run)

    def find_historical_witness(self, **kwargs):
        self._refresh_for_read()
        return super().find_historical_witness(**kwargs)

    def find_historical_fallback_witness(self, **kwargs):
        self._refresh_for_read()
        return super().find_historical_fallback_witness(**kwargs)

    def record_historical(self, request):
        self._refresh_for_read()
        return super().record_historical(request)
