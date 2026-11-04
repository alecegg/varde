import json

from varde_design.report import (
    SCHEMA_VERSION,
    Finding,
    build_report,
    checked_block,
    exit_code,
    validate_report,
)


def _checked(**overrides: object) -> dict[str, object]:
    args: dict[str, object] = {
        "tiers": ["static"],
        "widths": [390],
        "settings_source": "defaults",
    }
    args.update(overrides)
    return checked_block(**args)  # type: ignore[arg-type]


def _finding(severity: str = "warn") -> Finding:
    return Finding(
        id="S8",
        severity=severity,
        tier="static",
        file="a.html",
        message="lorem",
        line=3,
    )


def test_report_has_versioned_envelope_and_is_json_serialisable() -> None:
    report = build_report("check", [_finding()], _checked())
    assert report["schema"] == SCHEMA_VERSION == 1
    assert report["command"] == "check"
    assert json.loads(json.dumps(report)) == report
    assert validate_report(report) == []


def test_validation_flags_each_structural_problem() -> None:
    assert validate_report([]) == ["report: expected an object"]
    report = build_report("check", [_finding()], _checked())
    report["schema"] = 2
    report["command"] = "other"
    errors = validate_report(report)
    assert any("schema: expected 1" in e for e in errors)
    assert any("command:" in e for e in errors)
    bad = build_report("tokens", [], _checked())
    bad["findings"] = [{"id": "Z9"}]
    assert any("missing key" in e for e in validate_report(bad))
    unknown = build_report(
        "check", [Finding("Z9", "warn", "static", "f", "m")], _checked()
    )
    assert any("unknown rule id" in e for e in validate_report(unknown))
    badsev = build_report(
        "check", [Finding("S8", "info", "static", "f", "m")], _checked()
    )
    assert any("severity" in e for e in validate_report(badsev))


def test_exit_codes() -> None:
    assert exit_code(build_report("check", [], _checked())) == 0
    assert exit_code(build_report("check", [_finding("warn")], _checked())) == 0
    assert exit_code(build_report("check", [_finding("fail")], _checked())) == 2
    not_run = _checked(not_run=["render: not run (no browser)"])
    assert exit_code(build_report("check", [], not_run)) == 1
    assert exit_code(build_report("check", [_finding("fail")], not_run)) == 2
    assert exit_code(build_report("check", [], _checked(truncated=(10, 50)))) == 1


def test_checked_block_records_truncation_and_defaults() -> None:
    block = _checked(truncated=(10, 50), elements=7)
    assert block["truncated"] == {"shown": 10, "total": 50}
    assert block["elements"] == 7
    assert _checked()["truncated"] is None
    assert _checked()["not_run"] == []
