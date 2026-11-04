"""Migrate a knowledge bundle into the unified store, reversibly.

`plan_migration` reads only; `apply_migration` and `undo_migration` write under
the memory root. The source bundle is never edited.
"""

from __future__ import annotations

import posixpath
from collections import Counter
from dataclasses import dataclass, field, replace
from pathlib import Path

from varde_learn.knowledge.lint.links import link_spans
from varde_learn.knowledge.occ import version
from varde_learn.memory import migration_record, sources, store
from varde_learn.memory.entry import Entry, EntryError, find_secret, validate
from varde_learn.memory.searchindex import flatten_values

SCOPE = "project"


@dataclass(frozen=True)
class Reject:
    slug: str
    kind: str  # "secret", "invalid" or "unreadable"
    reason: str


@dataclass(frozen=True)
class LinkChange:
    slug: str
    link: str
    target: str  # new `<id>.md`, or "" when the link stays broken


@dataclass(frozen=True)
class Planned:
    slug: str
    entry: Entry
    path: Path
    status: str  # "new" or "unchanged"


@dataclass
class Plan:
    bundle: Path
    files: int = 0
    planned: list[Planned] = field(default_factory=list)
    collisions: list[Reject] = field(default_factory=list)
    rejects: list[Reject] = field(default_factory=list)
    links: list[LinkChange] = field(default_factory=list)

    def type_counts(self) -> dict[str, int]:
        return dict(sorted(Counter(p.entry.type for p in self.planned).items()))


@dataclass
class ApplyResult:
    created: list[Path] = field(default_factory=list)
    unchanged: list[Path] = field(default_factory=list)
    record: Path | None = None


@dataclass
class UndoResult:
    removed: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    missing: list[Path] = field(default_factory=list)
    record_removed: bool = False
    record_kept: bool = False


def plan_migration(bundle: Path, root: Path, scope_key: str) -> Plan:
    """What `--apply` would do. Writes nothing."""
    entries, issues = sources.load_bundle(bundle, scope_key=scope_key)
    plan = Plan(bundle, files=len(entries))
    plan.rejects += [
        Reject(i.path, "unreadable", i.message)
        for i in issues
        if i.code == "unreadable"
    ]
    plan.files += len(plan.rejects)
    prefix = f"knowledge:{bundle.name}:"
    usable: list[tuple[str, Entry]] = []
    for entry in entries:
        slug = entry.source.removeprefix(prefix)
        reason = rejection_of(entry)
        if reason:
            kind = "secret" if "secret" in reason else "invalid"
            plan.rejects.append(Reject(slug, kind, reason))
        else:
            usable.append((slug, entry))
    _plan_entries(plan, usable, root)
    return plan


def rejection_of(entry: Entry) -> str:
    """Why an entry may not be written (invalid or secret-like), else empty."""
    try:
        validate(entry)
    except EntryError as error:
        return str(error)
    metadata = [entry.title, entry.description, *entry.aliases, *entry.tags]
    metadata.append(flatten_values(entry.extra))
    if any(find_secret(text) for text in metadata):
        return "a metadata field looks like a secret"
    return ""


def _plan_entries(plan: Plan, usable: list[tuple[str, Entry]], root: Path) -> None:
    counts = Counter(entry.id for _, entry in usable)
    id_of = {slug: entry.id for slug, entry in usable if counts[entry.id] == 1}
    for slug, entry in sorted(usable, key=lambda item: item[0]):
        if counts[entry.id] > 1:
            plan.collisions.append(Reject(slug, "collision", f"id {entry.id} repeats"))
            continue
        body, changes = rewrite_links(slug, entry.text, id_of)
        plan.links += changes
        final = replace(entry, text=body)
        path = store.entry_path(root, SCOPE, entry.scope_key, entry.id)
        status = _existing_status(path, final)
        if status == "conflict":
            plan.collisions.append(
                Reject(slug, "collision", "file exists with other content")
            )
            continue
        plan.planned.append(Planned(slug, final, path, status))


def _existing_status(path: Path, entry: Entry) -> str:
    if not path.exists():
        return "new"
    same = path.read_text(encoding="utf-8") == store.to_document(entry)
    return "unchanged" if same else "conflict"


def rewrite_links(
    slug: str, body: str, id_of: dict[str, str]
) -> tuple[str, list[LinkChange]]:
    """Point relative `.md` links at new ids; report each link changed or broken."""
    changes: dict[str, LinkChange] = {}
    folder = posixpath.dirname(slug)
    spans = link_spans(body)
    for start, end, link in reversed(spans):
        if not link.endswith(".md") or "://" in link:
            continue
        target = posixpath.normpath(posixpath.join(folder, link)).removesuffix(".md")
        new_id = id_of.get(target)
        changes[link] = LinkChange(slug, link, f"{new_id}.md" if new_id else "")
        if new_id:
            body = body[:start] + f"{new_id}.md" + body[end:]
    targets = dict.fromkeys(link for _, _, link in spans)
    return body, [changes[link] for link in targets if link in changes]


def apply_migration(root: Path, plan: Plan) -> ApplyResult:
    """Write each planned entry, then the migration record."""
    result = ApplyResult()
    recorded: dict[str, str] = {}
    for item in plan.planned:
        if item.status == "new":
            store.write_entry(root, item.entry)
            result.created.append(item.path)
        else:
            result.unchanged.append(item.path)
        recorded[str(item.path)] = version(item.path.read_bytes())
    if recorded:
        result.record = migration_record.write_record(root, plan.bundle, recorded)
    return result


def undo_migration(root: Path, bundle: Path) -> UndoResult:
    """Remove recorded files whose bytes still match.

    The record goes when nothing changed is left; otherwise it is rewritten to
    list only the changed files, so the bundle stays read from the store.
    """
    result = UndoResult()
    record = migration_record.read_record(root, bundle)
    if record is None:
        return result
    kept: dict[str, str] = {}
    for name, expected in sorted(record.get("created", {}).items()):
        path = Path(name)
        if not path.resolve().is_relative_to(root.resolve()):
            result.skipped.append(path)
        elif not path.exists():
            result.missing.append(path)
        elif _unchanged_since(path, expected):
            path.unlink()
            result.removed.append(path)
        else:
            result.skipped.append(path)
            kept[name] = expected
    if kept:
        migration_record.write_record(root, bundle, kept)
        result.record_kept = True
    else:
        result.record_removed = migration_record.remove_record(root, bundle)
    return result


def _unchanged_since(path: Path, expected: str) -> bool:
    try:
        return version(path.read_bytes()) == expected
    except OSError:
        return False
