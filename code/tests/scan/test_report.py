from __future__ import annotations

import re

import pytest
from varde_code.scan.report import ReportError, index_error_code, summary_line


def _result(findings=(), gate="pass", analysis="complete", ok=True):
    return {
        "ok": ok,
        "data": {
            "analysis": {"status": analysis},
            "gate": {"status": gate},
            "findings": list(findings),
        },
    }


@pytest.mark.parametrize(
    ("findings", "gate"), [([], "pass"), ([{"severity": "error"}], "fail")]
)
def test_summary_for_pass_and_fail(findings, gate):
    line = summary_line(_result(findings, gate), 0, 2)
    assert f"gate={gate}" in line
    assert re.search(r"build=\d+s scan=\d+s", line)


def test_counts_by_severity():
    findings = [
        {"severity": "error"},
        {"severity": "warning"},
        {"severity": "warning"},
        {"severity": "info"},
        "junk",
    ]
    line = summary_line(_result(findings, "fail"), 3, 4)
    assert line == (
        "gate=fail analysis=complete errors=1 warnings=2 info=1 build=3s scan=4s"
    )


@pytest.mark.parametrize(
    "result",
    [
        "text",
        [],
        {"invalid": "schema"},
        {"ok": True, "data": []},
        {"ok": True, "data": {"gate": {}, "findings": []}},
        {"ok": True, "data": {"analysis": {}, "findings": []}},
        {"ok": True, "data": {"analysis": {}, "gate": {}}},
        _result(ok=False),
        {"ok": False, "data": {"error": {"code": "tool_error"}}},
        _result(analysis="incomplete"),
        _result(gate="unknown"),
    ],
)
def test_invalid_results_raise(result):
    with pytest.raises(ReportError):
        summary_line(result, 0, 0)


@pytest.mark.parametrize("code", ["index_missing", "index_stale"])
def test_index_error_code_top_level_and_nested(code):
    assert index_error_code({"error": {"code": code}}) == code
    assert index_error_code({"ok": False, "data": {"error": {"code": code}}}) == code


@pytest.mark.parametrize(
    "result",
    [
        None,
        [],
        {},
        _result(),
        {"error": {"code": "tool_error"}},
        {"data": {"error": {"code": "tool_error"}}},
        {"data": []},
        {"error": "index_missing"},
    ],
)
def test_other_results_give_empty_code(result):
    assert index_error_code(result) == ""
