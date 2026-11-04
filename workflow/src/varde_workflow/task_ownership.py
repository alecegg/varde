"""Audit changed commit paths against task ownership declarations."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from varde_learn.knowledge.cmdbase.errors import ExitCode
from varde_learn.knowledge.frontmatter import parse

from .execution_wave_paths import (
    canonical_declaration,
    declarations_overlap,
    matches_declaration,
    matching_paths,
)


class OwnershipError(Exception, ExitCode):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message

    def error_code(self) -> str:
        return self.code

    def exit_code(self) -> int:
        return 1


@dataclass
class OwnershipAudit:
    status: str
    stray: list[str]
    declared: list[str]
    changed: list[str]
    blockers: list[str] = field(default_factory=list)


@dataclass
class OwnershipDeclarations:
    owned: set[str] = field(default_factory=set)
    owns: set[str] = field(default_factory=set)
    creates: set[str] = field(default_factory=set)
    generated: set[str] = field(default_factory=set)


@dataclass
class OwnershipResolution:
    declared: list[str]
    blockers: list[str]
    excludes: list[str]

    def owns_path(self, path: str) -> bool:
        return any(matches_declaration(d, path) for d in self.declared) and not any(
            matches_declaration(x, path) for x in self.excludes
        )


def resolve(
    root: Path,
    declarations: OwnershipDeclarations,
    excludes: list[str],
    widened: list[str] | None,
    changed: set[str],
) -> OwnershipResolution:
    blockers: set[str] = set()
    canonical_excludes = []
    for exclude in excludes:
        try:
            canonical_excludes.append((exclude, canonical_declaration(root, exclude)))
        except ValueError as error:
            blockers.add(f"{exclude}: {error}")
    paths = dict.fromkeys(declarations.owned, False)
    for path in (
        declarations.owns
        | declarations.creates
        | declarations.generated
        | set(widened or [])
    ):
        paths.setdefault(path, True)
    resolved = set()
    for path, may_be_missing in paths.items():
        try:
            canonical = canonical_declaration(root, path)
        except ValueError as error:
            blockers.add(f"{path}: {error}")
            continue
        is_bare_directory = (
            "*" not in path and not path.endswith("/") and (root / path).is_dir()
        )
        resolved.add(path + "/" if is_bare_directory else path)
        for excluded, identity in canonical_excludes:
            if declarations_overlap(canonical, identity):
                blockers.add(f"{path}: overlaps excluded path {excluded}")
        try:
            matches = matching_paths(root, canonical)
        except (OSError, ValueError) as error:
            blockers.add(f"{path}: {error}")
            continue
        changed_match = any(matches_declaration(path, item) for item in changed)
        if not matches and not may_be_missing and not changed_match:
            why = (
                "matches no repository paths"
                if "*" in path
                else "directory does not exist"
                if path.endswith("/")
                else "path does not exist"
            )
            blockers.add(f"{path}: {why}")
    return OwnershipResolution(sorted(resolved), sorted(blockers), excludes)


def _list(fm: dict[str, Any], key: str) -> list[str]:
    value = fm.get(key, [])
    if not isinstance(value, list):
        raise OwnershipError("unreadable_task", f"{key} must be a list of strings")
    if not all(isinstance(item, str) for item in value):
        raise OwnershipError("unreadable_task", f"{key} must contain only strings")
    return value


def _declared(fm: dict[str, Any]) -> OwnershipDeclarations:
    owned, owns = set(_list(fm, "modifies")), set(_list(fm, "owns"))
    creates = set(_list(fm, "creates"))
    for rename in _list(fm, "renames"):
        parts = rename.split("->")
        if len(parts) != 2 or any(not part.strip() for part in parts):
            raise OwnershipError("unreadable_task", f"invalid rename entry: {rename}")
        owned.add(parts[0].strip())
        creates.add(parts[1].strip())
    return OwnershipDeclarations(owned, owns, creates)


def _git(root: Path, args: list[str], reject_stderr: bool = False) -> str:
    try:
        result = subprocess.run(  # noqa: S603 - Runs controlled repository inspection arguments.
            ["git", "-C", str(root), *args],  # noqa: S607 - Git is resolved from PATH.
            check=False,
            capture_output=True,
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise OwnershipError("git_error", str(error)) from error
    if result.returncode or (reject_stderr and result.stderr):
        raise OwnershipError(
            "git_error", result.stderr.decode("utf-8", "replace").strip()
        )
    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError as error:
        raise OwnershipError(
            "git_error", "Git returned a non-UTF-8 path or response"
        ) from error


def _commit(root: Path, ref: str) -> str:
    if not ref or ref.startswith("-"):
        raise OwnershipError(
            "git_error", "commit reference must be a nonempty revision, not an option"
        )
    value = _git(
        root,
        [
            "-c",
            "core.warnAmbiguousRefs=true",
            "rev-parse",
            "--verify",
            "--end-of-options",
            f"{ref}^{{commit}}",
        ],
        True,
    ).strip()
    if len(value) not in (40, 64) or any(
        c not in "0123456789abcdefABCDEF" for c in value
    ):
        raise OwnershipError("git_error", "Git did not resolve one commit object")
    return value


def check(
    task: Path, reference: str, root: Path, trusted_tips: list[str]
) -> OwnershipAudit:
    task = task.resolve()
    try:
        fm, _ = parse(task.read_bytes())
    except Exception as error:
        raise OwnershipError("unreadable_task", f"{task}: {error}") from error
    declarations = _declared(fm)
    plan = task.parent.parent / "plan.md" if task.parent.name == "tasks" else None
    if plan and plan.exists():
        try:
            plan_fm, _ = parse(plan.read_bytes())
            declarations.generated = set(
                _list(plan_fm, "generated") + _list(plan_fm, "shared")
            )
        except Exception as error:
            raise OwnershipError("unreadable_task", f"{plan}: {error}") from error
    kind = fm.get("kind", "")
    if not isinstance(kind, str):
        raise OwnershipError("unreadable_task", "kind must be a string")
    if kind == "spike" or (
        not declarations.generated
        and not any(k in fm for k in ("owns", "modifies", "creates", "renames"))
    ):
        declared = sorted(
            declarations.owned
            | declarations.owns
            | declarations.creates
            | declarations.generated
        )
        return OwnershipAudit("skipped", [], declared, [])
    root = root.resolve()
    for tip in trusted_tips:
        commit = _commit(root, tip)
        result = subprocess.run(  # noqa: S603 - Checks ancestry of a validated commit.
            ["git", "-C", str(root), "merge-base", "--is-ancestor", commit, "HEAD"],  # noqa: S607 - Git is resolved from PATH.
            capture_output=True,
            check=False,
        )
        if result.returncode:
            raise OwnershipError(
                "git_error",
                f"trusted tip {commit} is not an ancestor of integration branch HEAD",
            )
    commit = _commit(root, reference)
    parents = _git(root, ["rev-list", "--parents", "-n", "1", commit]).split()[1:]
    if len(parents) <= 1:
        changed = set(
            filter(
                None,
                _git(
                    root,
                    [
                        "diff-tree",
                        "-z",
                        "--root",
                        "--no-commit-id",
                        "--name-only",
                        "--no-renames",
                        "-r",
                        commit,
                        "--",
                    ],
                ).split("\0"),
            )
        )
    else:
        diffs = [
            set(
                filter(
                    None,
                    _git(
                        root,
                        [
                            "diff",
                            "--name-only",
                            "--no-renames",
                            "-z",
                            parent,
                            commit,
                            "--",
                        ],
                    ).split("\0"),
                )
            )
            for parent in parents
        ]
        changed = set.intersection(*diffs) if diffs else set()
    try:
        task_relative = task.relative_to(root).as_posix()
    except ValueError:
        task_relative = None
    changed.discard(task_relative)
    resolution = resolve(root, declarations, [], None, changed)
    if resolution.blockers:
        return OwnershipAudit(
            "invalid", [], resolution.declared, sorted(changed), resolution.blockers
        )
    stray = sorted(path for path in changed if not resolution.owns_path(path))
    return OwnershipAudit(
        "stray" if stray else "ok", stray, resolution.declared, sorted(changed)
    )
