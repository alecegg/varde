from __future__ import annotations

import subprocess
from pathlib import Path

from varde_code.model import Span
from varde_code.rules.finding import FileState, Finding, Location
from varde_code.rules.model import Rule, RuleKind, Severity
from varde_code.rules.rewrite import RewriteStatus, RewriteTarget, plan_file_rewrites
from varde_code.scan.apply import (
    apply_rewrites,
    attach_rewrite_statuses,
    git_gate,
    parse_porcelain_dirty_paths,
    splice,
    write_atomic,
)


def finding(
    path: Path, text: str, start: int, end: int, *, state=None, ident="f"
) -> Finding:
    return Finding(
        id=ident,
        rule_id="replace-trace",
        severity=Severity.WARNING,
        message="replace trace",
        location=Location(str(path), Span(start, end, 1, start, 1, end)),
        evidence={
            "CALL": {"text": text, "span": {"start_byte": start, "end_byte": end}}
        },
        remediation=None,
        matched_file_state=state,
    )


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)  # noqa: S603, S607 - Test uses controlled Git arguments against its temporary repository.


def commit_repo(repo: Path) -> None:
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.com")
    git(repo, "config", "user.name", "test")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "initial")


def test_apply_rewrites_clean_file_byte_exact_and_preserves_mode(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    path = repo / "main.ts"
    original = 'const café = console.trace("x");\r\n'
    path.write_bytes(original.encode())
    path.chmod(0o755)
    commit_repo(repo)
    start = len("const café = ".encode())
    end = start + len(b'console.trace("x")')
    item = finding(path, 'console.trace("x")', start, end)
    item.evidence = {
        "ARG": {"text": "x", "span": {"start_byte": start + 18, "end_byte": start + 19}}
    }
    rule = Rule(
        id="replace-trace",
        kind=RuleKind.PATTERN,
        severity=Severity.WARNING,
        message="replace",
        rewrite='console.info("$ARG")',
    )

    statuses = apply_rewrites([rule], [item], repo)

    assert statuses == {"f": RewriteStatus.APPLIED}
    assert path.read_bytes() == 'const café = console.info("x");\r\n'.encode()
    assert path.stat().st_mode & 0o777 == 0o755
    assert not list(repo.glob("*.varde-apply-tmp-*"))


def test_apply_skips_dirty_file_unless_forced(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    path = repo / "main.ts"
    path.write_text("trace()\n")
    commit_repo(repo)
    path.write_text("trace()\n// edited\n")
    start, end = 0, len("trace()")
    item = finding(path, "trace()", start, end)
    rule = Rule(
        id="replace-trace",
        kind=RuleKind.PATTERN,
        severity=Severity.WARNING,
        message="replace",
        rewrite="info()",
    )

    skipped = apply_rewrites([rule], [item], repo)
    assert skipped["f"] == RewriteStatus.SKIPPED_DIRTY
    assert path.read_text() == "trace()\n// edited\n"
    applied = apply_rewrites([rule], [item], repo, force=True)
    assert applied["f"] == RewriteStatus.APPLIED
    assert path.read_text() == "info()\n// edited\n"


def test_stale_file_state_conflicts_and_overlaps_use_shared_planner(
    tmp_path: Path,
) -> None:
    path = tmp_path / "file.ts"
    path.write_text("abcdef")
    stale = FileState(0, 99)
    target = finding(path, "abc", 0, 3, state=stale)
    rule = Rule(
        id="replace-trace",
        kind=RuleKind.PATTERN,
        severity=Severity.WARNING,
        message="replace",
        rewrite="x",
    )
    assert (
        apply_rewrites([rule], [target], tmp_path, force=True)["f"]
        == RewriteStatus.SKIPPED_CONFLICT
    )
    plans = plan_file_rewrites([RewriteTarget(0, 4, "x"), RewriteTarget(2, 5, "y")])
    assert [plan.value for plan in plans] == ["apply", "skipped-overlap"]


def test_git_gate_and_porcelain_parser(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    file = outside / "a.ts"
    file.write_text("x\n")
    assert git_gate(outside, [file]).kind == "not-git"
    assert parse_porcelain_dirty_paths(b" M a.ts\0?? new.ts\0!! ignored.ts\0") == [
        "a.ts",
        "new.ts",
        "ignored.ts",
    ]
    assert parse_porcelain_dirty_paths(b"bad\0") is None

    repo = tmp_path / "repo"
    repo.mkdir()
    tracked = repo / "a.ts"
    tracked.write_text("x\n")
    commit_repo(repo)
    tracked.write_text("y\n")
    gate = git_gate(repo, [tracked])
    assert gate.dirty(tracked.resolve())


def test_splice_and_atomic_write_keep_bytes(tmp_path: Path) -> None:
    assert splice("aéz", [RewriteTarget(1, 3, "E")]) == "aEz"
    assert splice("aéz", [RewriteTarget(2, 3, "E")]) is None
    path = tmp_path / "out"
    write_atomic(path, "new\r\n")
    assert path.read_bytes() == b"new\r\n"


def test_attach_rewrite_statuses_summary_is_stable() -> None:
    payload = {"findings": [{"id": "a"}, {"id": "b"}]}
    attach_rewrite_statuses(
        payload, {"a": RewriteStatus.APPLIED, "b": RewriteStatus.SKIPPED_DIRTY}, 2
    )
    assert payload == {
        "findings": [
            {"id": "a", "rewrite_status": "applied"},
            {"id": "b", "rewrite_status": "skipped-dirty"},
        ],
        "rewrite_summary": {"applied": 1, "skipped-dirty": 1},
    }
