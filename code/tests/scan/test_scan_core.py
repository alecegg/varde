# ruff: noqa: UP034 - Explicit grouping preserves split fixture strings in calls.
from __future__ import annotations

import sqlite3

import pytest
from varde_code.query.modes import set_index_service
from varde_code.query.params import QueryError
from varde_code.rules.model import Rule, RuleKind, Severity
from varde_code.scan.core import (
    scan_options,
    scan_repo,
    selected_gate_rules,
    severity_threshold,
)


def test_severity_threshold_defaults_and_validates():
    assert severity_threshold({}) is Severity.ERROR
    assert severity_threshold({"severityThreshold": "warning"}) is Severity.WARNING
    with pytest.raises(QueryError, match="unknown severityThreshold"):
        severity_threshold({"severityThreshold": "critical"})


def test_selected_gate_rules_validates_and_sorts_ids():
    rules = [
        Rule("b", RuleKind.PATTERN, Severity.WARNING, "b"),
        Rule("a", RuleKind.PATTERN, Severity.ERROR, "a"),
    ]
    assert selected_gate_rules({"gateRules": ["b", "a"]}, rules) == ["a", "b"]
    with pytest.raises(QueryError, match="mutually exclusive"):
        selected_gate_rules({"gateRules": ["a"], "severityThreshold": "error"}, rules)
    with pytest.raises(QueryError, match="duplicate gate rule"):
        selected_gate_rules({"gateRules": ["a", "a"]}, rules)


def test_scan_options_checks_root_and_findings_options(tmp_path):
    assert scan_options({"repoRoot": str(tmp_path), "findingsOffset": 2})[3] == {
        "full": False,
        "limit": 100,
        "offset": 2,
    }
    with pytest.raises(QueryError, match="findingsLimit must be greater than zero"):
        scan_options({"repoRoot": str(tmp_path), "findingsLimit": 0})


def test_scan_without_registered_index_service_has_build_hint(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "varde_code.scan.core.load_rules_with_details",
        lambda root: ([], [], type("Details", (), {"origins": {}})()),
    )
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    set_index_service(None)
    with pytest.raises(QueryError, match="index missing at") as error:
        scan_repo({"repoRoot": str(tmp_path)})
    expected = tmp_path / "config" / "code" / "repos"
    assert str(expected) in error.value.message
    assert "varde map build --repo-root <repo-root>" in error.value.message
    assert "find_pattern needs no index" in error.value.message


def test_scan_uses_index_service_and_returns_scan_payload(tmp_path, monkeypatch):
    db_path = tmp_path / "index.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        (
            "CREATE TABLE diagnostics (id INTEGER, file_id INTEGER, path TEXT, "
            "message TEXT, severity TEXT)"
        )
    )
    conn.execute(
        (
            "CREATE TABLE files (id INTEGER, path TEXT, is_test_path INTEGER, "
            "is_tooling_path INTEGER)"
        )
    )
    conn.execute(
        (
            "CREATE TABLE entities (file_id INTEGER, kind INTEGER, name TEXT, "
            "is_async INTEGER, start_byte INTEGER, end_byte INTEGER)"
        )
    )
    conn.executemany(
        "INSERT INTO diagnostics VALUES (?, ?, ?, ?, ?)",
        [
            (1, None, "vendor.bin", "unsupported file type — skipped", "info"),
            (
                2,
                None,
                "generated.min.js",
                "minified/generated source — skipped",
                "info",
            ),
            (
                3,
                None,
                "src/broken.py",
                "syntax error — partial extract kept",
                "warning",
            ),
        ],
    )
    conn.commit()
    conn.close()

    class Index:
        def __init__(self):
            self.freshened = []

        def ensure_fresh(self, root):
            self.freshened.append(root)

        def repo_db_path(self, root):
            return db_path

    service = Index()
    set_index_service(service)
    monkeypatch.setattr(
        "varde_code.scan.core.load_rules_with_details",
        lambda root: ([], [], type("Details", (), {"origins": {}})()),
    )
    result = scan_repo({"repoRoot": str(tmp_path)})
    assert service.freshened == [tmp_path]
    assert result["findings"] == []
    assert result["gate"]["status"] == "unknown"
    assert [item["message"] for item in result["diagnostics"]] == [
        "syntax error — partial extract kept"
    ]
    set_index_service(None)
