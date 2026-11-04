"""Shared paths used by the queue state stores."""

from pathlib import Path

from varde_data.errors import Invalid

QUEUE_DATABASE = Path(".cache/inbox/messages.sqlite3")
LEGACY_QUEUE_DATABASE = Path(".cache/data/queue.sqlite3")
QUEUE_VERSION_MARKER = Path(".cache/data/queue.version")


def read_queue_version(working: Path) -> int:
    """Read the one authoritative marker used to select the queue database."""
    marker = working / QUEUE_VERSION_MARKER
    try:
        raw = marker.read_text(encoding="ascii").strip()
    except FileNotFoundError:
        return 0
    except OSError as error:
        raise Invalid(f"cannot read queue version marker: {error}") from error
    if not raw.isdecimal():
        raise Invalid(f"invalid queue version marker: {raw!r}")
    try:
        return int(raw)
    except ValueError as error:
        raise Invalid(f"invalid queue version marker: {raw!r}") from error


def queue_migration_pending(working: Path) -> bool:
    """Whether an existing legacy queue still needs the explicit merge."""
    from varde_data.backends.sqlite.queue_schema import QUEUE_MARKER_VERSION

    version = read_queue_version(working)
    if version >= QUEUE_MARKER_VERSION:
        return False
    return version > 0 or (working / LEGACY_QUEUE_DATABASE).is_file()


def queue_database_for(working: Path) -> Path:
    """Select the legacy database only before its marker is advanced."""
    from varde_data.backends.sqlite.queue_schema import QUEUE_MARKER_VERSION

    version = read_queue_version(working)
    if version >= QUEUE_MARKER_VERSION:
        return working / QUEUE_DATABASE
    return working / LEGACY_QUEUE_DATABASE
