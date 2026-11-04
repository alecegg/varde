"""Deterministic checks for a task commit before integration."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from varde_core.layer_check import layer_violations
from varde_learn.knowledge.frontmatter import parse

from .execution_wave import derived_scope, serial_plan
from .execution_wave_paths import paths_outside_scope
from .review_structure import review_structure
from .task_ownership import OwnershipError
from .task_ownership import check as check_ownership

MAX_TOKENS = 60_000
DOC_PATH = re.compile(r"(^|/)(SKILL\.md|AGENTS\.md|CLAUDE\.md)$")


def _raise_missing_token_header() -> NoReturn:
    raise ValueError("review-scope.sh did not print a # tokens header")


@dataclass(frozen=True)
class GateResult:
    check: str
    status: str
    detail: str
    fix: str = ""


def evaluate(
    task: Path,
    commit: str | None = None,
    repository_path: Path | None = None,
) -> tuple[list[GateResult], bool]:
    task = task.resolve()
    repository = _repository_root(repository_path or Path.cwd())
    target = _commit(repository, commit or "HEAD")
    head = _commit(repository, "HEAD")
    if not _ancestor(repository, target, head):
        raise ValueError(f"commit {target} is not an ancestor of HEAD")
    worktree = repository
    plan_path = task.parent.parent / "plan.md"
    review_path = plan_path.parent / "review.md"
    frontmatter, _ = parse(plan_path.read_bytes())
    changed = _changed_files(repository, target)
    results = [*_review_result(review_path, repository)]
    if serial_plan(plan_path.parent):
        results.append(_scope_result(plan_path, frontmatter, target, repository))
    else:
        results.extend(_ownership_result(task, target, worktree))
    results.extend(_size_result(worktree, target))
    results.extend(_gate_command_results(frontmatter.get("gate", []), worktree))
    results.append(GateResult("scan", *_scan(worktree, changed)))
    results.extend(_doc_lint_results(changed, worktree))
    results.extend(_layer_results(changed, worktree))
    return results, any(result.status == "fail" for result in results)


def _review_result(path: Path, repository: Path) -> list[GateResult]:
    if not path.is_file():
        return []
    errors = review_structure(path, repo=repository)
    return [
        GateResult(
            "review structure",
            "fail" if errors else "pass",
            "; ".join(errors) or "review structure is valid",
        )
    ]


def _ownership_result(task: Path, commit: str, worktree: Path) -> list[GateResult]:
    try:
        ownership = check_ownership(task, commit, worktree, [])
        ok = ownership.status != "stray" and not ownership.blockers
        detail = ", ".join(ownership.stray or ownership.blockers) or ownership.status
        return [GateResult("ownership", "pass" if ok else "fail", detail)]
    except (OSError, ValueError, OwnershipError) as error:
        return [GateResult("ownership", "fail", str(error))]


def _scope_result(
    plan_path: Path, frontmatter: dict[str, object], commit: str, repository: Path
) -> GateResult:
    try:
        scope = _scope_entries(plan_path, frontmatter)
        if scope is None:
            return GateResult("scope", "skipped", "no scope or ownership declarations")
        base = _default_branch_merge_base(repository, commit)
        paths = _net_diff(repository, base, commit)
    except (OSError, TypeError, ValueError, OwnershipError) as error:
        return GateResult("scope", "fail", str(error))
    exempt = _plan_memory_paths(plan_path, repository)
    stray = [path for path in paths_outside_scope(paths, scope) if not exempt(path)]
    if stray:
        return GateResult(
            "scope", "fail", ", ".join(stray), "add the path to `scope:` in plan.md"
        )
    return GateResult("scope", "pass", f"{len(paths)} net-diff path(s) in scope")


def _scope_entries(plan_path: Path, frontmatter: dict[str, object]) -> list[str] | None:
    """Declared scope, else the union of task ownership declarations; None if empty."""
    shared = frontmatter.get("shared", []) + frontmatter.get("generated", [])  # type: ignore[operator]
    declared = frontmatter.get("scope")
    if declared is not None:
        if not isinstance(declared, list) or not all(
            isinstance(item, str) and item for item in declared
        ):
            raise ValueError("scope must be a list of non-empty strings")
        entries = [*declared, *shared]
    else:
        entries = list(shared)
        entries += sorted(derived_scope(plan_path.parent))
        if not entries:
            return None
    # A bare name may be a file or a directory: accept the path and its subtree.
    return [
        variant
        for entry in dict.fromkeys(entries)
        for variant in _with_directory_form(entry)
    ]


def _with_directory_form(entry: str) -> list[str]:
    if "*" in entry or entry.endswith("/"):
        return [entry]
    return [entry, entry + "/"]


def _plan_memory_paths(plan_path: Path, repository: Path):
    try:
        relative = (
            plan_path.parent.resolve().relative_to(repository.resolve()).as_posix()
        )
    except ValueError:
        return lambda path: False
    return lambda path: (
        path == f"{relative}/plan.md" or path.startswith(f"{relative}/tasks/")
    )


def _default_branch_merge_base(repository: Path, commit: str) -> str:
    for candidate in _default_branch_candidates(repository):
        result = subprocess.run(
            ["git", "-C", str(repository), "rev-parse", "--verify", "-q", candidate],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            continue
        base = subprocess.run(
            ["git", "-C", str(repository), "merge-base", result.stdout.strip(), commit],
            capture_output=True,
            text=True,
            check=False,
        )
        if base.returncode or not base.stdout.strip():
            raise ValueError(f"no merge-base between {candidate} and {commit}")
        return base.stdout.strip()
    raise ValueError("no default branch found (tried origin/HEAD, main, master)")


def _default_branch_candidates(repository: Path) -> list[str]:
    head = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "symbolic-ref",
            "-q",
            "refs/remotes/origin/HEAD",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    origin = (
        [head.stdout.strip()] if head.returncode == 0 and head.stdout.strip() else []
    )
    return [*origin, "refs/heads/main", "refs/heads/master"]


def _net_diff(repository: Path, base: str, commit: str) -> list[str]:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "diff",
            "--name-only",
            "--no-renames",
            "-z",
            base,
            commit,
            "--",
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise ValueError("cannot list net diff of plan branch")
    return sorted(path for path in result.stdout.decode().split("\0") if path)


def _size_result(worktree: Path, commit: str) -> list[GateResult]:
    try:
        tokens = scope_tokens(_scope(worktree, commit))
        if tokens is None:
            _raise_missing_token_header()
        over = tokens > MAX_TOKENS
        return [
            GateResult(
                "size",
                "fail" if over else "pass",
                f"{tokens} tokens (budget {MAX_TOKENS})",
            )
        ]
    except (OSError, ValueError) as error:
        return [GateResult("size", "fail", str(error))]


def _gate_command_results(commands: object, worktree: Path) -> list[GateResult]:
    if not isinstance(commands, list) or any(
        not isinstance(item, str) for item in commands
    ):
        return [
            GateResult(
                "gate commands", "fail", "plan gate must be a list of shell commands"
            )
        ]
    results = []
    for index, command in enumerate(commands, 1):
        try:
            result = subprocess.run(  # noqa: S602 - Plan gate entries are explicitly defined shell commands, executed in the task worktree.
                command,
                shell=True,
                cwd=worktree,
                capture_output=True,
                text=True,
                check=False,
            )
            status, detail = (
                "pass" if result.returncode == 0 else "fail",
                _command_detail(command, result.returncode, result.stderr),
            )
        except OSError as error:
            status, detail = "fail", f"{command}: {error}"
        results.append(GateResult(f"gate command {index} ({command})", status, detail))
    return results


def _doc_lint_results(changed: list[str], worktree: Path) -> list[GateResult]:
    documents = [path for path in changed if DOC_PATH.search(path)]
    if not documents:
        return [
            GateResult("learn check", "skipped", "no skill or agent documents changed")
        ]
    result = subprocess.run(
        ["varde", "learn", "check", *[str(worktree / path) for path in documents]],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    return [
        GateResult(
            "learn check",
            "pass" if result.returncode == 0 else "fail",
            _command_detail("varde learn check", result.returncode, result.stderr),
        )
    ]


def _layer_results(changed: list[str], worktree: Path) -> list[GateResult]:
    sources = [
        worktree / path
        for path in changed
        if path.endswith(".py") and (worktree / path).is_file()
    ]
    if not (worktree / "layers.toml").is_file() or not sources:
        return [GateResult("layers", "skipped", "no layered Python files changed")]
    violations = layer_violations(worktree, sources)
    if violations:
        return [GateResult("layers", "fail", "; ".join(violations))]
    return [GateResult("layers", "pass", f"{len(sources)} file(s) checked")]


def _repository_root(path: Path) -> Path:
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode or not result.stdout.strip():
        raise ValueError("task is not inside a Git worktree")
    return Path(result.stdout.strip()).resolve()


def _commit(repository: Path, reference: str) -> str:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "rev-parse",
            "--verify",
            "--end-of-options",
            f"{reference}^{{commit}}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise ValueError(f"cannot resolve commit {reference}")
    return result.stdout.strip()


def _ancestor(repository: Path, commit: str, head: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(repository), "merge-base", "--is-ancestor", commit, head],
            check=False,
        ).returncode
        == 0
    )


def _changed_files(repository: Path, commit: str) -> list[str]:
    result = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-only",
            "-r",
            "-z",
            commit,
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise ValueError("cannot list files changed by task commit")
    return sorted(path for path in result.stdout.decode().split("\0") if path)


def _scope(worktree: Path, commit: str) -> str:
    script = (
        Path(__file__).parent
        / "skills"
        / "varde-review"
        / "scripts"
        / "review-scope.sh"
    )
    with tempfile.TemporaryDirectory(prefix="varde-gate-scope-") as temporary:
        scope_worktree = Path(temporary) / "worktree"
        added = subprocess.run(
            [
                "git",
                "-C",
                str(worktree),
                "worktree",
                "add",
                "--detach",
                str(scope_worktree),
                commit,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if added.returncode:
            raise ValueError(f"cannot create scope worktree: {added.stderr.strip()}")
        try:
            parent = subprocess.run(
                [
                    "git",
                    "-C",
                    str(scope_worktree),
                    "rev-parse",
                    "--verify",
                    f"{commit}^",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if parent.returncode:
                result = subprocess.run(
                    ["bash", str(script), "area", *_changed_files(worktree, commit)],
                    cwd=scope_worktree,
                    capture_output=True,
                    text=True,
                    check=False,
                )
            else:
                result = subprocess.run(
                    ["bash", str(script), "diff", "--ref", parent.stdout.strip()],
                    cwd=scope_worktree,
                    capture_output=True,
                    text=True,
                    check=False,
                )
        finally:
            removed = subprocess.run(
                [
                    "git",
                    "-C",
                    str(worktree),
                    "worktree",
                    "remove",
                    "--force",
                    str(scope_worktree),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if removed.returncode:
                raise ValueError(
                    f"cannot remove scope worktree: {removed.stderr.strip()}"
                )
    if result.returncode:
        raise ValueError(f"review-scope.sh failed: {result.stderr.strip()}")
    return result.stdout


def scope_tokens(header: str) -> int | None:
    match = re.search(r"^# tokens\t(\d+)$", header, re.MULTILINE)
    return int(match.group(1)) if match else None


def _command_detail(command: str, returncode: int, stderr: str) -> str:
    last_line = next(
        (line.strip() for line in reversed(stderr.splitlines()) if line.strip()), ""
    )
    detail = f"{command} exited {returncode}"
    return f"{detail}: {last_line}" if last_line else detail


_INDEX_RECOVERY = (
    "index is missing or stale; worktrees have no index: run "
    "`varde map build` on the main checkout, then check `varde map packs status`"
)


def _is_linked_worktree(root: Path) -> bool:
    return (root / ".git").is_file()


def _index_unavailable(worktree: Path) -> tuple[str, str]:
    """A linked worktree has no index: warn (visible row, no failure); else fail."""
    if _is_linked_worktree(worktree):
        return "warning", f"scan skipped, changed files not scanned: {_INDEX_RECOVERY}"
    return "fail", f"scan {_INDEX_RECOVERY}"


def _scan(worktree: Path, changed: list[str]) -> tuple[str, str]:
    result = subprocess.run(
        [
            "varde",
            "scan",
            "--json",
            json.dumps(
                {
                    "repoRoot": str(worktree),
                    "fullFindings": True,
                    "findingsLimit": 10000,
                }
            ),
        ],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        output = result.stdout + result.stderr
        if "index_missing" in output or "index_stale" in output:
            return _index_unavailable(worktree)
        return "fail", f"scan returned invalid output (exit {result.returncode})"
    if not isinstance(payload, dict):
        return "fail", f"scan returned invalid output (exit {result.returncode})"
    data = payload.get("data")
    error = payload.get("error")
    if not isinstance(error, dict) and isinstance(data, dict):
        error = data.get("error")
    code = error.get("code") if isinstance(error, dict) else payload.get("code")
    if code in ("index_missing", "index_stale"):
        return _index_unavailable(worktree)
    if "ok" in payload and payload.get("ok") is not True:
        return "fail", f"scan failed with error code {code or 'unknown'}"
    data = payload.get("data", payload)
    findings = data.get("findings", []) if isinstance(data, dict) else []
    changed_set = set(changed)
    matching = [
        finding
        for finding in findings
        if isinstance(finding, dict)
        and isinstance(finding.get("location"), dict)
        and finding["location"].get("file") in changed_set
        and finding.get("severity") == "error"
    ]
    if matching:
        return "fail", f"{len(matching)} blocking finding(s) in changed files"
    return "pass", f"no blocking findings in {len(changed)} changed file(s)"
