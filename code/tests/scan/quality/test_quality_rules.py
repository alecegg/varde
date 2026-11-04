"""Gate rules over the TEMP tables: floor, cap, mean, unscored share, suppressed."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

_GATE = Path(__file__).parents[2] / "quality_gate" / "fixtures"
sys.path.insert(0, str(_GATE))

from gate_calibration import load_gate_test_calibration  # noqa: E402
from gate_snapshots import LANGUAGES, SNAPSHOTS  # noqa: E402
from varde_code.extract.provider import CodeExtractionProvider  # noqa: E402
from varde_code.index.build import build  # noqa: E402
from varde_code.index.paths import repo_db_path  # noqa: E402
from varde_code.parse import parse_source  # noqa: E402
from varde_code.query import modes  # noqa: E402
from varde_code.rules.loader import load_rules_with_details  # noqa: E402
from varde_code.rules.sql import run_sql_rules  # noqa: E402
from varde_code.scan.quality_scores import (  # noqa: E402
    QualityRow,
    materialize_quality_scores,
    write_quality_scores,
)

MICRO = 1_000_000
GATE_IDS = ("quality-file-floor", "quality-function-cap", "quality-scope-mean")
ALL_IDS = (*GATE_IDS, "quality-unscored-share", "quality-suppressed")
THRESHOLDS_TABLE = (
    "CREATE TEMP TABLE IF NOT EXISTS quality_thresholds (scope TEXT, "
    "language TEXT, mean_x INTEGER, file_floor_y INTEGER, function_cap INTEGER)"
)
SUPPRESSIONS_TABLE = (
    "CREATE TEMP TABLE IF NOT EXISTS quality_suppressions "
    "(scope TEXT, rule_id TEXT, suppressed INTEGER)"
)


@pytest.fixture(autouse=True, scope="session")
def _grammars() -> None:
    for grammar in ("python", "typescript", "tsx", "csharp"):
        try:
            parse_source(grammar, "value\n")
        except RuntimeError as error:
            pytest.skip(f"tree-sitter grammar cache unavailable: {error}")


@pytest.fixture
def repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(modes, "_INDEX_SERVICE", None)
    (tmp_path / "repo").mkdir()
    return tmp_path / "repo"


def _quality_rules(root: Path, severity: str | None = None):
    if severity is not None:
        lines = "\n".join(
            f'[rules.{rid}]\nseverity = "{severity}"\n' for rid in ALL_IDS
        )
        (root / ".varde-code").mkdir(exist_ok=True)
        (root / ".varde-code" / "overrides.toml").write_text(lines, encoding="utf-8")
    rules, _, _ = load_rules_with_details(root)
    return [rule for rule in rules if rule.id.startswith("quality-")]


def _thresholds(conn: sqlite3.Connection, calibration, scope: str = "repo") -> None:
    conn.execute(THRESHOLDS_TABLE)
    entries = [(None, "python")] + [(name, name) for name in calibration.languages]
    for language, source in entries:
        params = calibration.languages[source].parameters
        conn.execute(
            "INSERT INTO quality_thresholds VALUES (?, ?, ?, ?, ?)",
            (scope, language, params["X"], params["Y"], params["cap"]),
        )


def _run(rules, conn):
    """Run rules; absent TEMP tables are created empty, as scan would."""
    exists = "SELECT 1 FROM temp.sqlite_master WHERE name = 'quality_scores'"
    if conn.execute(exists).fetchone() is None:
        write_quality_scores(conn, [])
    conn.execute(THRESHOLDS_TABLE)
    conn.execute(SUPPRESSIONS_TABLE)
    findings, diagnostics = run_sql_rules(rules, conn)
    assert diagnostics == []
    return findings


def _by_rule(findings, rule_id):
    return [f for f in findings if f.rule_id == rule_id]


def _indexed_conn(root: Path, files: dict[str, str]) -> sqlite3.Connection:
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    build(root, CodeExtractionProvider())
    return sqlite3.connect(f"file:{repo_db_path(root).resolve()}?mode=ro", uri=True)


def _row(level, **fields) -> QualityRow:
    base = {
        "scope": "repo",
        "level": level,
        "path": None,
        "language": "python",
        "function_id": None,
        "line": None,
        "score": None,
        "tokens": None,
        "debt": None,
        "exempt": False,
        "exempt_reason": None,
        "diagnostics": "",
        "calibration_id": "cal",
        "metric_version": "vq1",
    }
    return QualityRow(**{**base, **fields})


def _synthetic(conn, rows, calibration=None) -> None:
    write_quality_scores(conn, rows)
    _thresholds(conn, calibration or load_gate_test_calibration())


@pytest.mark.parametrize("severity", ["error", "warning"])
@pytest.mark.parametrize("language", LANGUAGES)
def test_floor_and_cap_flag_the_debt_file_at_the_configured_severity(
    language, severity, repo
):
    snapshot = SNAPSHOTS[language]
    calibration = load_gate_test_calibration()
    conn = _indexed_conn(repo, snapshot.files)
    try:
        materialize_quality_scores(conn, repo, calibration, workers=1)
        _thresholds(conn, calibration)
        findings = _run(_quality_rules(repo, severity), conn)
    finally:
        conn.close()

    floors = _by_rule(findings, "quality-file-floor")
    caps = _by_rule(findings, "quality-function-cap")
    assert {f.location.file for f in floors} >= {snapshot.path("debt")}
    assert snapshot.path("clean") not in {f.location.file for f in floors}
    assert snapshot.path("floor_exempt") not in {f.location.file for f in floors}
    assert snapshot.path("debt") in {f.location.file for f in caps}
    assert {f.severity.name.lower() for f in floors + caps} == {severity}
    evidence = floors[0].evidence
    assert {"scope", "language", "score", "threshold", "calibration_id"} <= set(
        evidence
    )
    assert all(not isinstance(v, (dict, list)) for v in evidence.values())


@pytest.mark.parametrize("language", LANGUAGES)
def test_off_removes_every_quality_rule(language, repo):
    (repo / ".varde-code").mkdir()
    (repo / ".varde-code" / "overrides.toml").write_text(
        "\n".join(f'[rules.{rid}]\nseverity = "off"\n' for rid in ALL_IDS),
        encoding="utf-8",
    )
    assert _quality_rules(repo) == []


def test_default_severities_are_cap_error_floor_error_mean_warning(repo):
    rules = {rule.id: rule.severity.name.lower() for rule in _quality_rules(repo)}
    assert rules == {
        "quality-file-floor": "error",
        "quality-function-cap": "error",
        "quality-scope-mean": "warning",
        "quality-unscored-share": "warning",
        "quality-suppressed": "warning",
    }


def test_exempt_file_gets_no_floor_finding_but_the_cap_persists(repo):
    rows = [
        _row("scope", score=70 * MICRO, tokens=100),
        _row("file", path="a.py", score=10 * MICRO, tokens=40, exempt=True,
             exempt_reason="fixed overhead reaches floor threshold"),
        _row("file", path="b.py", score=10 * MICRO, tokens=40),
        _row("function", path="a.py", function_id="a.f", line=3, debt=13 * MICRO),
        _row("function", path="a.py", function_id="a.g", line=9, debt=12 * MICRO),
    ]  # fmt: skip
    conn = sqlite3.connect(":memory:")
    _synthetic(conn, rows)
    findings = _run(_quality_rules(repo), conn)

    assert [f.location.file for f in _by_rule(findings, "quality-file-floor")] == [
        "b.py"
    ]
    caps = _by_rule(findings, "quality-function-cap")
    assert [f.evidence["function_id"] for f in caps] == ["a.f"]
    assert caps[0].location.span.start_line == 3


def test_file_exactly_at_the_floor_and_function_exactly_at_the_cap_pass(repo):
    params = load_gate_test_calibration().languages["python"].parameters
    rows = [
        _row("scope", score=params["X"], tokens=10),
        _row("file", path="a.py", score=params["Y"], tokens=10),
        _row("function", path="a.py", function_id="a.f", line=1, debt=params["cap"]),
    ]
    conn = sqlite3.connect(":memory:")
    _synthetic(conn, rows)
    assert _run(_quality_rules(repo), conn) == []


def test_scope_mean_is_reported_per_scope_including_tests_and_tooling(repo):
    x = load_gate_test_calibration().languages["python"].parameters["X"]
    rows = [
        _row("scope", scope="repo", score=x + MICRO, tokens=10),
        _row("scope", scope="tests", score=x - MICRO, tokens=10),
        _row("scope", scope="tooling", score=None, tokens=0),
    ]
    conn = sqlite3.connect(":memory:")
    write_quality_scores(conn, rows)
    calibration = load_gate_test_calibration()
    for scope in ("repo", "tests", "tooling"):
        _thresholds(conn, calibration, scope) if scope == "repo" else conn.execute(
            "INSERT INTO quality_thresholds VALUES (?, NULL, ?, 0, 0)", (scope, x)
        )
    findings = _by_rule(_run(_quality_rules(repo), conn), "quality-scope-mean")

    assert [f.evidence["scope"] for f in findings] == ["tests"]
    assert findings[0].severity.name.lower() == "warning"


def test_unscored_share_flags_above_ten_percent_and_marks_blocking_above_twenty(repo):
    def files(scope, unscored, scored, na=0):
        out = [_row("file", scope=scope, path=f"{scope}/u", tokens=unscored, score=None,
                    exempt_reason="generated")]  # fmt: skip
        out.append(
            _row(
                "file", scope=scope, path=f"{scope}/s", tokens=scored, score=80 * MICRO
            )
        )
        out.append(_row("file", scope=scope, path=f"{scope}/n", tokens=na, score=None))
        return out

    rows = files("ok", 10, 90, na=500) + files("warn", 11, 89) + files("block", 21, 79)
    conn = sqlite3.connect(":memory:")
    write_quality_scores(conn, rows)
    findings = _by_rule(_run(_quality_rules(repo), conn), "quality-unscored-share")

    assert {f.evidence["scope"]: f.evidence["blocking"] for f in findings} == {
        "warn": 0,
        "block": 1,
    }


def test_suppressed_counts_per_scope_and_is_silent_at_zero(repo):
    conn = sqlite3.connect(":memory:")
    conn.execute(SUPPRESSIONS_TABLE)
    conn.executemany(
        "INSERT INTO quality_suppressions VALUES (?, ?, ?)",
        [
            ("repo", "quality-file-floor", 2),
            ("repo", "quality-function-cap", 1),
            ("tests", "quality-file-floor", 0),
        ],
    )
    findings = _by_rule(_run(_quality_rules(repo), conn), "quality-suppressed")

    assert [(f.evidence["scope"], f.evidence["suppressed"]) for f in findings] == [
        ("repo", 3)
    ]
