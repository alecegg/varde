"""One-shot migration of `memory_tier_decisions.jsonl` into scoped entries.

The old module is gone, so this reads the JSONL itself. Mapping is by tier
only: user -> global, project -> project, role -> archived (counted, never
written as an entry).
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from varde_core.memory_dirs import project_key

from varde_learn.knowledge.memory import MemoryPaths, find_root
from varde_learn.memory import store
from varde_learn.memory.entry import Entry, EntryError, validate

OLD_LOG = "memory_tier_decisions.jsonl"
MIGRATED_LOG = OLD_LOG + ".migrated"
MIGRATING = ("approved", "applied")


@dataclass(frozen=True)
class Row:
    """Latest row for one proposal, with the first row's timestamp."""

    proposal_id: str
    note: str
    decision: str
    target_tier: str | None
    source_path: str | None
    target_path: str | None
    created: str


@dataclass
class Report:
    migrated: list[str] = field(default_factory=list)
    existing: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    archived_role: list[str] = field(default_factory=list)
    already_applied: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    dry_run: bool = False
    renamed: bool = False

    def counts(self) -> dict[str, int]:
        return {
            "migrated": len(self.migrated),
            "existing": len(self.existing),
            "skipped": len(self.skipped),
            "archived_role": len(self.archived_role),
            "already_applied": len(self.already_applied),
            "unresolved": len(self.unresolved),
            "failed": len(self.failed),
        }

    def complete(self) -> bool:
        """Only unresolved rows block the rename; failed rows are skipped and listed."""
        return not self.unresolved

    def render(self) -> str:
        lines = [f"{name}: {count}" for name, count in self.counts().items()]
        lines += [f"unresolved project: {i}" for i in self.unresolved]
        lines += [f"failed (skipped): {i}" for i in self.failed]
        if self.dry_run:
            lines.append("dry run: nothing written")
        elif self.renamed:
            lines.append(f"renamed log to {MIGRATED_LOG}")
        elif self.unresolved:
            lines.append("log kept: pass --project-root for the unresolved rows")
        return "\n".join(lines)


def read_rows(path: Path) -> list[Row]:
    """Latest row per `proposal_id`; torn or malformed lines are skipped."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return []
    latest: dict[str, dict] = {}
    first_ts: dict[str, str] = {}
    for line in lines:
        value = _parse_line(line)
        if value is None:
            continue
        pid = value["proposal_id"]
        first_ts.setdefault(pid, str(value.get("timestamp") or ""))
        latest[pid] = value
    return [_row(value, first_ts[pid]) for pid, value in latest.items()]


def _parse_line(line: str) -> dict | None:
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict):
        return None
    if not isinstance(value.get("proposal_id"), str) or not value["proposal_id"]:
        return None
    if not isinstance(value.get("note"), str):
        return None
    return value


def _row(value: dict, created: str) -> Row:
    return Row(
        proposal_id=value["proposal_id"],
        note=value["note"],
        decision=str(value.get("decision") or "pending"),
        target_tier=value.get("target_tier") or None,
        source_path=value.get("source_path") or None,
        target_path=value.get("target_path") or None,
        created=created,
    )


def to_entry(row: Row, scope: str, key: str) -> Entry:
    return Entry(
        id=row.proposal_id,
        scope=scope,
        scope_key=key,
        text=row.note,
        source=f"memory-tier {row.proposal_id}",
        created=row.created,
    )


def migrate(
    rows: list[Row],
    root: Path,
    *,
    project_of: Callable[[Row], str | None],
    applied_in_place: Callable[[Row], bool],
    dry_run: bool,
) -> Report:
    report = Report(dry_run=dry_run)
    for row in rows:
        _migrate_row(row, root, report, project_of, applied_in_place)
    return report


def _migrate_row(
    row: Row,
    root: Path,
    report: Report,
    project_of: Callable[[Row], str | None],
    applied_in_place: Callable[[Row], bool],
) -> None:
    pid = row.proposal_id
    if row.decision not in MIGRATING or row.target_tier not in (
        "user",
        "project",
        "role",
    ):
        report.skipped.append(pid)
        return
    if row.target_tier == "role":
        report.archived_role.append(pid)
        return
    if row.decision == "applied" and applied_in_place(row):
        report.already_applied.append(pid)
        return
    scope, key = ("global", "")
    if row.target_tier == "project":
        project = project_of(row)
        if project is None:
            report.unresolved.append(pid)
            return
        scope, key = "project", project
    _write(to_entry(row, scope, key), root, report)


def _write(entry: Entry, root: Path, report: Report) -> None:
    if store.entry_path(root, entry.scope, entry.scope_key, entry.id).exists():
        report.existing.append(entry.id)
        return
    try:
        if report.dry_run:
            validate(entry)
        else:
            store.write_entry(root, entry)
    except EntryError as error:
        report.failed.append(f"{entry.id} ({error})")
        return
    report.migrated.append(entry.id)


# ---- filesystem helpers (I/O) -------------------------------------------


def git_toplevel(path: Path) -> Path | None:
    """Git toplevel of the nearest existing ancestor directory of `path`."""
    start = path
    while not start.is_dir():
        if start.parent == start:
            return None
        start = start.parent
    result = subprocess.run(  # noqa: S603
        ["git", "-C", str(start), "rev-parse", "--show-toplevel"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    return Path(result.stdout.strip()) if result.returncode == 0 else None


def is_agent_memory_repo(top: Path, paths: MemoryPaths) -> bool:
    if top.name == "agent-memory":
        return True
    return any(root.is_relative_to(top) for root in paths.write_roots())


def make_project_of(
    paths: MemoryPaths, project_root: Path | None, cwd: Path
) -> Callable[[Row], str | None]:
    fallback = _fallback_key(project_root, cwd)

    def project_of(row: Row) -> str | None:
        note_path = row.target_path or row.source_path
        top = git_toplevel(Path(note_path).parent) if note_path else None
        if top is not None and not is_agent_memory_repo(top, paths):
            return project_key(MemoryPaths.resolve(top).root)
        return fallback

    return project_of


def _fallback_key(project_root: Path | None, cwd: Path) -> str | None:
    if project_root is not None:
        return project_key(MemoryPaths.resolve(project_root).root)
    found = find_root(cwd)
    return project_key(found) if found is not None else None


def make_applied_in_place(paths: MemoryPaths) -> Callable[[Row], bool]:
    def applied_in_place(row: Row) -> bool:
        if not row.target_path:
            return False
        target = Path(row.target_path).expanduser()
        if not target.exists():
            return False
        return any(
            target.resolve().is_relative_to(base.resolve())
            for base in (paths.knowledge.path, paths.memory.path)
        )

    return applied_in_place
