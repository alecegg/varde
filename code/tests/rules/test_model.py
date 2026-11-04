import sqlite3

import pytest
from varde_code.model import Span
from varde_code.rules.index_reader import finding_id, run_sql_rules
from varde_code.rules.model import (
    ConstraintSpec,
    Rule,
    RuleKind,
    Severity,
    Verification,
)


def test_model_parses_rule_enums_and_constraint_forms():
    rule = Rule.from_mapping(
        {
            "id": "sample",
            "kind": "sql",
            "severity": "WARNING",
            "message": "found {count}",
            "verification": "exact-clone",
            "constraints": {"NAME": ["^A", "Z$"], "VALUE": "[0-9]+"},
            "ignored": True,
        }
    )
    assert rule.kind is RuleKind.SQL
    assert rule.severity is Severity.WARNING
    assert rule.verification is Verification.EXACT_CLONE
    assert rule.constraints == {
        "NAME": ConstraintSpec(("^A", "Z$")),
        "VALUE": ConstraintSpec(("[0-9]+",)),
    }


@pytest.mark.parametrize("missing", ["id", "kind", "severity", "message"])
def test_model_requires_core_fields(missing):
    data = {"id": "sample", "kind": "pattern", "severity": "info", "message": "m"}
    del data[missing]
    with pytest.raises(ValueError, match=f"missing field `{missing}`"):
        Rule.from_mapping(data)


def test_severity_order_and_case_insensitive_lookup():
    assert Severity.from_name("Error") is Severity.ERROR
    assert Severity.from_name("unknown") is None
    assert Severity.ERROR.rank > Severity.WARNING.rank > Severity.INFO.rank


def test_model_coerces_threshold_numbers_and_rejects_invalid_field_types():
    rule = Rule.from_mapping(
        {
            "id": "sample",
            "kind": "sql",
            "severity": "warning",
            "message": "x",
            "query": "SELECT :limit",
            "thresholds": {"limit": 7},
        }
    )
    assert rule.thresholds is not None
    assert rule.thresholds == {"limit": 7.0}
    assert isinstance(rule.thresholds["limit"], float)
    with pytest.raises(ValueError, match="invalid type"):
        Rule.from_mapping(
            {"id": 4, "kind": "pattern", "severity": "warning", "message": "x"}
        )
    with pytest.raises(ValueError, match="missing field `message`"):
        Rule.from_mapping({"id": "sample", "kind": "pattern", "severity": "warning"})
    with pytest.raises(ValueError, match="unknown variant"):
        Rule.from_mapping(
            {"id": "sample", "kind": "regex", "severity": "warning", "message": "x"}
        )


def test_sql_reader_binds_values_and_maps_evidence_location_and_id():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE t (file TEXT, line INTEGER, count INTEGER, note TEXT)")
    db.execute("INSERT INTO t VALUES ('src/a.py', 3, 8, 'value')")
    rule = Rule.from_mapping(
        {
            "id": "large-count",
            "kind": "sql",
            "severity": "error",
            "message": "count {count}",
            "query": (
                "SELECT file, line, count, note FROM t WHERE count > :limit "
                "AND note = :needle"
            ),
            "thresholds": {"limit": 4},
            "strings": {"needle": "value", "unused": "ignored"},
            "remediation": "reduce it",
            "fix": "review it",
        }
    )
    findings, diagnostics = run_sql_rules([rule], db)
    assert diagnostics == []
    assert len(findings) == 1
    finding = findings[0]
    expected_span = Span(0, 0, 3, 0, 3, 0)
    assert finding.location.file == "src/a.py"
    assert finding.location.span == expected_span
    assert finding.evidence == {"count": 8, "note": "value"}
    assert finding.message == "count 8"
    assert finding.id == finding_id("large-count", "src/a.py", expected_span)
    assert finding.agent_instructions == "review it"


def test_sql_reader_reports_bad_rule_and_continues():
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE t (file TEXT, line INTEGER)")
    db.execute("INSERT INTO t VALUES ('a.py', 1)")
    bad = Rule.from_mapping(
        {
            "id": "bad",
            "kind": "sql",
            "severity": "info",
            "message": "x",
            "query": "SELECT line FROM t",
        }
    )
    good = Rule.from_mapping(
        {
            "id": "good",
            "kind": "sql",
            "severity": "info",
            "message": "x",
            "query": "SELECT file, line FROM t",
        }
    )
    findings, diagnostics = run_sql_rules([bad, good], db)
    assert len(findings) == 1
    assert diagnostics[0].rule_id == "bad"
    assert "file" in diagnostics[0].reason
