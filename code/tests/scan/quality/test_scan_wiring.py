"""Scan wiring: quality tables, --skip-quality golden, generated exemption, mode."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

_GATE = Path(__file__).parents[2] / "quality_gate" / "fixtures"
sys.path.insert(0, str(_GATE))

from gate_calibration import load_gate_test_calibration  # noqa: E402
from gate_snapshots import SNAPSHOTS  # noqa: E402
from varde_code import cli_scan  # noqa: E402
from varde_code.extract.provider import CodeExtractionProvider  # noqa: E402
from varde_code.index.build import build  # noqa: E402
from varde_code.model import Span  # noqa: E402
from varde_code.parse import parse_source  # noqa: E402
from varde_code.query import modes  # noqa: E402
from varde_code.rules import loader  # noqa: E402
from varde_code.rules.finding import Finding, Location  # noqa: E402
from varde_code.rules.model import Severity  # noqa: E402
from varde_code.rules.scan_output import filter_generated  # noqa: E402
from varde_code.scan import core, quality_wiring, report_run  # noqa: E402
from varde_code.scan.test_cmd import run_tests  # noqa: E402

GATE_IDS = ("quality-file-floor", "quality-function-cap", "quality-scope-mean")


@pytest.fixture(autouse=True)
def _grammar() -> None:
    try:
        parse_source("python", "value\n")
    except RuntimeError as error:
        pytest.skip(f"tree-sitter grammar cache unavailable: {error}")


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(modes, "_INDEX_SERVICE", None)
    root = tmp_path / "repo"
    for name, text in SNAPSHOTS["python"].files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    build(root, CodeExtractionProvider())
    return root


def _finding(rule_id: str, file: str, severity=Severity.ERROR, **evidence) -> Finding:
    return Finding(
        "id-" + file, rule_id, severity, "m", Location(file, Span(0, 0, 1, 0, 1, 0)),
        evidence, None,
    )  # fmt: skip


def test_scan_default_materializes_quality_and_caps_unvalidated_languages(repo):
    result = core.scan_repo({"repoRoot": str(repo), "fullFindings": True})

    quality = [f for f in result["findings"] if f["rule_id"].startswith("quality-")]
    gate = [f for f in quality if f["rule_id"] in GATE_IDS]
    assert {f["rule_id"] for f in gate} >= {
        "quality-file-floor",
        "quality-function-cap",
    }
    assert {f["severity"] for f in gate} == {"info"}
    assert all(f["evidence"]["quality_mode"] == "not validated" for f in gate)
    assert result["gate"]["status"] == "pass"
    assert not [d for d in result["diagnostics"] if d["rule_id"].startswith("quality-")]


def test_validated_language_keeps_severity(repo, monkeypatch):
    calibration = load_gate_test_calibration()
    monkeypatch.setattr(core, "load_calibration", lambda path: calibration)

    result = core.scan_repo({"repoRoot": str(repo), "fullFindings": True})

    severities = {
        f["rule_id"]: f["severity"]
        for f in result["findings"]
        if f["rule_id"] in ("quality-file-floor", "quality-function-cap")
    }
    assert set(severities.values()) == {"error"}
    assert result["gate"]["status"] == "fail"


def test_skip_quality_equals_the_pre_gate_payload(repo, monkeypatch):
    skipped = core.scan_repo({"repoRoot": str(repo), "skipQuality": True})
    real = loader.load_rules_with_details

    def pre_gate(root):
        rules, diagnostics, details = real(root)
        return quality_wiring.without_quality(rules), diagnostics, details

    monkeypatch.setattr(core, "load_rules_with_details", pre_gate)
    golden = core.scan_repo({"repoRoot": str(repo)})

    assert json.dumps(skipped, sort_keys=True) == json.dumps(golden, sort_keys=True)
    assert not any(f["rule_id"].startswith("quality-") for f in skipped["findings"])
    assert "quality-file-floor" not in json.dumps(skipped)


def test_rules_off_creates_no_quality_work(repo, monkeypatch):
    (repo / ".varde-code").mkdir()
    ids = (*GATE_IDS, "quality-unscored-share", "quality-suppressed")
    (repo / ".varde-code" / "overrides.toml").write_text(
        "\n".join(f'[rules.{rid}]\nseverity = "off"\n' for rid in ids), encoding="utf-8"
    )
    monkeypatch.setattr(
        core, "materialize_quality_scores", lambda *a, **k: pytest.fail("ran")
    )
    result = core.scan_repo({"repoRoot": str(repo)})
    assert not any(f["rule_id"].startswith("quality-") for f in result["findings"])


def test_skip_quality_must_be_boolean(tmp_path):
    with pytest.raises(core.QueryError, match="skipQuality must be a boolean"):
        core.scan_options({"repoRoot": str(tmp_path), "skipQuality": "yes"})


def test_cli_flag_sets_skip_quality(monkeypatch, capsys, tmp_path):
    seen = []
    monkeypatch.setattr(
        cli_scan,
        "scan_repo",
        lambda value, capture=None: (
            seen.append(copy.deepcopy(value)) or {"gate": {"status": "pass"}}
        ),
    )
    args = ["--json", json.dumps({"repoRoot": str(tmp_path)})]
    assert cli_scan.run(["scan", *args, "--skip-quality"]) == 0
    assert cli_scan.run(["scan", *args]) == 0
    capsys.readouterr()
    assert seen[0]["skipQuality"] is True
    assert "skipQuality" not in seen[1]


def test_report_scan_skips_quality(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(
        "varde_code.scan.core.scan_repo",
        lambda payload: seen.append(payload) or {"findings": []},
    )
    report_run.default_scan({"repoRoot": str(tmp_path)})
    assert seen == [{"repoRoot": str(tmp_path), "skipQuality": True}]


def test_generated_filter_exempts_quality_findings_only():
    findings = [
        _finding("quality-file-floor", "vendor/a.py"),
        _finding("eval-usage", "vendor/b.py"),
        _finding("quality-scope-mean", "."),
        _finding("eval-usage", "src/c.py"),
    ]
    kept = quality_wiring.split_generated_filter(findings, filter_generated)
    assert [(f.rule_id, f.location.file) for f in kept] == [
        ("quality-file-floor", "vendor/a.py"),
        ("quality-scope-mean", "."),
        ("eval-usage", "src/c.py"),
    ]


def test_threshold_rows_cover_languages_and_scope_mean():
    calibration = load_gate_test_calibration()
    rows = quality_wiring.threshold_rows(calibration)
    languages = [row[1] for row in rows]
    assert languages[-1] is None
    assert set(languages[:-1]) == set(calibration.languages)
    x_values = [row[2] for row in rows[:-1]]
    assert rows[-1][2] == min(x_values)


def test_state_lookup_is_conservative_without_a_recorded_state():
    calibration = load_gate_test_calibration()
    state_of = quality_wiring.calibration_state_lookup(calibration)
    assert state_of("python") == "panel-validated"
    assert state_of("tsx") == state_of("typescript")
    assert state_of("cobol") is None


def test_scope_finding_gates_only_when_every_language_validated():
    state_of = {"python": "panel-validated", "csharp": "report-only"}.get
    mean = _finding("quality-scope-mean", ".", Severity.WARNING)
    kept = quality_wiring.apply_quality_mode([mean], state_of, ["python"])
    capped = quality_wiring.apply_quality_mode([mean], state_of, ["csharp", "python"])
    assert kept[0].severity is Severity.WARNING
    assert capped[0].severity is Severity.INFO
    assert capped[0].evidence["quality_mode"] == "not validated"


def test_scan_test_does_not_need_quality_tables(tmp_path):
    result = run_tests({"repoRoot": str(tmp_path)})
    assert result["summary"]["failed"] == 0
