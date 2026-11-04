from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from varde_learn.knowledge.frontmatter import parse
from varde_workflow.commands.conclude import run as run_conclude
from varde_workflow.commands.distill import distill
from varde_workflow.commands.owner import (
    remove_owner_line,
    resolve_plan,
    set_owner_line,
    validate_owner,
)
from varde_workflow.commands.plan_gate import run as run_plan_gate
from varde_workflow.commands.validate import run as run_validate
from varde_workflow.commands.validate import validate
from varde_workflow.conclusion import ConcludeError, conclude, unchecked_acceptance
from varde_workflow.review_structure import open_critical_or_high, review_structure


def test_owner_edits_frontmatter_preserving_body_and_multiline_values() -> None:
    original = b"---\ntype: plan\nowner: |\n  old\n  value\ntitle: Keep\n---\n\nbody\n"
    updated = set_owner_line(original, "claude:session")
    assert b"owner: claude:session\ntitle: Keep\n" in updated
    assert updated.endswith(b"\n\nbody\n")
    assert remove_owner_line(updated) == original.replace(
        b"owner: |\n  old\n  value\n", b""
    )


def test_owner_edits_quote_values_that_yaml_would_parse_as_other_types() -> None:
    updated = set_owner_line(b"---\ntype: plan\n---\nbody\n", "[harness:id]")
    assert parse(updated)[0]["owner"] == "[harness:id]"


@pytest.mark.parametrize(
    "owner", ["", ":id", "harness:", "harness:bad value", "harness:bad\nid"]
)
def test_owner_validation_rejects_invalid_values(owner: str) -> None:
    with pytest.raises(ValueError):
        validate_owner(owner)


def test_resolve_plan_is_confined_to_plans_tree(tmp_path: Path) -> None:
    plans = tmp_path / "working" / "plans"
    target = plans / "example" / "plan.md"
    target.parent.mkdir(parents=True)
    target.write_text("---\ntype: plan\n---\n", encoding="utf-8")
    assert resolve_plan("example/plan.md", tmp_path, plans) == target.resolve()
    outside = tmp_path / "outside" / "plan.md"
    outside.parent.mkdir()
    outside.write_text("---\ntype: plan\n---\n", encoding="utf-8")
    with pytest.raises(ValueError):
        resolve_plan(outside, tmp_path, plans)


def test_unchecked_acceptance_reports_section_state() -> None:
    assert unchecked_acceptance("## Acceptance criteria\n- [ ] one\n") is True
    assert unchecked_acceptance("## Acceptance criteria\n- done\n") is False
    assert unchecked_acceptance("## Other\n- [ ] one\n") is None


def test_conclude_cli_preserves_review_error_code_and_fix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "review.md").write_text(
        "---\nverdict: changes-requested\n---\n", encoding="utf-8"
    )

    status = run_conclude(
        SimpleNamespace(plan=plan, merged=None, repo=tmp_path, json=True)
    )

    result = json.loads(capsys.readouterr().err)
    error = result["data"]["error"]
    assert status == 1
    assert error["code"] == "review_invalid"
    assert error["fix"] == {
        "reason": "Correct the review report or the merged commit named in the "
        "error, then rerun plan conclude."
    }


def test_conclude_requires_reviewed_commit_and_completes_plan(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "--allow-empty",
            "-qm",
            "review",
        ],
        check=True,
    )
    reviewed = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "--allow-empty",
            "-qm",
            "merge",
        ],
        check=True,
    )
    head = reviewed
    working = tmp_path / "working"
    plan = working / "plans" / "plan"
    plan.mkdir(parents=True)
    (plan / "review.md").write_text(
        f"---\nverdict: approved\nhead: {head}\n---\n", encoding="utf-8"
    )
    (plan / "plan.md").write_text(
        "---\nid: plan-id\ntype: plan\nstatus: active\n---\n\n"
        "## Acceptance criteria\n- done\n",
        encoding="utf-8",
    )
    result = conclude(plan, reviewed, repo)
    assert (result.id, result.head) == ("plan-id", head)
    assert "status: completed" in (plan / "plan.md").read_text(encoding="utf-8")
    from varde_workflow.relay_state import load, planning_state

    assert "plan-id" in load(working)["concluded_addresses"]
    with pytest.raises(ConcludeError, match="does not match reviewed head"):
        conclude(plan, "HEAD", repo)
    import shutil

    shutil.rmtree(plan)
    assert "plan-id" in planning_state(working)["concluded_addresses"]


def test_conclude_accepts_single_task_directory_without_writing_status(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "--allow-empty",
            "-qm",
            "review",
        ],
        check=True,
    )
    head = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    change = tmp_path / "change"
    change.mkdir()
    (change / "review.md").write_text(
        f"---\nverdict: approved\nhead: {head}\n---\n", encoding="utf-8"
    )
    task = change / "task.md"
    task.write_text(
        "---\nid: task-id\ntype: task\nstatus: todo\n---\n", encoding="utf-8"
    )
    assert conclude(change, None, repo).id == "task-id"
    assert "status: todo" in task.read_text(encoding="utf-8")


def test_conclude_rejects_approved_review_with_open_critical_finding(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "--allow-empty",
            "-qm",
            "review",
        ],
        check=True,
    )
    head = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "review.md").write_text(
        f"---\ntype: review\nverdict: approved\nhead: {head}\n---\n\n"
        "## [CODE-001] Exposed secret\n\n**Severity:** critical\n"
        "**Status:** open\n\n### Solutions\n\n1. Remove it.\n",
        encoding="utf-8",
    )
    with pytest.raises(ConcludeError, match="open critical/high findings: CODE-001"):
        conclude(plan, head, repo)


def test_validate_rejects_malformed_review_finding(tmp_path: Path) -> None:
    review = tmp_path / "review.md"
    review.write_text(
        "---\ntype: review\nverdict: changes-requested\nhead: abc\n---\n\n"
        "## [CODE-001] Missing fields\n\n**Severity:** urgent\n"
        "**Status:** open\n",
        encoding="utf-8",
    )

    envelope, errors, _ = validate(review)

    assert envelope is None
    assert "CODE-001 has an invalid severity" in [item.message for item in errors]
    assert "CODE-001 is missing ### Solutions" in [item.message for item in errors]


def test_validate_rejects_duplicate_finding_ids(tmp_path: Path) -> None:
    review = tmp_path / "review.md"
    finding = (
        "## [CODE-001] Issue\n\n**Severity:** low\n**Status:** open\n\n"
        "### Solutions\n\n1. Fix.\n"
    )
    review.write_text(
        "---\ntype: review\nverdict: changes-requested\nhead: abc\n---\n\n"
        + finding
        + "\n"
        + finding,
        encoding="utf-8",
    )

    _, errors, _ = validate(review)

    assert "duplicate finding id CODE-001" in [item.message for item in errors]


def test_review_structure_accepts_standalone_deferred_finding(tmp_path: Path) -> None:
    review = tmp_path / "working" / "reviews" / "2026-10-17-example" / "review.md"
    review.parent.mkdir(parents=True)
    review.write_text(
        "---\ntype: review\nverdict: changes-requested\nhead: abc\n---\n\n"
        "## [DESIGN-001] Defer the cleanup\n\n**Severity:** medium\n"
        "**Status:** deferred\n\n### Solutions\n\n1. Revisit later.\n",
        encoding="utf-8",
    )

    assert review_structure(review) == []


def test_validate_and_gate_accept_conformance_sections(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    plan = repo / "plans" / "sample"
    tasks = plan / "tasks"
    tasks.mkdir(parents=True)
    source = repo / "src" / "owned.py"
    source.parent.mkdir()
    source.write_text("base\n", encoding="utf-8")
    (plan / "plan.md").write_text(
        "---\ntype: plan\nstatus: active\n---\n\n## Acceptance criteria\n- done\n",
        encoding="utf-8",
    )
    task = tasks / "sample.md"
    task.write_text(
        "---\ntype: task\nstatus: in_progress\nowns: [src/owned.py]\n---\n\n"
        "## Acceptance criteria\n- done\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    _git_commit_file(repo, plan / "plan.md", "base")
    base = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()

    source.write_text("wave change\n", encoding="utf-8")
    _git_commit_file(repo, source, "wave change")
    wave_commit = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()
    review = plan / "review.md"
    review.write_text(
        f"---\ntype: review\nverdict: changes-requested\nreviewer: test\n"
        f"base: {base}\nhead: {wave_commit}\n---\n\n"
        "## Conformance W1\n\n"
        "## [SPEC-001] First criterion\n\n"
        "**Severity:** high\n**Status:** fixed\n\n### Solutions\n\n1. Fix it.\n",
        encoding="utf-8",
    )
    _git_commit_file(repo, review, "record W1 conformance")
    with review.open("a", encoding="utf-8") as stream:
        stream.write(
            "\n## Conformance W2\n\n"
            "## [SPEC-002] Second criterion\n\n"
            "**Severity:** high\n**Status:** open\n\n### Solutions\n\n1. Fix it.\n"
        )
    source.write_text("fixed wave issue\n", encoding="utf-8")
    _git_commit_file(repo, source, "fix(SPEC-001): address conformance issue")

    bindir = tmp_path / "bin"
    bindir.mkdir()
    scan_stub = bindir / "varde"
    scan_stub.write_text(
        '#!/bin/sh\necho \'{"data":{"findings":[]}}\'\nexit 0\n',
        encoding="utf-8",
    )
    scan_stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")

    status = run_validate(SimpleNamespace(artifact=review, json=False))
    validation_output = capsys.readouterr().out

    assert status == 0
    assert f"valid: {review}" in validation_output

    gate_status = run_plan_gate(
        SimpleNamespace(task=task, commit=wave_commit, repo_root=repo)
    )
    gate_output = capsys.readouterr().out

    assert gate_status == 0
    assert "review structure, pass," in gate_output


def test_open_critical_or_high_reads_level_two_conformance_findings(
    tmp_path: Path,
) -> None:
    review = tmp_path / "review.md"
    review.write_text(
        "---\ntype: review\nverdict: changes-requested\nhead: abc\n---\n\n"
        "## Conformance W1\n\n"
        "## [SPEC-001] Missing behavior\n\n"
        "**Severity:** high\n**Status:** open\n\n"
        "### Solutions\n\n1. Implement the behavior.\n",
        encoding="utf-8",
    )

    assert open_critical_or_high(review) == ["SPEC-001"]


def test_open_critical_or_high_handles_empty_severity(tmp_path: Path) -> None:
    review = tmp_path / "review.md"
    review.write_text(
        "---\nverdict: approved\nhead: abc\n---\n\n"
        "## [CODE-001] Missing severity\n\n**Status:** open\n",
        encoding="utf-8",
    )

    with pytest.raises(ConcludeError, match="open critical/high findings: CODE-001"):
        conclude(tmp_path, repo=tmp_path)


def test_validate_rejects_non_list_plan_gate(tmp_path: Path) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text(
        "---\ntype: plan\nstatus: active\ngate: false\n---\n\n"
        "## Acceptance criteria\n- done\n",
        encoding="utf-8",
    )

    _, errors, _ = validate(plan)

    assert ("gate", "field must be a list of strings") in [
        (item.field, item.message) for item in errors
    ]


@pytest.mark.parametrize(
    ("severity", "status", "should_close"),
    [
        ("high", "fixed (verified at abc)", True),
        ("high", "asked", False),
        ("Critical", "open", False),
        ("high", "", False),
    ],
)
def test_conclude_fails_closed_for_critical_and_high_status(
    tmp_path: Path, severity: str, status: str, should_close: bool
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    head = _commit_empty(repo, "review")
    plan = tmp_path / "plan"
    plan.mkdir()
    (plan / "task.md").write_text(
        "---\nid: task\ntype: task\nstatus: todo\n---\n", encoding="utf-8"
    )
    review_status = f"**Status:** {status}\n" if status else ""
    (plan / "review.md").write_text(
        f"---\nverdict: approved\nhead: {head}\n---\n\n"
        f"## [CODE-001] Issue\n\n**Severity:** {severity}\n"
        f"{review_status}\n### Solutions\n\n1. Fix.\n",
        encoding="utf-8",
    )

    if should_close:
        assert conclude(plan, head, repo).head == head
    else:
        with pytest.raises(
            ConcludeError, match="open critical/high findings: CODE-001"
        ):
            conclude(plan, head, repo)


def test_validate_rejects_non_fix_recheck_commit(tmp_path: Path) -> None:
    code = tmp_path / "code"
    notes = tmp_path / "notes"
    code.mkdir()
    notes.mkdir()
    subprocess.run(["git", "-C", str(code), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(notes), "init", "-q"], check=True)
    base = _commit_empty(code, "base")
    review = notes / "review.md"
    finding = (
        "## [CODE-001] Issue\n\n**Severity:** low\n**Status:** open\n\n"
        "### Solutions\n\n1. Fix.\n"
    )
    header = (
        f"---\ntype: review\nverdict: changes-requested\nbase: {base}\n"
        f"head: {base}\n---\n\n"
    )
    review.write_text(header + finding, encoding="utf-8")
    _git_commit_file(notes, review, "initial review")
    head = _commit_empty(code, "ordinary update")
    review.write_text(
        header.replace(f"head: {base}", f"head: {head}")
        + "## Re-check\nReviewed again.\n\n"
        + finding,
        encoding="utf-8",
    )

    errors = review_structure(review, repo=code)

    assert (
        "header-only re-check includes commits other than fix(<ID>) commits" in errors
    )


def test_fixed_high_requires_matching_fix_commit_in_code_repo(tmp_path: Path) -> None:
    code = tmp_path / "code"
    notes = tmp_path / "notes"
    code.mkdir()
    notes.mkdir()
    subprocess.run(["git", "-C", str(code), "init", "-q"], check=True)
    base = _commit_empty(code, "base")
    head = _commit_empty(code, "fix(CODE-001): address issue")
    review = notes / "review.md"
    review.write_text(
        f"---\ntype: review\nverdict: approved\nbase: {base}\nhead: {head}\n"
        "---\n\n## [CODE-001] Issue\n\n**Severity:** high\n"
        "**Status:** fixed\n\n### Solutions\n\n1. Fix.\n",
        encoding="utf-8",
    )

    assert review_structure(review, repo=code) == []


def test_fixed_highs_validate_with_one_fix_commit_per_finding(tmp_path: Path) -> None:
    code = tmp_path / "code"
    notes = tmp_path / "notes"
    code.mkdir()
    notes.mkdir()
    subprocess.run(["git", "-C", str(code), "init", "-q"], check=True)
    base = _commit_empty(code, "base")
    _commit_empty(code, "fix(CODE-001): first")
    head = _commit_empty(code, "fix(CODE-002): second")
    finding = (
        "## [CODE-00{n}] Issue\n\n**Severity:** high\n**Status:** fixed\n\n"
        "### Solutions\n\n1. Fix.\n"
    )
    review = notes / "review.md"
    review.write_text(
        f"---\ntype: review\nverdict: approved\nbase: {base}\nhead: {head}\n---\n\n"
        + finding.format(n=1)
        + "\n"
        + finding.format(n=2),
        encoding="utf-8",
    )

    assert review_structure(review, repo=code) == []


def test_fixed_high_without_matching_commit_is_invalid(tmp_path: Path) -> None:
    code = tmp_path / "code"
    notes = tmp_path / "notes"
    code.mkdir()
    notes.mkdir()
    subprocess.run(["git", "-C", str(code), "init", "-q"], check=True)
    base = _commit_empty(code, "base")
    head = _commit_empty(code, "unrelated update")
    review = notes / "review.md"
    review.write_text(
        f"---\ntype: review\nverdict: approved\nbase: {base}\nhead: {head}\n"
        "---\n\n## [CODE-001] Issue\n\n**Severity:** high\n"
        "**Status:** fixed\n\n### Solutions\n\n1. Fix.\n",
        encoding="utf-8",
    )

    assert any(
        "fixed high without a matching" in item
        for item in review_structure(review, repo=code)
    )


def test_fixed_high_without_available_code_shas_warns_and_skips(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    review = tmp_path / "review.md"
    review.write_text(
        "---\ntype: review\nverdict: approved\nbase: unavailable-base\n"
        "head: unavailable-head\n---\n\n## [CODE-001] Issue\n\n"
        "**Severity:** high\n**Status:** fixed\n\n### Solutions\n\n1. Fix.\n",
        encoding="utf-8",
    )

    assert review_structure(review, repo=tmp_path) == []
    assert "cannot check fixed high finding CODE-001" in caplog.text


def _commit_empty(repo: Path, message: str) -> str:
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "--allow-empty",
            "-qm",
            message,
        ],
        check=True,
    )
    return subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()


def _git_commit_file(repo: Path, path: Path, message: str) -> None:
    subprocess.run(["git", "-C", str(repo), "add", str(path)], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            message,
        ],
        check=True,
    )


def test_validate_rejects_finding_text_changed_since_previous_head(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    review = repo / "review.md"
    header = (
        "---\ntype: review\nverdict: changes-requested\nreviewer: test\n"
        "base: abc\nhead: abc\n---\n\n"
    )
    finding = (
        "## [CODE-001] Original title\n\n**Severity:** low\n"
        "**Status:** open\n\n### Solutions\n\n1. Change this.\n"
    )
    review.write_text(header + finding, encoding="utf-8")
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "add",
            "review.md",
        ],
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "-qm",
            "initial review",
        ],
        check=True,
    )
    review.write_text(
        header + finding.replace("Original title", "Changed title"), encoding="utf-8"
    )

    _, errors, _ = validate(review)

    assert "CODE-001 finding text changed since the prior head" in [
        item.message for item in errors
    ]


def test_distill_returns_markdown_and_data_without_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    working = tmp_path / "working"
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    plan = tmp_path / "plan"
    (plan / "tasks").mkdir(parents=True)
    (plan / "plan.md").write_text(
        "---\ntype: plan\nstatus: completed\nreviewed_commit: abc\n---\n"
        "# Example\n\n## Problem\nNeed it.\n\n## Solution\nDo it.\n"
        "\n## Decisions so far\nKeep this.\n",
        encoding="utf-8",
    )
    (plan / "tasks" / "one.md").write_text(
        "---\nstatus: done\n---\n# Task\n", encoding="utf-8"
    )
    result = distill(plan, tmp_path)
    assert result.data["title"] == "Example"
    assert "- Task (done)" in result.markdown
    assert result.data["bundle_path"] == str(working / "distilled")
    assert not (working / "distilled").exists()
