"""Deterministic map of the store, grouped by scope and type."""

from __future__ import annotations

import os
from collections.abc import Sequence
from pathlib import Path

from varde_learn.memory.entry import SCOPES, Entry, EntryError, summary_of
from varde_learn.memory.links import entry_rel


def build_map(
    root: Path,
    entries: Sequence[Entry],
    destination: Path | None = None,
    bundles: Sequence[Path] = (),
) -> str:
    """Return the map text; write it only when a destination is given.

    A destination inside any of `bundles` (a source bundle) is refused.
    """
    folder = destination.parent if destination else root
    text = render_map(root, entries, folder)
    if destination is not None:
        _refuse_inside(destination, bundles)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")
    return text


def render_map(root: Path, entries: Sequence[Entry], folder: Path) -> str:
    lines = ["# Memory map", ""]
    for scope in SCOPES:
        scoped = [e for e in entries if e.scope == scope]
        if scoped:
            lines += _scope_lines(root, folder, scope, scoped)
    return "\n".join(lines).rstrip("\n") + "\n"


def _scope_lines(
    root: Path, folder: Path, scope: str, scoped: list[Entry]
) -> list[str]:
    lines = [f"## {scope}", ""]
    for kind in sorted({e.type for e in scoped}):
        lines += [f"### {kind}", ""]
        group = sorted((e for e in scoped if e.type == kind), key=entry_rel)
        lines += [_entry_line(root, folder, e) for e in group]
        lines.append("")
    return lines


def _entry_line(root: Path, folder: Path, entry: Entry) -> str:
    target = os.path.relpath(root / entry_rel(entry), folder).replace(os.sep, "/")
    label = entry.title or entry.id
    summary = summary_of(entry)
    return f"- [{label}]({target})" + (f" - {summary}" if summary else "")


def _refuse_inside(destination: Path, bundles: Sequence[Path]) -> None:
    target = destination.resolve()
    for bundle in bundles:
        if target.is_relative_to(bundle.resolve()):
            raise EntryError(f"map destination is inside a source bundle: {bundle}")
