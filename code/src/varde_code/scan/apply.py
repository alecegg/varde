"""Apply safe, per-file source rewrites produced by scan rules."""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from varde_code.git import run_git
from varde_code.rules.finding import FileState, Finding, resolve_real_path
from varde_code.rules.model import Rule, RuleKind
from varde_code.rules.rewrite import (
    RewritePlan,
    RewriteStatus,
    RewriteTarget,
    plan_file_rewrites,
    substitute_with_source,
)


@dataclass(frozen=True)
class FileTarget:
    finding: Finding
    template: str
    target: RewriteTarget


@dataclass(frozen=True)
class GitGate:
    kind: str
    worktree: Path | None = None
    dirty_paths: frozenset[Path] = frozenset()

    def dirty(self, path: Path) -> bool:
        return self.kind == "unverifiable" or (
            self.kind == "worktree" and path in self.dirty_paths
        )

    def recheck_dirty(self, path: Path) -> bool:
        if self.kind == "not-git":
            return False
        if self.kind == "unverifiable":
            return True
        if self.worktree is None or not path.is_relative_to(self.worktree):
            return False
        result = status_dirty_paths(self.worktree, [path])
        return result is None or path in result


def apply_rewrites(
    rules: list[Rule], findings: list[Finding], repo_root: Path, force: bool = False
) -> dict[str, RewriteStatus]:
    rewrites = {
        rule.id: rule.rewrite
        for rule in rules
        if rule.kind == RuleKind.PATTERN and rule.rewrite is not None
    }
    if not rewrites:
        return {}
    by_file = group_rewrite_targets(findings, rewrites)
    gate = GitGate("not-git") if force else git_gate(repo_root.resolve(), list(by_file))
    statuses: dict[str, RewriteStatus] = {}
    for path, targets in by_file.items():
        apply_file_rewrites(path, targets, gate, statuses)
    return statuses


def group_rewrite_targets(
    findings: list[Finding], rewrites: dict[str, str]
) -> dict[Path, list[FileTarget]]:
    grouped: dict[Path, list[FileTarget]] = {}
    for finding in findings:
        template = rewrites.get(finding.rule_id)
        if template is None:
            continue
        span = finding.location.span
        path = resolve_real_path(finding.location.file)
        grouped.setdefault(path, []).append(
            FileTarget(
                finding, template, RewriteTarget(span.start_byte, span.end_byte, "")
            )
        )
    return grouped


def apply_file_rewrites(
    path: Path,
    targets: list[FileTarget],
    gate: GitGate,
    statuses: dict[str, RewriteStatus],
) -> None:
    if gate.dirty(path):
        _mark(targets, RewriteStatus.SKIPPED_DIRTY, statuses)
        return
    replacements = _planned_targets(targets, statuses)
    if not replacements:
        return
    content = read_verified_content(path, targets, statuses)
    if content is None:
        return
    rendered = render_rewrites(content, replacements)
    if rendered is None:
        _mark(targets, RewriteStatus.SKIPPED_CONFLICT, statuses)
        return
    if gate.recheck_dirty(path):
        _mark(targets, RewriteStatus.SKIPPED_DIRTY, statuses)
        return
    try:
        write_atomic(path, rendered)
    except OSError:
        _mark(targets, RewriteStatus.SKIPPED_CONFLICT, statuses)


def _planned_targets(
    targets: list[FileTarget], statuses: dict[str, RewriteStatus]
) -> list[FileTarget]:
    plans = plan_file_rewrites([target.target for target in targets])
    selected = []
    for target, plan in zip(targets, plans, strict=True):
        status = (
            RewriteStatus.APPLIED
            if plan == RewritePlan.APPLY
            else RewriteStatus.SKIPPED_OVERLAP
        )
        statuses[target.finding.id] = status
        if status == RewriteStatus.APPLIED:
            selected.append(target)
    return selected


def read_verified_content(
    path: Path, targets: list[FileTarget], statuses: dict[str, RewriteStatus]
) -> str | None:
    before = FileState.of(path)
    try:
        content = path.read_bytes().decode("utf-8")
    except OSError, UnicodeDecodeError:
        _mark(targets, RewriteStatus.SKIPPED_CONFLICT, statuses)
        return None
    after = FileState.of(path)
    for target in targets:
        expected = target.finding.matched_file_state
        if expected is not None and (
            before != expected
            or after != expected
            or len(content.encode("utf-8")) != expected.length
        ):
            _mark(targets, RewriteStatus.SKIPPED_CONFLICT, statuses)
            return None
    return content


def render_rewrites(content: str, targets: list[FileTarget]) -> str | None:
    replacements = [
        RewriteTarget(
            target.target.start_byte,
            target.target.end_byte,
            substitute_with_source(target.template, target.finding.evidence, content),
        )
        for target in targets
    ]
    replacements.sort(key=lambda item: (item.start_byte, item.end_byte))
    return splice(content, replacements)


def git_gate(repo_root: Path, targets: list[Path]) -> GitGate:
    root = _canonical(repo_root)
    target_paths = [_canonical(path) for path in targets]
    inside = run_git(["rev-parse", "--is-inside-work-tree"], root)
    if inside is None or inside.strip() != "true":
        return GitGate("not-git")
    top = run_git(["rev-parse", "--show-toplevel"], root)
    if top is None:
        return GitGate("unverifiable")
    worktree = _canonical(Path(top.strip()))
    in_tree = [path for path in target_paths if path.is_relative_to(worktree)]
    if not in_tree:
        return GitGate("worktree", worktree)
    dirty = status_dirty_paths(worktree, in_tree)
    return (
        GitGate("unverifiable")
        if dirty is None
        else GitGate("worktree", worktree, frozenset(dirty))
    )


def status_dirty_paths(worktree: Path, targets: list[Path]) -> set[Path] | None:
    dirty: set[Path] = set()
    for offset in range(0, len(targets), 1000):
        chunk = targets[offset : offset + 1000]
        args = [
            "-c",
            "status.renames=false",
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--ignored",
            "-z",
            "--",
            *(str(path) for path in chunk),
        ]
        try:
            result = subprocess.run(  # noqa: S603 - Runs git with constructed worktree arguments.
                ["git", *args],  # noqa: S607 - Uses the system git executable from PATH.
                cwd=worktree,
                capture_output=True,
                check=False,
            )
        except OSError:
            return None
        if result.returncode:
            return None
        records = parse_porcelain_dirty_paths(result.stdout)
        if records is None:
            return None
        dirty.update(_canonical(worktree / record) for record in records)
    return dirty


def parse_porcelain_dirty_paths(status: str | bytes) -> list[str] | None:
    raw = status.encode() if isinstance(status, str) else status
    records = []
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        if (
            len(entry) < 4
            or entry[2:3] != b" "
            or any(byte not in b" M TADRCU?!" for byte in entry[:2])
        ):
            return None
        records.append(os.fsdecode(entry[3:]))
    return records


def splice(content: str, targets: list[RewriteTarget]) -> str | None:
    source = content.encode("utf-8")
    output = bytearray()
    cursor = 0
    for target in targets:
        start, end = target.start_byte, target.end_byte
        if start < cursor or end > len(source):
            return None
        try:
            source[:start].decode("utf-8")
            source[:end].decode("utf-8")
        except UnicodeDecodeError:
            return None
        output.extend(source[cursor:start])
        output.extend(target.replacement.encode("utf-8"))
        cursor = end
    output.extend(source[cursor:])
    return output.decode("utf-8")


def write_atomic(path: Path, content: str) -> None:
    mode = path.stat().st_mode if path.exists() else None
    fd, name = tempfile.mkstemp(
        prefix=f".{path.name}.varde-apply-tmp-", dir=path.parent
    )
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content.encode("utf-8"))
        if mode is not None:
            temp.chmod(mode)
        temp.replace(path)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


def attach_rewrite_statuses(
    payload: dict[str, Any], statuses: dict[str, RewriteStatus], expected_count: int
) -> None:
    if len(statuses) != expected_count:
        raise ValueError("rewrite status count does not match rewrite-bearing findings")
    for finding in payload.get("findings", []):
        status = statuses.get(finding.get("id"))
        if status is not None:
            finding["rewrite_status"] = status.value
    counts = Counter(status.value for status in statuses.values())
    if counts:
        payload["rewrite_summary"] = {
            key: counts[key]
            for key in (
                "applied",
                "skipped-dirty",
                "skipped-overlap",
                "skipped-conflict",
            )
            if counts[key]
        }


def _mark(
    targets: list[FileTarget], status: RewriteStatus, statuses: dict[str, RewriteStatus]
) -> None:
    for target in targets:
        statuses[target.finding.id] = status


def _canonical(path: Path) -> Path:
    try:
        return path.resolve(strict=True)
    except OSError:
        return path.absolute()
