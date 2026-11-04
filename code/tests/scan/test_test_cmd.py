from pathlib import Path

import pytest
from varde_code import ApiError
from varde_code.scan.test_cmd import run_tests


def _write_pack(directory: Path, text: str) -> Path:
    directory.mkdir(parents=True)
    path = directory / "pack.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_reports_pass_fail_and_rule_pack_path(tmp_path):
    pack = _write_pack(
        tmp_path / "rules",
        """
[[rule]]
id = "no-console-log"
kind = "pattern"
severity = "warning"
message = "console.log detected"
pattern = "console.log($MSG)"

[[rule.test]]
name = "flags console.log"
invalid = ["console.log(1);"]

[[rule.test]]
name = "incorrectly expects clean code"
valid = ["console.log(1);"]
""",
    )

    result = run_tests({"rulesDir": str(pack.parent)})

    assert result["summary"] == {"passed": 1, "failed": 1}
    assert result["results"][0] == {
        "rule_id": "no-console-log",
        "test_name": "flags console.log",
        "status": "pass",
        "file": str(pack),
    }
    failure = result["results"][1]
    assert failure["status"] == "fail"
    assert failure["detail"]
    assert result["diagnostics"] == []


def test_empty_rules_and_malformed_test_diagnostic(tmp_path):
    _write_pack(
        tmp_path / "rules",
        """
[[rule]]
id = "broken-test"
kind = "pattern"
severity = "warning"
message = "console.log detected"
pattern = "console.log($MSG)"

[[rule.test]]
name = "invalid rewrite expectation"
[rule.test.expect_rewrite]
"console.log(1)" = "console.info(1)"
""",
    )

    result = run_tests({"rulesDir": str(tmp_path / "rules")})

    assert result["results"] == []
    assert result["summary"] == {"passed": 0, "failed": 0}
    assert result["diagnostics"]


def test_missing_rules_directory_is_invalid_input():
    with pytest.raises(ApiError, match="rulesDir is not a directory"):
        run_tests({"rulesDir": "/missing/varde-test-rules"})


def test_pages_more_than_one_hundred_results(tmp_path):
    tests = "".join(
        f'\n[[rule.test]]\nname = "case {index}"\ninvalid = ["console.log(1);"]\n'
        for index in range(101)
    )
    _write_pack(
        tmp_path / "rules",
        """
[[rule]]
id = "many-tests"
kind = "pattern"
severity = "warning"
message = "console.log detected"
pattern = "console.log($MSG)"
"""
        + tests,
    )

    result = run_tests({"rulesDir": str(tmp_path / "rules")})

    assert result["summary"] == {"passed": 101, "failed": 0}
    assert len(result["results"]) == 100
    assert result["guide"]["truncated"]["results"] == {"shown": 100, "total": 101}


def test_capture_pages_results_and_adds_query_guides(tmp_path, monkeypatch):
    monkeypatch.delenv("VARDE_CODE_TOZ", raising=False)
    tests = "".join(
        f'\n[[rule.test]]\nname = "case {index}"\ninvalid = ["console.log(1);"]\n'
        for index in range(101)
    )
    _write_pack(
        tmp_path / "rules",
        """
[[rule]]
id = "many-tests"
kind = "pattern"
severity = "warning"
message = "console.log detected"
pattern = "console.log($MSG)"
"""
        + tests,
    )

    class Capture:
        def __init__(self):
            self.items = []

        def capture(self, items, source, label):
            self.items = items.items
            return '{"handle":"test-handle"}'

    capture = Capture()
    result = run_tests({"rulesDir": str(tmp_path / "rules")}, capture)

    assert len(capture.items) == 101
    assert result["summary"] == {"passed": 101, "failed": 0}
    assert len(result["results"]) == 20
    assert result["guide"]["toz"]["handle"] == "test-handle"
    details = result["guide"]["truncated"]["results"]
    assert details["shown"] == 20
    assert details["total"] == 101
    assert details["toz_read"] == "varde run query --handle test-handle --lines 21:40"
    assert details["toz_search"] == 'varde run query --handle test-handle "<term>"'
