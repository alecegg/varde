"""Factory for selecting a message repository backend."""

from pathlib import Path
from typing import Any, cast

from varde_data.records.messages import ReaderResolver
from varde_data.repos.messages import MessageRepository
from varde_data.store_mode import (
    StoreModeInvalid,
    read_store_mode,
    store_mode_read_lock,
)


def open_messages(
    working: Path,
    backend_name: str,
    *,
    resolver: ReaderResolver | None = None,
    busy_timeout: float = 30,
) -> MessageRepository:
    if backend_name == "memory":
        from varde_data.backends.memory import MemoryMessages

        return MemoryMessages(resolver)
    if backend_name not in {"files", "sqlite", "mirror-files", "mirror-sqlite"}:
        raise ValueError(f"unknown messages backend: {backend_name}")
    cache = working / ".cache"
    if backend_name == "files" and (not cache.exists() or not cache.is_dir()):
        from varde_data.backends.files.messages import FilesMessages

        return FilesMessages(working, resolver, lock_timeout=busy_timeout)

    with store_mode_read_lock(working, timeout=busy_timeout):
        return _open_messages_locked(working, backend_name, resolver, busy_timeout)


def _open_messages_locked(
    working: Path,
    backend_name: str,
    resolver: ReaderResolver | None,
    busy_timeout: float,
) -> MessageRepository:

    marker = read_store_mode(working)
    if backend_name in {"sqlite", "mirror-files", "mirror-sqlite"} and marker is None:
        raise StoreModeInvalid("run varde msg store import")
    if marker is not None:
        if marker.mirror != "none":
            from varde_data.backends.mirror.messages import MirrorMessages

            # MirrorMessages delegates the rest of the protocol through __getattr__.
            return cast(
                "MessageRepository",
                MirrorMessages(
                    working,
                    marker.primary,
                    marker.mirror,
                    resolver=resolver,
                    busy_timeout=busy_timeout,
                    mode_generation=marker.generation,
                ),
            )
        backend_name = marker.primary
    if backend_name == "files":
        from varde_data.backends.files.messages import FilesMessages

        return FilesMessages.from_store_mode(
            working, resolver, marker, lock_timeout=busy_timeout
        )
    if backend_name == "sqlite":
        from varde_data.backends.files.slots_reader import SlotReader
        from varde_data.backends.sqlite.messages import factory

        return factory(
            working,
            resolver or SlotReader(working),
            busy_timeout=busy_timeout,
        )
    raise AssertionError(f"unreachable messages backend: {backend_name}")


def below_watermark(inbox: Path) -> set[str]:
    """Return IDs at or before their reader watermark."""
    from varde_data.backends.files.messages_status import below_watermark as check

    return check(inbox)


__all__ = ["below_watermark", "open_messages"]


def touch_relay_wake(working: Path) -> None:
    """Wake a file-backed relay after a message append."""
    from varde_data.addresses import open_addresses

    open_addresses(working, "files").touch_wake()


def record_send_liveness(
    working: Path, message_id: str, recipient: str, now: Any
) -> None:
    """Record send liveness through the address repository."""
    from varde_data.addresses import open_addresses

    open_addresses(working, "files").record_send_liveness(message_id, recipient, now)


__all__ += ["record_send_liveness", "touch_relay_wake"]


def messages_db_path(working: Path) -> Path:
    """Resolve the SQLite message store path for a working directory."""
    from varde_data.backends.sqlite.messages import messages_db_path as resolve

    return resolve(working)


def message_store_files(working: Path) -> tuple[Path, ...]:
    """Return the SQLite database and files SQLite may create beside it."""
    from varde_data.backends.sqlite.messages import message_store_files as paths

    return paths(working)


__all__ += ["message_store_files", "messages_db_path"]


def read_stray_messages(inbox: Path) -> tuple[list[dict[str, Any]], int]:
    """Read legacy stray message rows using the files backend adapter."""
    from varde_data.backends.files.strays import read_stray_messages as read

    return read(inbox)


def remove_stray_store(inbox: Path) -> None:
    """Remove a migrated legacy store using the files backend adapter."""
    from varde_data.backends.files.strays import remove_stray_store as remove

    remove(inbox)


def mirror_parity(
    working: Path, backend_name: str = "files", *, window: int = 7
) -> dict[str, int] | None:
    """Compare a mirrored store and return its parity report; None if not mirrored."""
    from varde_data.backends.mirror.messages import MirrorMessages

    messages = open_messages(working, backend_name)
    if not isinstance(messages, MirrorMessages):
        return None
    messages.compare()
    return messages.parity_report(window)
