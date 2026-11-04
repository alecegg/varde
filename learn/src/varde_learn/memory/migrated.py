"""Read a migrated knowledge bundle from the unified store (one reader per fact)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from varde_learn.knowledge.crud.show import ShownConcept
from varde_learn.knowledge.occ import version
from varde_learn.memory import migration_record, sources, store
from varde_learn.memory.entry import Entry
from varde_learn.memory.searchindex import Source


def migrated_source(root: Path, bundle: Path) -> Source | None:
    """The bundle's entries in the store, or None when it has no migration record."""
    if migration_record.read_record(root, bundle) is None:
        return None
    record = migration_record.read_record(root, bundle) or {}
    created = set(record.get("created", {}))

    def load() -> sources.Loaded:
        entries, issues = sources.load_memory(root)
        return [e for e in entries if str(path_of(e)) in created], issues

    def path_of(entry: Entry) -> Path:
        return store.entry_path(root, entry.scope, entry.scope_key, entry.id)

    return Source(
        files=lambda: [path_of(entry) for entry in load()[0]],
        load=load,
        path_of=path_of,
    )


def shown_concept(root: Path, bundle: Path, slug: str) -> ShownConcept | None:
    """The migrated entry for a slug as a shown concept, else None."""
    source = migrated_source(root, bundle)
    if source is None:
        return None
    for entry in source.load()[0]:
        if original_slug(entry, bundle) == slug:
            data = source.path_of(entry).read_bytes()
            return ShownConcept(slug, version(data), _frontmatter(entry), entry.text)
    return None


def _frontmatter(entry: Entry) -> dict[str, Any]:
    front: dict[str, Any] = {
        "type": entry.type,
        "description": entry.description,
        "status": entry.status,
        "date": entry.created,
    }
    if entry.title:
        front["title"] = entry.title
    if entry.aliases:
        front["aliases"] = list(entry.aliases)
    if entry.tags:
        front["tags"] = list(entry.tags)
    return front | dict(entry.extra)


def original_slug(entry: Entry, bundle: Path) -> str:
    """The knowledge slug an entry was migrated from."""
    return entry.source.removeprefix(f"knowledge:{bundle.name}:")
