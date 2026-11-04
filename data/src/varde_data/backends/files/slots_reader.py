"""Read-only slot resolver backed by the address repository."""

from __future__ import annotations

from pathlib import Path

from varde_data.backends.files.addresses_bindings import FilesAddresses


class SlotReader:
    """Adapt address slot lookup to the message repository's resolver API."""

    def __init__(self, working: Path) -> None:
        self._addresses = FilesAddresses(working)

    def snapshot(self) -> SlotSnapshot:
        return SlotSnapshot(
            {slot.slot: slot.aliases for slot in self._addresses.slots()}
        )

    def resolve(self, name: str) -> str:
        return self._addresses.resolve_alias(name)

    def addresses(self, slot: str) -> set[str]:
        return set(self._addresses.reader_addresses(slot))


class SlotSnapshot:
    """Immutable resolver snapshot for one messages repository operation."""

    def __init__(self, slots: dict[str, tuple[str, ...]]) -> None:
        self._slots = dict(slots)
        self._slot_by_name: dict[str, str] = {}
        for slot, aliases in sorted(slots.items()):
            self._slot_by_name.setdefault(slot, slot)
            for alias in aliases:
                self._slot_by_name.setdefault(alias, slot)

    def resolve(self, name: str) -> str:
        return self._slot_by_name.get(name, name)

    def addresses(self, slot: str) -> set[str]:
        resolved = self.resolve(slot)
        return {resolved, *self._slots.get(resolved, ())}
