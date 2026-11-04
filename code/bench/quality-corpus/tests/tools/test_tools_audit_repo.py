"""Audit-repo tests: git-scoped scanning, label-name rule and the git-less fallback."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from place_item import audit_repo, listed_files

TOOLS = Path(__file__).resolve().parents[2] / "tools"
TEST_TASK = "sample-test"


@pytest.fixture(autouse=True)
def empty_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the content scan at a temp store so no test reads the real one."""
    store = tmp_path / "restricted"
    store.mkdir()
    monkeypatch.setenv("VARDE_GOLDEN_RESTRICTED", str(store))


def split_id() -> str:
    return hashlib.sha256(TEST_TASK.encode()).hexdigest()[:24]


def make_lock(tmp_path: Path, split: str = "test-restricted") -> Path:
    lock = tmp_path / "splits.lock"
    lock.write_text(json.dumps({"assignments": {TEST_TASK: split}, "sha256": "unused"}))
    return lock


def init_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    return root


def run_audit_cli(repo: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [
            sys.executable,
            str(TOOLS / "place_item.py"),
            "--audit-repo",
            "--repo-root",
            str(repo),
        ],
        check=False,
        capture_output=True,
    )


def test_audit_ignores_gitignored_venv_label_names(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / ".gitignore").write_text(".venv/\n")
    (repo / "tracked.py").write_text("pass\n")
    stub = repo / ".venv" / "lib" / "site-packages" / "textlabels.pyi"
    stub.parent.mkdir(parents=True)
    stub.write_text("# typeshed stub\n")
    assert audit_repo(repo, make_lock(tmp_path)) == []
    audit = run_audit_cli(repo)
    assert audit.returncode == 0
    assert f"audited root: {repo}" in audit.stdout.decode()


def test_audit_flags_planted_untracked_test_item(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    planted = repo / "leaked" / split_id() / "sensible.py"
    planted.parent.mkdir(parents=True)
    planted.write_text("pass\n")
    marker = repo / "leaked" / ".varde-split.json"
    marker.write_text(json.dumps({"task_id": TEST_TASK, "split": "test-restricted"}))
    findings = audit_repo(repo, make_lock(tmp_path))
    assert str(planted) in findings
    assert str(marker) in findings
    assert run_audit_cli(repo).returncode == 1


def test_audit_flags_tracked_labels_file(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    label = repo / "code" / "bench" / "quality-corpus" / "labels" / "labels.jsonl"
    label.parent.mkdir(parents=True)
    label.write_text('{"task_id":"sample-test"}\n')
    subprocess.run(
        ["git", "-C", str(repo), "add", str(label.relative_to(repo))],
        check=True,
        capture_output=True,
    )
    assert str(label) in audit_repo(repo, make_lock(tmp_path))


def test_audit_ignores_labels_fixture_outside_quality_corpus(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    fixture = (
        repo
        / "code"
        / "tests"
        / "quality_pass"
        / "fixtures"
        / "accuracy"
        / "labels"
        / "generated.json"
    )
    fixture.parent.mkdir(parents=True)
    fixture.write_text("{}\n")
    assert audit_repo(repo, make_lock(tmp_path)) == []


def test_audit_flags_labels_directory_inside_quality_corpus(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    label = (
        repo
        / "code"
        / "bench"
        / "quality-corpus"
        / "fixtures"
        / "labels"
        / "generated.json"
    )
    label.parent.mkdir(parents=True)
    label.write_text("{}\n")
    assert str(label) in audit_repo(repo, make_lock(tmp_path))


def test_audit_flags_specific_golden_label_names_anywhere(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    labels = [
        repo / name for name in ("panel-v1.jsonl", "human-v2.jsonl", "batch-v3.jsonl")
    ]
    for label in labels:
        label.write_text("[]\n")
    findings = audit_repo(repo, make_lock(tmp_path))
    assert all(str(label) in findings for label in labels)


def test_audit_flags_bare_label_names_only_in_items_or_labels_trees(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / "src").mkdir()
    (repo / "src" / "label_utils.py").write_text("pass\n")
    item_label = (
        repo
        / "code"
        / "bench"
        / "quality-corpus"
        / "items"
        / "dev"
        / "x"
        / "label_utils.py"
    )
    item_label.parent.mkdir(parents=True)
    item_label.write_text("pass\n")
    panel = repo / "code" / "bench" / "quality-corpus" / "panel.labels.json"
    panel.write_text("[]\n")
    findings = audit_repo(repo, make_lock(tmp_path))
    assert str(repo / "src" / "label_utils.py") not in findings
    assert str(item_label) in findings
    assert str(panel) in findings


def test_audit_flags_special_character_label_paths(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "repo")
    non_ascii = repo / "code" / "bench" / "quality-corpus" / "labels" / "\u00f8.json"
    non_ascii.parent.mkdir(parents=True)
    non_ascii.write_text("{}\n")
    special = repo / "code" / "bench" / "quality-corpus" / "items" / "\u00f8.labels.x"
    special.parent.mkdir()
    special.write_text("x\n")
    newline = (
        repo / "code" / "bench" / "quality-corpus" / "items" / "weird\nname.labels"
    )
    newline.write_text("x\n")
    findings = audit_repo(repo, make_lock(tmp_path))
    assert str(non_ascii) in findings
    assert str(special) in findings
    assert str(newline) in findings


def test_audit_flags_renamed_restricted_copy_by_content(tmp_path: Path) -> None:
    store = tmp_path / "store"
    secret = store / "test-restricted" / "abc" / "sensible.py"
    secret.parent.mkdir(parents=True)
    secret.write_text("def answer():\n    return 42\n")
    tiny = store / "test-restricted" / "abc" / "pair.json"
    tiny.write_text("{}\n")
    repo = init_repo(tmp_path / "repo")
    renamed = repo / "items" / "dev" / "panel-v1.jsonl"
    renamed.parent.mkdir(parents=True)
    renamed.write_text("def answer():\n    return 42\n")
    decoy = repo / "items" / "dev" / "decoy.jsonl"
    decoy.write_text("def answer():\n    return 43\n")
    tiny_copy = repo / "items" / "dev" / "tiny.json"
    tiny_copy.write_text("{}\n")
    findings = audit_repo(repo, make_lock(tmp_path), store=store)
    assert str(renamed) in findings
    assert str(decoy) not in findings
    assert str(tiny_copy) not in findings


def test_audit_skips_content_scan_without_restricted_store(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo = init_repo(tmp_path / "repo")
    (repo / "tracked.py").write_text("pass\n")
    absent = tmp_path / "absent-store"
    assert audit_repo(repo, make_lock(tmp_path), store=absent) == []
    captured = capsys.readouterr()
    assert "content scan skipped" in captured.err
    assert str(absent) in captured.err


def test_audit_walks_when_git_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "no-git"))
    copy = tmp_path / "archive"
    (copy / "notes").mkdir(parents=True)
    label = copy / "code" / "bench" / "quality-corpus" / "notes" / "panel.labels.json"
    label.parent.mkdir(parents=True)
    label.write_text("[]\n")
    stub = copy / ".venv" / "lib" / "mklabels.py"
    stub.parent.mkdir(parents=True)
    stub.write_text("# stub\n")
    leaked = copy / "leaked" / split_id() / ".varde-split.json"
    leaked.parent.mkdir(parents=True)
    leaked.write_text(json.dumps({"task_id": TEST_TASK, "split": "test-restricted"}))
    assert listed_files(copy) is None
    findings = audit_repo(copy, make_lock(tmp_path))
    assert str(label) in findings
    assert str(leaked) in findings
    assert all(".venv" not in finding for finding in findings)
    assert run_audit_cli(copy).returncode == 1
