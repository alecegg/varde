"""Per-working-directory authority for message store selection."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from varde_data.errors import Invalid, Locked
from varde_data.locking import atomic_write, file_lock, shared_file_lock

Primary = Literal["files", "sqlite"]
Mirror = Literal["none", "files", "sqlite"]
StoreMode = Literal["files", "mirror-files", "mirror-sqlite", "sqlite"]

_MODES: tuple[StoreMode, ...] = (
    "files",
    "mirror-files",
    "mirror-sqlite",
    "sqlite",
)
_MODE_PARTS = {
    "files": ("files", "none"),
    "mirror-files": ("files", "sqlite"),
    "mirror-sqlite": ("sqlite", "files"),
    "sqlite": ("sqlite", "none"),
}
_MARKER = ".cache/inbox/store-mode.json"
_LOCK = ".cache/inbox/store-mode.lock"
STORE_MODE_MARKER_VERSION = 1
_MAX_GENERATION = 2**63 - 1


class StoreModeInvalid(Invalid, ValueError):
    """Invalid mode state that prompt hooks can safely skip as a ValueError."""


@dataclass(frozen=True)
class StoreModeRecord:
    primary: Primary
    mirror: Mirror
    import_verified_at: str
    generation: int

    def to_json(self) -> str:
        return json.dumps(
            {
                "version": STORE_MODE_MARKER_VERSION,
                "primary": self.primary,
                "mirror": self.mirror,
                "import_verified_at": self.import_verified_at,
                "generation": self.generation,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


def marker_path(working: Path) -> Path:
    return working / _MARKER


def store_mode_read_lock(working: Path, *, timeout: float):
    """Keep a mode transition from splitting backend selection and opening."""
    return shared_file_lock(working / _LOCK, timeout=timeout)


def mode_parts(mode: str) -> tuple[Primary, Mirror]:
    """Map a requested mode to its primary and mirror stores."""
    if mode not in _MODE_PARTS:
        raise StoreModeInvalid(f"unknown message store mode: {mode}")
    return _MODE_PARTS[mode]  # type: ignore[return-value]


def transition_allowed(current: str, requested: str) -> bool:
    """Allow only one adjacent step along the migration path."""
    if current not in _MODES or requested not in _MODES:
        return False
    return abs(_MODES.index(current) - _MODES.index(requested)) == 1


def read_store_mode(working: Path) -> StoreModeRecord | None:
    """Read and cross-check the marker, failing closed if it is damaged."""
    return _read_store_mode(working)


def _read_store_mode(working: Path) -> StoreModeRecord | None:
    path = marker_path(working)
    try:
        payload = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        _reject_orphan_database_mode(working)
        return None
    except NotADirectoryError:
        _reject_orphan_database_mode(working)
        return None
    except UnicodeError as exc:
        raise StoreModeInvalid(f"invalid message store mode marker: {exc}") from exc
    except OSError as exc:
        raise StoreModeInvalid(f"cannot read message store mode marker: {exc}") from exc

    record = _parse_record(payload)
    database_record = _read_database_record(working)
    if database_record != record:
        raise StoreModeInvalid(
            "interrupted store mode flip; rerun varde msg store verify"
        )
    return record


def mirror_lag(working: Path, *, verify: bool = False) -> int:
    """Return pending mirror writes persisted by the message wrapper."""
    from varde_data.backends.sqlite.messages import messages_db_path

    path = messages_db_path(working)
    if not path.is_file():
        return 0
    try:
        with closing(
            sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=0.05)
        ) as db:
            exists = db.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='mirror_state'"
            ).fetchone()
            if exists is None:
                lag = 0
            else:
                row = db.execute(
                    "SELECT COALESCE(SUM(lag),0) FROM mirror_state"
                ).fetchone()
                lag = int(row[0]) if row else 0
        if lag or not verify:
            return lag
        record = read_store_mode(working)
        if record is None or record.mirror == "none":
            return 0
        from varde_data.backends.mirror.messages import MirrorMessages

        try:
            repository = MirrorMessages(working, record.primary, record.mirror)
            return 0 if repository.is_synchronized() else 1
        except Exception as exc:
            raise StoreModeInvalid(
                f"cannot verify mirror state before mode flip: {exc}"
            ) from exc
    except sqlite3.OperationalError as exc:
        message = str(exc).lower()
        if "locked" in message or "busy" in message:
            raise Locked("message mirror state is busy; retry the operation") from exc
        raise StoreModeInvalid(f"cannot read message mirror state: {exc}") from exc


def set_store_mode(working: Path, mode: StoreMode) -> StoreModeRecord:
    """Persist one transition with a lock and generation compare-and-swap."""
    observed = read_store_mode(working)
    if observed is None:
        raise StoreModeInvalid("run varde msg store import")

    with file_lock(working / _LOCK, timeout=30):
        old = _read_store_mode(working)
        if old is None or old.generation != observed.generation:
            raise Locked("message store mode changed concurrently; retry")
        current = _record_mode(old)
        if not transition_allowed(current, mode):
            raise StoreModeInvalid(
                f"illegal message store mode transition: {current} to {mode}"
            )
        with file_lock(working / ".cache/inbox/mirror.lock", timeout=30):
            if old.mirror != "none":
                from varde_data.backends.mirror.messages import MirrorMessages

                repository = MirrorMessages(working, old.primary, old.mirror)
                if not repository._sync() or not repository.is_synchronized():
                    raise StoreModeInvalid(
                        "cannot change message store mode while mirror lag is nonzero"
                    )
            if mirror_lag(working, verify=old.mirror != "none"):
                raise StoreModeInvalid(
                    "cannot change message store mode while mirror lag is nonzero"
                )
            primary, mirror = mode_parts(mode)
            record = StoreModeRecord(
                primary,
                mirror,
                old.import_verified_at,
                _next_generation(old.generation),
            )
            _write_record(working, record)
        return record


def mark_import_verified(
    working: Path, *, verified_at: str | None = None
) -> StoreModeRecord:
    """Record a clean, verified import from the message transfer workflow."""
    with file_lock(working / _LOCK, timeout=2):
        old = _read_store_mode(working)
        imported_at = verified_at or datetime.now(UTC).isoformat()
        if old is None:
            record = StoreModeRecord("files", "none", imported_at, 1)
        else:
            record = StoreModeRecord(
                old.primary, old.mirror, imported_at, _next_generation(old.generation)
            )
        _write_record(working, record)
        return record


def _mark_import_verified(
    working: Path, *, verified_at: str | None = None
) -> StoreModeRecord:
    """Compatibility alias for the original private import helper."""
    return mark_import_verified(working, verified_at=verified_at)


def parse_store_mode_record(payload: str) -> StoreModeRecord:
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise StoreModeInvalid(f"invalid message store mode marker: {exc}") from exc
    if not isinstance(raw, dict):
        raise StoreModeInvalid("invalid message store mode marker")
    primary, mirror = raw.get("primary"), raw.get("mirror")
    verified, generation = raw.get("import_verified_at"), raw.get("generation")
    version = raw.get("version", STORE_MODE_MARKER_VERSION)
    if type(version) is not int or version != STORE_MODE_MARKER_VERSION:
        raise StoreModeInvalid(
            f"message store marker version {version!r} is newer than supported "
            f"version {STORE_MODE_MARKER_VERSION}"
        )
    if primary not in ("files", "sqlite") or mirror not in (
        "none",
        "files",
        "sqlite",
    ):
        raise StoreModeInvalid(
            "invalid primary and mirror in message store mode marker"
        )
    if (primary, mirror) not in _MODE_PARTS.values():
        raise StoreModeInvalid(
            "invalid primary and mirror in message store mode marker"
        )
    if not isinstance(verified, str) or not _valid_timestamp(verified):
        raise StoreModeInvalid(
            "invalid import verification time in message store mode marker"
        )
    if (
        not isinstance(generation, int)
        or isinstance(generation, bool)
        or not 1 <= generation <= _MAX_GENERATION
    ):
        raise StoreModeInvalid("invalid generation in message store mode marker")
    return StoreModeRecord(primary, mirror, verified, generation)


def _parse_record(payload: str) -> StoreModeRecord:
    """Compatibility alias for callers that used the old private parser."""
    return parse_store_mode_record(payload)


def _valid_timestamp(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _next_generation(generation: int) -> int:
    if generation >= _MAX_GENERATION:
        raise StoreModeInvalid("message store mode generation is exhausted")
    return generation + 1


def _record_mode(record: StoreModeRecord) -> StoreMode:
    for mode, pair in _MODE_PARTS.items():
        if pair == (record.primary, record.mirror):
            return mode  # type: ignore[return-value]
    raise StoreModeInvalid("invalid primary and mirror in message store mode marker")


def _read_database_record(working: Path) -> StoreModeRecord | None:
    from varde_data.backends.sqlite.messages import messages_db_path

    path = messages_db_path(working)
    if not path.is_file():
        raise StoreModeInvalid(
            "message store mode marker has no matching SQLite metadata"
        )
    try:
        with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as db:
            row = db.execute("SELECT value FROM meta WHERE key='store_mode'").fetchone()
    except sqlite3.OperationalError as exc:
        message = str(exc).lower()
        if "locked" in message or "busy" in message:
            raise Locked("message store metadata is busy; retry the operation") from exc
        raise StoreModeInvalid(f"cannot read message store metadata: {exc}") from exc
    if row is None:
        return None
    return _parse_record(str(row[0]))


def _reject_orphan_database_mode(working: Path) -> None:
    from varde_data.backends.sqlite.messages import messages_db_path

    path = messages_db_path(working)
    if not path.is_file():
        return
    try:
        with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as db:
            row = db.execute("SELECT value FROM meta WHERE key='store_mode'").fetchone()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc).lower():
            return
        raise StoreModeInvalid(
            f"cannot verify missing message store marker: {exc}"
        ) from exc
    if row is None:
        return
    record = _parse_record(str(row[0]))
    if _record_mode(record) != "files":
        raise StoreModeInvalid(
            "message store mode marker is missing; run "
            "varde msg store verify --repair-mode; for a nondefault mode, run "
            "varde msg store verify --repair-mode --force-adopt after confirming "
            "the intended mode"
        )


def _write_record(working: Path, record: StoreModeRecord) -> None:
    from varde_data.backends.sqlite.messages import factory

    payload = record.to_json()
    repository = factory(working)
    repository.write_meta("store_mode", payload)
    try:
        atomic_write(marker_path(working), (payload + "\n").encode(), mode=0o600)
    except OSError as exc:
        raise StoreModeInvalid(
            f"could not write message store mode marker: {exc}"
        ) from exc
