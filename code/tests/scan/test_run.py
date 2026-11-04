from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from varde_code.model import Span
from varde_code.rules.finding import Finding, Location
from varde_code.rules.model import Rule, RuleKind, Severity
from varde_code.scan.core import (
    _attach_gate,
    _attach_policy,
    _build_payload,
    _truncate_findings,
)


def test_selected_gate_counts_only_unresolved_selected_findings():
    payload = {
        "diagnostics": [],
        "findings": [
            {"rule_id": "chosen", "severity": "info", "rewrite_status": "applied"},
            {
                "rule_id": "chosen",
                "severity": "info",
                "rewrite_status": "skipped-dirty",
            },
            {"rule_id": "other", "severity": "error"},
        ],
    }
    _attach_gate(payload, Severity.ERROR, ["chosen"])
    gate = cast("dict[str, Any]", payload["gate"])
    assert gate["blocking_findings"] == 1
    assert gate["status"] == "fail"
    payload["findings"].pop(1)
    _attach_gate(payload, Severity.ERROR, ["chosen"])
    gate = cast("dict[str, Any]", payload["gate"])
    assert gate["status"] == "pass"


def test_gate_ignores_fixture_diagnostics_and_reports_incomplete_analysis():
    payload = {
        "diagnostics": [
            {"source": "persisted", "message": "syntax error", "is_test_path": True},
            {"source": "rules", "message": "invalid rule"},
        ],
        "findings": [],
    }
    _attach_gate(payload, Severity.ERROR, None)
    gate = cast("dict[str, Any]", payload["gate"])
    analysis = cast("dict[str, Any]", payload["analysis"])
    assert gate["diagnostic_count"] == 2
    assert gate["blocking_diagnostic_count"] == 1
    assert analysis["status"] == "incomplete"
    assert gate["status"] == "unknown"


def test_policy_includes_requested_gate_and_rule_origins(tmp_path: Path):
    rules = [
        Rule("a", RuleKind.PATTERN, Severity.ERROR, "a"),
        Rule("b", RuleKind.PATTERN, Severity.WARNING, "b"),
    ]
    payload = {}
    _attach_policy(
        payload,
        rules,
        {"a": "builtin", "b": "override"},
        Severity.WARNING,
        ["b"],
        tmp_path,
    )
    assert payload["policy"]["mode"] == "selected-rules"
    assert payload["policy"]["active_rule_count"] == 2
    assert payload["policy"]["gating_rule_count"] == 1
    assert payload["policy"]["severity_threshold"] is None
    assert payload["policy"]["rule_ids"] == ["b"]
    assert payload["policy"]["sources"] == {"builtin": 1, "custom": 0, "override": 1}
    assert payload["policy"]["fingerprint"].startswith("fnv1a64:")


def test_payload_builder_keeps_all_findings_until_paging():
    findings = [
        Finding(
            str(index),
            "r",
            Severity.ERROR,
            "message",
            Location(f"src/{index}.py", Span(0, 1, 1, 0, 1, 1)),
            {},
            None,
        )
        for index in range(101)
    ]
    payload = _build_payload(findings, [], [], [], Path("."))
    assert len(payload["findings"]) == 101
    assert payload["findings_summary"]["total"] == 101


def test_truncation_captures_full_findings_and_uses_short_page(monkeypatch):
    monkeypatch.setattr(
        "varde_code.scan.core.capture_items",
        lambda capture, mode, findings: {
            "handle": "scan-handle",
            "items": len(findings),
        },
    )
    findings = [{"id": index} for index in range(101)]
    payload = {"findings": findings, "findings_summary": {"total": 101}}
    _truncate_findings(
        payload, {"full": False, "limit": 100, "offset": 0}, {}, object()
    )
    assert len(payload["findings"]) == 20
    assert payload["guide"]["toz"]["items"] == 101
    assert payload["guide"]["truncated"]["findings"]["next_offset"] == 20
    assert payload["guide"]["truncated"]["findings"]["toz_read"].endswith(
        "--lines 21:40"
    )
