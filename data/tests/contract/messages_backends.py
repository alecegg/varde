"""Lazily assembled registry for message repository contract tests."""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest
from varde_data.backends.memory import MemoryMessages
from varde_data.records.messages import ReaderResolver
from varde_data.repos.messages import MessageRepository, StaticReaderResolver

BackendFactory = Callable[[Path, ReaderResolver], MessageRepository]
RawMessageSeeder = Callable[[Path, bytes], None]
ForceNextIds = Callable[[MessageRepository, tuple[str, ...], pytest.MonkeyPatch], None]


@dataclass(frozen=True)
class BackendCapabilities:
    torn_tail: bool
    byte_cursor: bool
    shared_processes: bool
    append_only: bool


@dataclass(frozen=True)
class BackendRegistration:
    name: str
    factory: BackendFactory
    capabilities: BackendCapabilities
    seed_raw_messages: RawMessageSeeder | None = None
    force_next_ids: ForceNextIds | None = None


class AliasResolver(StaticReaderResolver):
    def resolve(self, name: str) -> str:
        return "slot-a" if name in {"alias-a", "slot-a"} else name

    def addresses(self, slot: str) -> set[str]:
        return {"slot-a", "alias-a"} if slot == "slot-a" else {slot}


def _available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except ModuleNotFoundError:
        return False


def _seed_files_messages(working: Path, data: bytes) -> None:
    path = working / ".cache" / "inbox" / "messages.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _force_files_next_ids(
    _backend: MessageRepository, ids: tuple[str, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    from varde_data.backends.files import messages as files_messages

    generated = iter(ids)
    monkeypatch.setattr(files_messages.secrets, "token_hex", lambda _: next(generated))


def _force_memory_next_ids(
    _backend: MessageRepository, ids: tuple[str, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from varde_data.backends import memory

    generated = iter(ids)

    def uuid4() -> SimpleNamespace:
        return SimpleNamespace(hex=next(generated))

    monkeypatch.setattr(memory.uuid, "uuid4", uuid4)


def _force_sqlite_next_ids(
    _backend: MessageRepository, ids: tuple[str, ...], monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from varde_data.backends.sqlite import messages as module

    generated = iter(ids)

    def uuid4() -> SimpleNamespace:
        return SimpleNamespace(hex=next(generated))

    monkeypatch.setattr(module.uuid, "uuid4", uuid4)


def backend_registry() -> dict[str, BackendRegistration]:
    registry = {
        "memory": BackendRegistration(
            "memory",
            lambda _working, resolver: MemoryMessages(resolver),
            BackendCapabilities(
                torn_tail=False,
                byte_cursor=False,
                shared_processes=False,
                append_only=True,
            ),
            force_next_ids=_force_memory_next_ids,
        )
    }
    if _available("varde_data.messages"):
        module = importlib.import_module("varde_data.messages")
        opener = cast("Callable[..., MessageRepository]", module.open_messages)
        registry["files"] = BackendRegistration(
            "files",
            lambda working, resolver: opener(working, "files", resolver=resolver),
            BackendCapabilities(
                torn_tail=True,
                byte_cursor=True,
                shared_processes=True,
                append_only=True,
            ),
            _seed_files_messages,
            _force_files_next_ids,
        )
    if _available("varde_data.backends.sqlite.messages"):
        module = importlib.import_module("varde_data.backends.sqlite.messages")
        factory = cast("Callable[..., MessageRepository]", module.factory)
        registry["sqlite"] = BackendRegistration(
            "sqlite",
            lambda working, resolver: factory(working, resolver=resolver),
            BackendCapabilities(
                torn_tail=False,
                byte_cursor=False,
                shared_processes=True,
                append_only=True,
            ),
            force_next_ids=_force_sqlite_next_ids,
        )
    if _available("varde_data.messages"):
        from varde_data.messages import open_messages
        from varde_data.store_mode import (
            _mark_import_verified,
            read_store_mode,
            set_store_mode,
        )

        def mirror_factory(mode: str) -> BackendFactory:
            def make(working: Path, resolver: ReaderResolver) -> MessageRepository:
                record = read_store_mode(working)
                if record is None:
                    _mark_import_verified(working, verified_at="2026-01-01T00:00:00Z")
                    if mode == "mirror-sqlite":
                        set_store_mode(working, "mirror-files")
                    set_store_mode(working, mode)  # type: ignore[arg-type]
                elif record.primary == "files" and record.mirror == "none":
                    if mode == "mirror-sqlite":
                        set_store_mode(working, "mirror-files")
                    set_store_mode(working, mode)  # type: ignore[arg-type]
                return open_messages(working, mode, resolver=resolver)

            return make

        for mode in ("mirror-files", "mirror-sqlite"):
            registry[mode] = BackendRegistration(
                mode,
                mirror_factory(mode),
                BackendCapabilities(
                    torn_tail=mode == "mirror-files",
                    byte_cursor=mode == "mirror-files",
                    shared_processes=True,
                    append_only=True,
                ),
                seed_raw_messages=_seed_files_messages
                if mode == "mirror-files"
                else None,
                force_next_ids=(
                    _force_files_next_ids
                    if mode == "mirror-files"
                    else _force_sqlite_next_ids
                ),
            )
    return registry
