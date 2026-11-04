"""Links between entries: relative Markdown links resolved against the store."""

from __future__ import annotations

import posixpath
from dataclasses import dataclass, field

from varde_learn.knowledge.lint.links import extract_links
from varde_learn.memory.entry import Entry
from varde_learn.memory.rules import WARNING, Issue


def entry_rel(entry: Entry) -> str:
    """Store-relative POSIX path: `<scope>[/<key>]/<id>.md`."""
    parts = [entry.scope, entry.scope_key, f"{entry.id}.md"]
    return "/".join(part for part in parts if part)


@dataclass(frozen=True)
class LinkGraph:
    inbound: dict[str, list[str]] = field(default_factory=dict)
    broken: dict[str, list[str]] = field(default_factory=dict)


def resolve_link(link: str, source: Entry, known: set[str]) -> str | None:
    """Store-relative path a link names, or None when it names no entry.

    A link is tried relative to the linking entry's folder, then to the root.
    """
    folder = posixpath.dirname(entry_rel(source))
    for base in (folder, ""):
        candidate = posixpath.normpath(posixpath.join(base, link))
        if candidate in known:
            return candidate
    return None


def build_graph(entries: list[Entry]) -> LinkGraph:
    known = {entry_rel(e) for e in entries}
    inbound: dict[str, list[str]] = {rel: [] for rel in known}
    broken: dict[str, list[str]] = {}
    for entry in entries:
        source = entry_rel(entry)
        for link in _entry_links(entry):
            target = resolve_link(link, entry, known)
            if target is None:
                broken.setdefault(source, []).append(link)
            elif target != source and source not in inbound[target]:
                inbound[target].append(source)
    return LinkGraph(inbound, broken)


def lint_links(entries: list[Entry]) -> list[Issue]:
    """Warnings: a link to no entry, and an entry nothing links to."""
    graph = build_graph(entries)
    issues: list[Issue] = []
    for entry in sorted(entries, key=entry_rel):
        rel = entry_rel(entry)
        issues += [
            Issue(WARNING, "link-broken", f"link to no entry: {link}", rel)
            for link in graph.broken.get(rel, [])
        ]
        if not graph.inbound[rel]:
            issues.append(Issue(WARNING, "orphan", "no entry links here", rel))
    return issues


def linked_by(entries: list[Entry], target: Entry) -> list[str]:
    """Store-relative paths of entries that link to `target`."""
    return sorted(build_graph(entries).inbound.get(entry_rel(target), []))


def _entry_links(entry: Entry) -> list[str]:
    return [link for link in extract_links(entry.text) if link.endswith(".md")]
