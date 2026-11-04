"""changedSince scoping: floor and cap findings limited to changed files."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_GATE = Path(__file__).parents[2] / "quality_gate" / "fixtures"
sys.path.insert(0, str(_GATE))

from gate_calibration import load_gate_test_calibration  # noqa: E402
from gate_snapshots import SNAPSHOTS  # noqa: E402
from varde_code.extract.provider import CodeExtractionProvider  # noqa: E402
from varde_code.index.build import build  # noqa: E402
from varde_code.model import Span  # noqa: E402
from varde_code.parse import parse_source  # noqa: E402
from varde_code.query import modes  # noqa: E402
from varde_code.rules.finding import Finding, Location  # noqa: E402
from varde_code.rules.model import Severity  # noqa: E402
from varde_code.scan import changed_since, core  # noqa: E402


@pytest.fixture(autouse=True)
def _grammars() -> None:
    try:
        parse_source("python", "value\n")
    except RuntimeError as error:
        pytest.skip(f"tree-sitter grammar cache unavailable: {error}")


def _finding(rule_id: str, file: str) -> Finding:
    return Finding(
        "id", rule_id, Severity.ERROR, "m",
        Location(file, Span(0, 0, 1, 0, 1, 0)), {}, None,
    )  # fmt: skip


def _git(root: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],  # noqa: S607
        cwd=root, check=True, capture_output=True,
    )  # fmt: skip


def test_parse_changed_paths_ignores_blank_lines():
    assert changed_since.parse_changed_paths("a.py\0\0b/c.py\0") == {"a.py", "b/c.py"}


def test_limit_keeps_scope_mean_and_drops_unchanged_floor_and_cap():
    findings = [
        _finding("quality-file-floor", "a.py"),
        _finding("quality-function-cap", "b.py"),
        _finding("quality-scope-mean", "."),
        _finding("other-rule", "b.py"),
    ]

    kept = changed_since.limit_to_changed(findings, frozenset({"a.py"}))

    assert [f.rule_id for f in kept] == [
        "quality-file-floor", "quality-scope-mean", "other-rule",
    ]  # fmt: skip


def test_empty_changed_scope_yields_no_floor_or_cap():
    findings = [
        _finding("quality-file-floor", "a.py"),
        _finding("quality-function-cap", "a.py"),
        _finding("quality-scope-mean", "."),
    ]
    kept = changed_since.limit_to_changed(findings, frozenset())
    assert [f.rule_id for f in kept] == ["quality-scope-mean"]


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(modes, "_INDEX_SERVICE", None)
    monkeypatch.setattr(
        core, "load_calibration", lambda path: load_gate_test_calibration()
    )
    root = tmp_path / "repo"
    for name, text in SNAPSHOTS["python"].files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    build(root, CodeExtractionProvider())
    _git(root, "init", "-q")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "base", "--no-verify")
    return root


def _scan(root: Path, **extra):
    return core.scan_repo({"repoRoot": str(root), "fullFindings": True, **extra})


def _by_rule(result, rule_id):
    return [f for f in result["findings"] if f["rule_id"] == rule_id]


def test_missing_ref_blocks_and_never_yields_an_empty_set(repo):
    result = _scan(repo, changedSince="no-such-ref")

    blocking = [d for d in result["diagnostics"] if d["blocking"]]
    assert any("changedSince" in d["message"] for d in blocking)
    assert result["gate"]["status"] in {"unknown", "fail"}
    assert _by_rule(result, "quality-file-floor")


def test_unchanged_tree_has_no_floor_or_cap_but_keeps_mean(repo):
    full = _scan(repo)
    result = _scan(repo, changedSince="HEAD")

    assert not _by_rule(result, "quality-file-floor")
    assert not _by_rule(result, "quality-function-cap")
    assert _by_rule(result, "quality-scope-mean") == _by_rule(
        full, "quality-scope-mean"
    )


def test_new_file_is_included_and_mean_is_unchanged(repo):
    snapshot = SNAPSHOTS["python"]
    full = _scan(repo)
    debt = snapshot.path("debt")
    assert debt in {f["location"]["file"] for f in _by_rule(full, "quality-file-floor")}
    (repo / "pkg_new").mkdir()
    new_path = "pkg_new/debt_copy.py"
    (repo / new_path).write_text((repo / debt).read_text(), encoding="utf-8")
    _git(repo, "add", new_path)
    build(repo, CodeExtractionProvider())

    result = _scan(repo, changedSince="HEAD")

    floors = {f["location"]["file"] for f in _by_rule(result, "quality-file-floor")}
    assert new_path in floors
    assert debt not in floors
    assert _by_rule(result, "quality-scope-mean")


def test_untracked_new_file_with_debt_is_reported(repo):
    debt = SNAPSHOTS["python"].path("debt")
    (repo / "pkg_new").mkdir()
    new_path = "pkg_new/debt_copy.py"
    (repo / new_path).write_text((repo / debt).read_text(), encoding="utf-8")
    build(repo, CodeExtractionProvider())

    result = _scan(repo, changedSince="HEAD")

    floors = {f["location"]["file"] for f in _by_rule(result, "quality-file-floor")}
    assert new_path in floors
    assert debt not in floors


def test_read_changed_paths_counts_untracked_but_not_ignored(repo):
    (repo / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    _git(repo, "add", ".gitignore")
    _git(repo, "commit", "-qm", "ignore", "--no-verify")
    (repo / "ignored.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "untracked.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "staged.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "staged.py")

    changed = changed_since.read_changed_paths(repo, "HEAD")

    assert changed == {"untracked.py", "staged.py"}


def test_read_changed_paths_counts_committed_new_file_since_base(repo):
    (repo / "later.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "later.py")
    _git(repo, "commit", "-qm", "later", "--no-verify")

    assert changed_since.read_changed_paths(repo, "HEAD~1") == {"later.py"}
    assert changed_since.read_changed_paths(repo, "no-such-ref") is None


def test_option_like_ref_is_rejected_and_writes_no_file(repo, tmp_path):
    target = tmp_path / "pwned"

    assert changed_since.read_changed_paths(repo, f"--output={target}") is None
    result = _scan(repo, changedSince=f"--output={target}")

    assert not target.exists()
    assert any(
        d["blocking"] and "changedSince" in d["message"] for d in result["diagnostics"]
    )


def test_read_changed_paths_keeps_non_ascii_filenames_unquoted(repo):
    (repo / "\u00e4.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "\u00e4.py")
    (repo / "\u00f6.py").write_text("x = 1\n", encoding="utf-8")

    assert changed_since.read_changed_paths(repo, "HEAD") == {"\u00e4.py", "\u00f6.py"}
