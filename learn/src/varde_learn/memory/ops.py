"""Entry store operations with optimistic concurrency (library only)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from varde_learn.knowledge.occ import version
from varde_learn.knowledge.registry import _matches_all as matches_all
from varde_learn.memory import links, store
from varde_learn.memory.entry import Entry, EntryError, find_secret
from varde_learn.memory.rules import ERROR, Issue, lint_entry

IMMUTABLE = frozenset({"id", "scope", "scope_key", "created", "updated"})
LIST_FIELDS = frozenset({"tags", "aliases"})
_ENTRY_FIELDS = frozenset(Entry.__dataclass_fields__) - {"extra"}


class OpsError(Exception):
    """An operation failed; `kind` is one of conflict, not_found, ambiguous,
    lint, immutable, invalid."""

    def __init__(self, kind: str, message: str, issues: tuple[Issue, ...] = ()):
        super().__init__(f"{kind}: {message}")
        self.kind = kind
        self.issues = issues


@dataclass(frozen=True)
class EntryRef:
    scope: str
    scope_key: str
    id: str


@dataclass(frozen=True)
class Stored:
    entry: Entry
    path: Path
    version: str


@dataclass(frozen=True)
class OpResult:
    entry: Entry | None
    path: Path
    version: str
    issues: tuple[Issue, ...] = ()
    linked_by: tuple[str, ...] = ()


def resolve_ref(root: Path, entry_id: str) -> EntryRef:
    """The one entry with this id, across scopes."""
    entries, _ = store.load_report(root)
    found = [e for e in entries if e.id == entry_id]
    if not found:
        raise OpsError("not_found", entry_id)
    if len(found) > 1:
        raise OpsError("ambiguous", f"{entry_id} exists in {len(found)} scopes")
    return EntryRef(found[0].scope, found[0].scope_key, entry_id)


def read_stored(root: Path, ref: EntryRef) -> Stored:
    path = store.entry_path(root, ref.scope, ref.scope_key, ref.id)
    try:
        data = path.read_bytes()
        entry = store.read_entry(path, root)
    except FileNotFoundError as error:
        raise OpsError("not_found", ref.id) from error
    except (OSError, ValueError) as error:
        raise OpsError("invalid", f"{ref.id}: {error}") from error
    return Stored(entry, path, version(data))


def update_entry(
    root: Path,
    ref: EntryRef,
    expected_version: str,
    changes: Mapping[str, Any],
    now: str | None = None,
) -> OpResult:
    """Apply field changes; fails with `conflict` when the file changed."""
    stored = _read_expecting(root, ref, expected_version)
    updated = _apply(stored.entry, changes, now or _now())
    return _write(root, stored, updated)


def set_field(
    root: Path,
    ref: EntryRef,
    expected_version: str,
    assignment: tuple[str, str],
    now: str | None = None,
) -> OpResult:
    """Set one `name=value` field; unknown names go to `extra`."""
    name, value = assignment
    return update_entry(root, ref, expected_version, {name: value}, now)


def retire_entry(
    root: Path, ref: EntryRef, expected_version: str, now: str | None = None
) -> OpResult:
    return update_entry(root, ref, expected_version, {"status": "retired"}, now)


def delete_entry(root: Path, ref: EntryRef, expected_version: str) -> OpResult:
    """Hard delete of one file; reports the entries that linked to it."""
    stored = _read_expecting(root, ref, expected_version)
    entries, _ = store.load_report(root)
    inbound = links.linked_by(entries, stored.entry)
    stored.path.unlink()
    return OpResult(None, stored.path, "", linked_by=tuple(inbound))


def entry_fields(entry: Entry) -> dict[str, Any]:
    """Front-matter view of an entry for `--field key=value` filters."""
    fields: dict[str, Any] = {n: getattr(entry, n) for n in _ENTRY_FIELDS}
    fields["tags"] = list(entry.tags)
    fields["aliases"] = list(entry.aliases)
    return {**entry.extra, **fields}


def filter_entries(entries: list[Entry], filters: list[tuple[str, str]]) -> list[Entry]:
    """Entries matching every filter, with the knowledge registry's semantics."""
    return [e for e in entries if matches_all(entry_fields(e), filters)]


def _read_expecting(root: Path, ref: EntryRef, expected_version: str) -> Stored:
    stored = read_stored(root, ref)
    if stored.version != expected_version:
        raise OpsError("conflict", f"{ref.id} changed on disk")
    return stored


def _apply(entry: Entry, changes: Mapping[str, Any], now: str) -> Entry:
    fixed = IMMUTABLE.intersection(changes)
    if fixed:
        raise OpsError("immutable", ", ".join(sorted(fixed)))
    known = {k: _coerce(k, v) for k, v in changes.items() if k in _ENTRY_FIELDS}
    extra = {k: v for k, v in changes.items() if k not in _ENTRY_FIELDS}
    return replace(entry, **known, updated=now, extra={**entry.extra, **extra})


def _coerce(name: str, value: Any) -> Any:
    if name in LIST_FIELDS and isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if name == "surface" and isinstance(value, str):
        if value not in ("true", "false"):
            raise OpsError("invalid", f"surface must be true or false: {value!r}")
        return value == "true"
    return value


def _write(root: Path, stored: Stored, updated: Entry) -> OpResult:
    issues = tuple(lint_entry(updated, stored.entry)) + _secret_issues(updated)
    errors = tuple(i for i in issues if i.severity == ERROR)
    if errors:
        raise OpsError("lint", "; ".join(i.message for i in errors), errors)
    try:
        path = store.write_entry(root, updated, overwrite=True)
    except EntryError as error:
        raise OpsError("invalid", str(error)) from error
    return OpResult(updated, path, version(path.read_bytes()), issues)


def _secret_issues(entry: Entry) -> tuple[Issue, ...]:
    fields = [entry.title, entry.description, *entry.aliases, *entry.tags]
    if any(find_secret(text) for text in fields):
        return (Issue(ERROR, "secret", "a metadata field looks like a secret"),)
    return ()


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
