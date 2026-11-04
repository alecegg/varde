"""Per-domain store switch for the learn root (``store-mode.json``)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from varde_data.errors import Invalid, Locked
from varde_data.learn_store_ignore import ensure_ignored
from varde_data.locking import atomic_write, file_lock, shared_file_lock

Domain = Literal["friction", "ledger", "calls"]
Mode = Literal["files", "sqlite"]

DOMAINS: tuple[Domain, ...] = ("friction", "ledger", "calls")
MARKER_NAME = "store-mode.json"
LOCK_NAME = "store-mode.lock"
DB_NAME = "learn.sqlite3"
MARKER_VERSION = 1
_MAX_GENERATION = 2**63 - 1


class LearnStoreModeInvalid(Invalid):
    """The learn store marker is damaged or names an unknown mode."""


class StaleGeneration(Locked):
    """A writer's store generation is older than the marker's."""


@dataclass(frozen=True)
class LearnStoreMode:
    friction: Mode
    ledger: Mode
    calls: Mode
    generation: int

    def mode(self, domain: str) -> Mode:
        if domain not in DOMAINS:
            raise LearnStoreModeInvalid(f"unknown learn domain: {domain}")
        return getattr(self, domain)

    def to_json(self) -> str:
        return json.dumps(
            {
                "version": MARKER_VERSION,
                "friction": self.friction,
                "ledger": self.ledger,
                "calls": self.calls,
                "generation": self.generation,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


DEFAULT_MODE = LearnStoreMode("files", "files", "files", 0)


def learn_db_path(root: Path) -> Path:
    """Return the sqlite database path inside a learn root."""
    return root / DB_NAME


def marker_path(root: Path) -> Path:
    return root / MARKER_NAME


def read_learn_mode(root: Path) -> LearnStoreMode:
    """Read the marker; an absent marker means every domain is on files."""
    try:
        payload = marker_path(root).read_text(encoding="utf-8")
    except FileNotFoundError, NotADirectoryError:
        return DEFAULT_MODE
    except (OSError, UnicodeError) as exc:
        raise LearnStoreModeInvalid(f"cannot read learn store marker: {exc}") from exc
    return parse_learn_mode(payload)


def parse_learn_mode(payload: str) -> LearnStoreMode:
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise LearnStoreModeInvalid(f"invalid learn store marker: {exc}") from exc
    if not isinstance(raw, dict):
        raise LearnStoreModeInvalid("invalid learn store marker")
    if raw.get("version") != MARKER_VERSION:
        raise LearnStoreModeInvalid(
            f"learn store marker version {raw.get('version')!r} is not supported"
        )
    generation = raw.get("generation")
    if type(generation) is not int or not 0 <= generation <= _MAX_GENERATION:
        raise LearnStoreModeInvalid("invalid generation in learn store marker")
    modes = {domain: raw.get(domain) for domain in DOMAINS}
    for domain, mode in modes.items():
        if mode not in ("files", "sqlite"):
            raise LearnStoreModeInvalid(
                f"invalid {domain} mode in learn store marker: {mode!r}"
            )
    return LearnStoreMode(
        modes["friction"],  # type: ignore[arg-type]
        modes["ledger"],  # type: ignore[arg-type]
        modes["calls"],  # type: ignore[arg-type]
        generation,
    )


def backend_for(root: Path, domain: str) -> Mode:
    """Return the backend a domain currently uses."""
    return read_learn_mode(root).mode(domain)


@contextmanager
def writer_target(
    root: Path,
    domain: str,
    *,
    held_generation: int | None = None,
    timeout: float = 5,
) -> Iterator[tuple[Mode, int]]:
    """Hold the shared lock and yield the backend and generation to write to.

    A writer that opened its backend at ``held_generation`` is refused with
    ``StaleGeneration`` once a flip moved the marker; it never writes to the
    backend it opened before the flip. Pass ``None`` to follow the marker.
    """
    with shared_file_lock(root / LOCK_NAME, timeout=timeout):
        record = read_learn_mode(root)
        if held_generation is not None and held_generation != record.generation:
            raise StaleGeneration(
                f"learn store generation {held_generation} is stale; "
                f"now {record.generation}"
            )
        yield record.mode(domain), record.generation


@contextmanager
def files_writer(root: Path, domain: str, *, timeout: float = 5) -> Iterator[None]:
    """Hold the shared lock around a files-backend write.

    Refuses with ``StaleGeneration`` when a flip moved the domain off ``files``,
    so no row is written to source files after the flip. The caller reopens
    the repository to follow the marker.
    """
    with writer_target(root, domain, timeout=timeout) as (backend, generation):
        if backend != "files":
            raise StaleGeneration(
                f"{domain} moved to {backend} at generation {generation}; "
                "reopen the store"
            )
        yield


@contextmanager
def shared_store_lock(root: Path, *, timeout: float = 30) -> Iterator[None]:
    """Keep a flip from changing the store during a read-only check."""
    with shared_file_lock(root / LOCK_NAME, timeout=timeout):
        yield


@contextmanager
def exclusive_store_lock(root: Path, *, timeout: float = 30) -> Iterator[None]:
    """Block all writers while a domain is backed up, imported, verified, flipped."""
    with file_lock(root / LOCK_NAME, timeout=timeout):
        yield


def flip_domain_locked(root: Path, domain: str, mode: Mode) -> LearnStoreMode:
    """Switch one domain and bump the generation; caller holds the exclusive lock."""
    if mode not in ("files", "sqlite"):
        raise LearnStoreModeInvalid(f"unknown learn store mode: {mode}")
    old = read_learn_mode(root)
    old.mode(domain)
    if old.generation >= _MAX_GENERATION:
        raise LearnStoreModeInvalid("learn store generation is exhausted")
    values: dict[str, Mode] = {name: old.mode(name) for name in DOMAINS}
    values[domain] = mode
    record = LearnStoreMode(
        values["friction"],
        values["ledger"],
        values["calls"],
        old.generation + 1,
    )
    try:
        atomic_write(marker_path(root), (record.to_json() + "\n").encode(), mode=0o600)
    except OSError as exc:
        raise LearnStoreModeInvalid(
            f"could not write learn store marker: {exc}"
        ) from exc
    ensure_ignored(root)
    return record
