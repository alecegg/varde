"""Integrity controls: rulesRef, downgrades, suppression, scopes, pin."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_GATE = Path(__file__).parents[2] / "quality_gate" / "fixtures"
sys.path.insert(0, str(_GATE))

from gate_calibration import load_gate_test_calibration  # noqa: E402
from gate_snapshots import LANGUAGES, SNAPSHOTS  # noqa: E402
from varde_code.extract.provider import CodeExtractionProvider  # noqa: E402
from varde_code.index.build import build  # noqa: E402
from varde_code.model import Span  # noqa: E402
from varde_code.parse import parse_source  # noqa: E402
from varde_code.quality_pass.pathclass import PathPredicates, classify_path  # noqa: E402
from varde_code.query import modes  # noqa: E402
from varde_code.query.params import QueryError  # noqa: E402
from varde_code.rules.finding import Finding, Location  # noqa: E402
from varde_code.rules.model import Severity  # noqa: E402
from varde_code.rules.scan_output import filter_generated  # noqa: E402
from varde_code.rules.suppress import filter_findings  # noqa: E402
from varde_code.scan import core, integrity  # noqa: E402
from varde_code.scan.quality_scores import split_records_by_scope  # noqa: E402


@pytest.fixture(autouse=True)
def _grammars() -> None:
    for grammar in ("python", "typescript", "tsx", "csharp"):
        try:
            parse_source(grammar, "value\n")
        except RuntimeError as error:
            pytest.skip(f"tree-sitter grammar cache unavailable: {error}")


def _finding(rule_id: str, file: str, line: int = 1, **evidence) -> Finding:
    return Finding(
        "id", rule_id, Severity.ERROR, "m",
        Location(file, Span(0, 0, line, 0, line, 0)), evidence, None,
    )  # fmt: skip


def _git(root: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],  # noqa: S607
        cwd=root, check=True, capture_output=True,
    )  # fmt: skip


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


def _write_overrides(root: Path, text: str) -> None:
    (root / ".varde-code").mkdir(exist_ok=True)
    (root / ".varde-code" / "overrides.toml").write_text(text, encoding="utf-8")
    build(root, CodeExtractionProvider())


# G1: a generated marker alone never excludes a file from the gate.
@pytest.mark.parametrize("language", LANGUAGES)
def test_g1_marker_alone_never_excludes(language):
    snapshot = SNAPSHOTS[language]
    path = snapshot.path("debt")
    marker = PathPredicates(generated_marker=True)
    result = classify_path(path, marker, language=language, gate_mode=True)

    assert not result.excluded
    assert not result.generated
    assert filter_generated([_finding("quality-file-floor", path)])


# G11: inline suppression is ignored for quality-* and counted.
@pytest.mark.parametrize("language", LANGUAGES)
def test_g11_inline_suppression_is_ignored_and_counted(language, tmp_path):
    snapshot = SNAPSHOTS[language]
    path = snapshot.path("debt")
    source = snapshot.with_file_suppression(snapshot.files[path])
    (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / path).write_text(source, encoding="utf-8")
    quality = _finding("quality-file-floor", path, scope="repo")
    other = _finding("other-rule", path)

    kept, _ = integrity.filter_inline_suppressions(
        [quality, other], tmp_path, filter_findings
    )

    assert kept == [quality]
    assert integrity.count_quality_suppressions([quality, other], tmp_path) == [
        ("repo", "quality-file-floor", 1)
    ]


def test_scope_level_findings_are_never_counted_as_suppressed(tmp_path):
    scope_finding = _finding("quality-scope-mean", ".", scope="repo")
    assert integrity.count_quality_suppressions([scope_finding], tmp_path) == []


def test_scan_reports_suppressed_quality_findings_still_and_counts_them(repo):
    snapshot = SNAPSHOTS["python"]
    debt = repo / snapshot.path("debt")
    debt.write_text(snapshot.with_file_suppression(debt.read_text()), encoding="utf-8")
    build(repo, CodeExtractionProvider())

    result = core.scan_repo({"repoRoot": str(repo), "fullFindings": True})

    rules = [f["rule_id"] for f in result["findings"]]
    floors = [f for f in result["findings"] if f["rule_id"] == "quality-file-floor"]
    assert snapshot.path("debt") in {f["location"]["file"] for f in floors}
    assert "quality-suppressed" in rules


# G12: tests and tooling are their own scopes.
@pytest.mark.parametrize("language", LANGUAGES)
def test_g12_test_paths_are_their_own_scope(language):
    snapshot = SNAPSHOTS[language]
    assert integrity.scope_name(True, False) == "tests"
    assert integrity.scope_name(False, True) == "tooling"
    assert integrity.scope_name(True, True) == "tests"
    assert integrity.scope_name(False, False) == "repo"
    records = [{"path": p} for p in (snapshot.path("debt"), *snapshot.test_paths)]
    scopes = dict.fromkeys(snapshot.test_paths, "tests")

    groups = split_records_by_scope(records, scopes)

    assert [r["path"] for r in groups["repo"]] == [snapshot.path("debt")]
    assert [r["path"] for r in groups["tests"]] == list(snapshot.test_paths)


def test_scan_scores_tests_as_their_own_scope(repo):
    snapshot = SNAPSHOTS["python"]
    test_file = repo / "tests" / "test_extra.py"
    test_file.parent.mkdir(exist_ok=True)
    test_file.write_text(snapshot.filler_clean.replace("{n}", "1"), encoding="utf-8")
    build(repo, CodeExtractionProvider())
    captured = {}
    original = core.materialize_quality_scores

    def spy(*args, **kwargs):
        rows = original(*args, **kwargs)
        captured["scopes"] = {row.scope for row in rows}
        return rows

    core.materialize_quality_scores = spy
    try:
        core.scan_repo({"repoRoot": str(repo)})
    finally:
        core.materialize_quality_scores = original

    assert {"repo", "tests"} <= captured["scopes"]


# G3: configuration changes against the base ref.
def test_g3_config_changed_is_blocking_and_findings_use_base_config(repo):
    _write_overrides(repo, '[rules.quality-file-floor]\nseverity = "off"\n')

    result = core.scan_repo(
        {"repoRoot": str(repo), "rulesRef": "HEAD", "fullFindings": True}
    )

    changed = [d for d in result["diagnostics"] if d["rule_id"] == "config-changed"]
    assert changed
    assert changed[0]["blocking"] is True
    assert ".varde-code/overrides.toml" in changed[0]["message"]
    assert any(f["rule_id"] == "quality-file-floor" for f in result["findings"])
    assert result["gate"]["status"] == "fail"
    assert "analysis-incomplete" in result["outcome_reasons"]


def test_g3_config_changed_gives_unknown_without_a_blocking_finding(repo):
    base = "".join(
        f'[rules.{rid}]\nseverity = "off"\n'
        for rid in ("quality-file-floor", "quality-function-cap")
    )
    _write_overrides(repo, base)
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "cfg", "--no-verify")
    _write_overrides(repo, base + '[rules.quality-scope-mean]\nseverity = "off"\n')

    result = core.scan_repo({"repoRoot": str(repo), "rulesRef": "HEAD"})

    assert result["gate"]["status"] == "unknown"
    assert result["outcome_reasons"] == ["analysis-incomplete"]


def test_unchanged_config_adds_no_diagnostic(repo):
    result = core.scan_repo({"repoRoot": str(repo), "rulesRef": "HEAD"})
    assert not [d for d in result["diagnostics"] if d["rule_id"] == "config-changed"]


def test_missing_rules_ref_blocks(repo):
    result = core.scan_repo({"repoRoot": str(repo), "rulesRef": "no-such-ref"})
    blocking = [d for d in result["diagnostics"] if d["rule_id"] == "config-changed"]
    assert blocking and "no-such-ref" in blocking[0]["message"]
    assert result["gate"]["status"] in {"unknown", "fail"}


def test_config_diff_helpers():
    assert integrity.config_changed_diagnostic({"a": "1"}, {"a": "1"}) is None
    assert integrity.changed_config_files(
        {"a": "1", "b": "2"}, {"a": "1", "c": "3"}
    ) == ["b", "c"]


# Severity downgrade.
def test_downgrade_names_rule_old_new_and_reason(repo):
    _write_overrides(
        repo,
        '[rules.quality-file-floor]\nseverity = "warning"\nreason = "legacy"\n'
        '[rules.quality-function-cap]\nseverity = "off"\n',
    )

    result = core.scan_repo({"repoRoot": str(repo)})

    messages = {
        d["message"]
        for d in result["diagnostics"]
        if d["rule_id"] == "quality-severity-downgrade"
    }
    assert any(
        "quality-file-floor lowered from error to warning (reason: legacy)" in m
        for m in messages
    )
    assert any(
        "quality-function-cap lowered from error to off (missing reason)" in m
        for m in messages
    )
    assert all(
        not d["blocking"]
        for d in result["diagnostics"]
        if d["rule_id"] == "quality-severity-downgrade"
    )


def test_no_downgrade_diagnostic_at_default_severity(repo):
    result = core.scan_repo({"repoRoot": str(repo)})
    assert not [
        d for d in result["diagnostics"] if d["rule_id"] == "quality-severity-downgrade"
    ]


def test_skip_quality_reports_no_integrity_diagnostics(repo):
    _write_overrides(repo, '[rules.quality-file-floor]\nseverity = "warning"\n')
    result = core.scan_repo({"repoRoot": str(repo), "skipQuality": True})
    assert not [d for d in result["diagnostics"] if d["rule_id"].startswith("quality-")]


# Calibration pin.
def test_pin_mismatch_is_refused_without_flag_and_allowed_with_it():
    calibration = load_gate_test_calibration()
    pin = {"calibration_id": "other-id", "formula": calibration.formula}
    with pytest.raises(QueryError, match="calibration_id"):
        integrity.check_pin(pin, calibration, allow_change=False)
    integrity.check_pin(pin, calibration, allow_change=True)
    integrity.check_pin(None, calibration, allow_change=False)
    major = {"calibration_id": calibration.id, "formula": "vq9"}
    with pytest.raises(QueryError, match="formula"):
        integrity.check_pin(major, calibration, allow_change=False)
    assert integrity.formula_major("vq1") == integrity.formula_major("vq1.2")


def test_scan_refuses_pin_mismatch_and_previews_migration(repo):
    calibration = load_gate_test_calibration()
    (repo / ".varde-code").mkdir(exist_ok=True)
    (repo / integrity.PIN_FILE).write_text(
        'calibration_id = "old-cal"\nformula = "vq1"\n', encoding="utf-8"
    )
    build(repo, CodeExtractionProvider())
    with pytest.raises(QueryError) as error:
        core.scan_repo({"repoRoot": str(repo)})
    assert error.value.code == "calibration_pin_mismatch"

    preview = core.scan_repo({"repoRoot": str(repo), "migratePreview": True})[
        "migrate_preview"
    ]
    assert preview["differs"] == ["calibration_id"]
    assert preview["current"]["calibration_id"] == calibration.id

    allowed = core.scan_repo({"repoRoot": str(repo), "allowCalibrationChange": True})
    assert "gate" in allowed


def test_rules_ref_must_be_a_nonempty_string(tmp_path):
    with pytest.raises(QueryError, match="rulesRef"):
        core.scan_options({"repoRoot": str(tmp_path), "rulesRef": ""})


def test_read_ref_config_returns_none_when_the_tree_listing_fails(repo, monkeypatch):
    real = integrity.run_git

    def failing(args, cwd):
        return None if args[0] == "ls-tree" else real(args, cwd)

    monkeypatch.setattr(integrity, "run_git", failing)

    assert integrity.read_ref_config(repo, "HEAD") is None
