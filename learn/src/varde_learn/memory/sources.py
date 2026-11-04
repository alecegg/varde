"""Index source loaders: the memory layout and the knowledge bundle layout."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

from varde_learn.knowledge.bundle import is_artifact_dir, is_reserved
from varde_learn.knowledge.concept import Concept
from varde_learn.knowledge.crud import relative_slug
from varde_learn.knowledge.frontmatter import FrontmatterError
from varde_learn.memory import migration_record, store
from varde_learn.memory.entry import Entry, EntryError, entry_from_concept, validate
from varde_learn.memory.rules import ERROR, WARNING, Issue

Loaded = tuple[list[Entry], list[Issue]]


def load_memory(root: Path) -> Loaded:
    """Entries under `<root>/<scope>/<key>/<id>.md`, plus unreadable-file issues."""
    return store.load_report(root)


def load_bundle(bundle: Path, *, scope_key: str) -> Loaded:
    """Entries for a knowledge bundle; flat and nested slugs both work.

    `knowledge/walk.py` aborts on the first file without front matter, so this
    walk reads each file on its own and reports bad files as issues.
    """
    entries: list[Entry] = []
    seen: set[str] = set()
    issues: list[Issue] = []
    for path in concept_files(bundle):
        try:
            concept = _read_concept(bundle, path)
        except (OSError, UnicodeDecodeError, FrontmatterError, ValueError) as error:
            issues.append(Issue(ERROR, "unreadable", str(error), str(path)))
            continue
        entry, warnings = entry_from_concept(
            concept,
            scope_key=scope_key,
            source=f"knowledge:{bundle.name}:{concept.slug}",
            mtime_date=_mtime_date(path),
        )
        issues.extend(Issue(WARNING, "concept-field", w, str(path)) for w in warnings)
        problem = _entry_problem(entry, seen)
        if problem:
            issues.append(Issue(WARNING, "concept-entry", problem, str(path)))
        seen.add(entry.id)
        entries.append(entry)
    return entries, issues


def concept_files(directory: Path) -> Iterator[Path]:
    for path in sorted(directory.iterdir()):
        name = path.name
        if name.startswith(".") or is_artifact_dir(name) or path.is_symlink():
            continue
        if path.is_dir():
            yield from concept_files(path)
        elif name.endswith(".md") and not is_reserved(name):
            yield path


def _read_concept(bundle: Path, path: Path) -> Concept:
    text = path.read_text(encoding="utf-8")
    slug = relative_slug(bundle, path)
    if not text.startswith("---"):
        return Concept(slug, {}, text)
    return Concept.from_bytes(text.encode(), slug)


def loader_for(root: Path, bundle: Path, *, scope_key: str) -> Callable[[], Loaded]:
    """One reader per fact: the memory loader once a migration record exists."""
    if migration_record.read_record(root, bundle) is not None:
        return partial(load_memory, root)
    return partial(load_bundle, bundle, scope_key=scope_key)


def _entry_problem(entry: Entry, seen: set[str]) -> str:
    try:
        validate(entry)
    except EntryError as error:
        return str(error)
    if entry.id in seen:
        return f"duplicate id after slug flattening: {entry.id}"
    return ""


def _mtime_date(path: Path) -> str:
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return ""
    return datetime.fromtimestamp(stamp, UTC).date().isoformat()
