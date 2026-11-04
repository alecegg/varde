"""Compatibility helpers for repository-backed stable address slots."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_SLOT = re.compile(r"[A-Za-z0-9._-]+\Z", re.ASCII)
_ORCHESTRATOR_SLOT = re.compile(r"orchestrator-[0-9]+\Z", re.ASCII)
_PIPELINE_WORKER_SLOT = re.compile(
    r"(?P<plan>[A-Za-z0-9._-]+)-(?:builder|reviewer)\Z", re.ASCII
)


def is_orchestrator_slot(name: str) -> bool:
    """Return whether the address uses the reserved orchestrator slot form."""
    return bool(_ORCHESTRATOR_SLOT.fullmatch(name))


def is_pipeline_worker_slot(name: str, plan: str | None = None) -> bool:
    """Return whether an address uses a stable pipeline worker slot form."""
    match = _PIPELINE_WORKER_SLOT.fullmatch(name)
    return match is not None and (plan is None or match.group("plan") == plan)


def _addresses(working: str | Path):
    return _open_addresses(Path(working))


@lru_cache(maxsize=128)
def _open_addresses(working: Path):
    from varde_data.config import load_data_config
    from varde_data.open import open_data

    return open_data(working, load_data_config()).addresses


def load_slots(working: str | Path) -> dict[str, dict[str, object]]:
    return {
        row.slot: {
            "slot": row.slot,
            "aliases": list(row.aliases),
            "current_address": row.current_address,
        }
        for row in _addresses(working).slots()
    }


def resolve_alias(name: str, slots: dict[str, dict[str, object]]) -> str:
    """Resolve a name using a previously read slot snapshot."""
    for slot in sorted(slots):
        aliases = slots[slot].get("aliases", [])
        if name == slot or isinstance(aliases, list) and name in aliases:
            return slot
    return name


def resolve_reader(name: str, working: str | Path) -> str:
    return _addresses(working).resolve_alias(name)


def reader_addresses(name: str, working: str | Path) -> set[str]:
    return set(_addresses(working).reader_addresses(name))


def add_alias(working: str | Path, slot: str, plan: str | None = None) -> None:
    from varde_data.config import load_data_config
    from varde_data.open import open_data
    from varde_data.service import AddressService

    if not _SLOT.fullmatch(slot) or plan is not None and not _SLOT.fullmatch(plan):
        raise ValueError(f"invalid slot or plan alias `{plan or slot}`")
    data = open_data(Path(working), load_data_config())
    AddressService(data.addresses, data.messages).add_alias(slot, plan)


def remove_alias(working: str | Path, plan: str) -> None:
    if not _SLOT.fullmatch(plan):
        raise ValueError(f"invalid plan alias `{plan}`")
    _addresses(working).remove_alias(plan)
