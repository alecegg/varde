"""Plain-file memory store: `<root>/<scope>[/<key>]/<id>.md`."""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

from varde_core.frontmatter import FrontmatterError, parse, serialize
from varde_core.memory_dirs import project_key

from varde_learn.knowledge.memory import MemoryPaths
from varde_learn.memory.entry import (
    DEFAULT_TYPE,
    SCOPES,
    Entry,
    EntryError,
    validate,
)
from varde_learn.memory.rules import ERROR, Issue

_FIELDS = (
    "id",
    "scope",
    "scope_key",
    "project",
    "source",
    "created",
    "status",
    "model",
    "harness_version",
)
_OPTIONAL_TEXT_FIELDS = ("topic", "valid_until", "updated", "title", "description")
_KNOWN_KEYS = frozenset(
    (*_FIELDS, *_OPTIONAL_TEXT_FIELDS, "tags", "type", "surface", "aliases")
)


def memory_root(project_root: Path | str) -> Path:
    return MemoryPaths.resolve(project_root).memory.path


def current_project_key(cwd: Path | str) -> str:
    """Project key of the repository containing `cwd` (worktree-stable)."""
    return project_key(MemoryPaths.resolve(cwd).root)


def memory_root_and_project(cwd: Path | str) -> tuple[Path, str]:
    """Memory root and worktree-stable project key from one path resolution."""
    paths = MemoryPaths.resolve(cwd)
    return paths.memory.path, project_key(paths.root)


def entry_path(root: Path, scope: str, scope_key: str, entry_id: str) -> Path:
    base = root / scope
    return (base / scope_key if scope_key else base) / f"{entry_id}.md"


def generate_id(text: str, scope: str, created: str) -> str:
    digest = hashlib.sha256(f"{scope}\0{created}\0{text}".encode()).hexdigest()
    return digest[:10]


def to_document(entry: Entry) -> str:
    front: dict[str, object] = {name: getattr(entry, name) for name in _FIELDS}
    front = {k: v for k, v in front.items() if v != "" or k == "scope_key"}
    front["tags"] = list(entry.tags)
    front.update(_unified_front(entry))
    for key, value in entry.extra.items():
        front.setdefault(key, value)
    return serialize(front, entry.text.rstrip("\n") + "\n")


def _unified_front(entry: Entry) -> dict[str, object]:
    """Unified fields, written only when they differ from the old-file defaults."""
    front: dict[str, object] = {}
    if entry.type != DEFAULT_TYPE:
        front["type"] = entry.type
    if not entry.surface:
        front["surface"] = False
    if entry.aliases:
        front["aliases"] = list(entry.aliases)
    for name in _OPTIONAL_TEXT_FIELDS:
        if value := getattr(entry, name):
            front[name] = value
    return front


def from_document(data: str) -> Entry:
    front, body = parse(data)
    return Entry(
        id=str(front.get("id", "")),
        scope=str(front.get("scope", "")),
        scope_key=str(front.get("scope_key") or ""),
        text=body.strip("\n"),
        source=str(front.get("source") or ""),
        created=str(front.get("created") or ""),
        status=str(front.get("status") or "active"),
        tags=tuple(str(t) for t in front.get("tags") or ()),
        project=str(front.get("project") or ""),
        model=str(front.get("model") or ""),
        harness_version=str(front.get("harness_version") or ""),
        type=str(front.get("type") or DEFAULT_TYPE),
        topic=str(front.get("topic") or ""),
        valid_until=str(front.get("valid_until") or ""),
        surface=front.get("surface", True) is not False,
        updated=str(front.get("updated") or ""),
        title=str(front.get("title") or ""),
        aliases=tuple(str(a) for a in front.get("aliases") or ()),
        description=str(front.get("description") or ""),
        extra={k: v for k, v in front.items() if k not in _KNOWN_KEYS},
    )


def write_entry(root: Path, entry: Entry, *, overwrite: bool = False) -> Path:
    validate(entry)
    path = entry_path(root, entry.scope, entry.scope_key, entry.id)
    if path.exists() and not overwrite:
        raise EntryError(f"entry already exists: {entry.id}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_document(entry), encoding="utf-8")
    return path


def read_entry(path: Path, root: Path) -> Entry:
    """Read one file; its frontmatter must agree with its location."""
    entry = from_document(path.read_text(encoding="utf-8"))
    validate(entry)
    expected = entry_path(root, entry.scope, entry.scope_key, entry.id)
    if expected != path:
        raise EntryError(f"frontmatter does not match path: {path}")
    return entry


def load_report(root: Path) -> tuple[list[Entry], list[Issue]]:
    """Read every entry file; report each unreadable file as an issue."""
    entries: list[Entry] = []
    issues: list[Issue] = []
    for scope in SCOPES:
        for path in sorted((root / scope).rglob("*.md")):
            try:
                entries.append(read_entry(path, root))
            except (EntryError, FrontmatterError, OSError, UnicodeDecodeError) as error:
                issues.append(Issue(ERROR, "unreadable", str(error), str(path)))
    return entries, issues


def load_entries(root: Path) -> Iterator[Entry]:
    """Yield valid entries; warn on stderr about files that fail to load."""
    entries, issues = load_report(root)
    for issue in issues:
        print(f"warning: skipped {issue.path}: {issue.message}", file=sys.stderr)
    yield from entries


def set_status(root: Path, entry: Entry, status: str) -> Entry:
    updated = replace(entry, status=status)
    write_entry(root, updated, overwrite=True)
    return updated
