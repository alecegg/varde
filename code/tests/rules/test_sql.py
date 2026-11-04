# ruff: noqa: UP034 - Explicit grouping preserves split fixture strings in calls.
import sqlite3
from pathlib import Path

from varde_code.model import Entity, EntityKind, ExtractOutput, Span
from varde_code.rules.dependency_facts import prepare
from varde_code.rules.finding import finding_id
from varde_code.rules.model import Diagnostic, Rule, RuleKind, Severity, Verification
from varde_code.rules.sql import run_sql_rules, run_sql_rules_in_repo


class FakeProvider:
    def __init__(self, entities=None):
        self.entities = entities or []
        self.calls = []

    def extract(self, path, source, language):
        self.calls.append((path, language))
        return ExtractOutput(entities=self.entities)


def rule(rule_id: str, query: str | None, **kwargs) -> Rule:
    return Rule(
        id=rule_id,
        kind=RuleKind.SQL,
        severity=Severity.ERROR,
        message=kwargs.pop("message", "{note}: {count}"),
        query=query,
        **kwargs,
    )


def connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE t (file TEXT, line INTEGER, count INTEGER, note TEXT)")
    conn.executemany(
        "INSERT INTO t VALUES (?, ?, ?, ?)",
        [("a.rs", 1, 5, "alpha"), ("b.rs", 2, 1, "beta")],
    )
    return conn


def test_sql_rule_binds_threshold_and_maps_rows_to_findings():
    conn = connection()
    item = rule(
        "high",
        "SELECT file, line, count, note FROM t WHERE count > :limit",
        thresholds={"limit": 3.0},
    )

    findings, diagnostics = run_sql_rules([item], conn)

    assert diagnostics == []
    assert len(findings) == 1
    finding = findings[0]
    assert finding.location.file == "a.rs"
    assert finding.location.span.start_line == finding.location.span.end_line == 1
    assert finding.evidence == {"count": 5, "note": "alpha"}
    assert finding.message == "alpha: 5"
    assert finding.certainty is None


def test_repository_sql_findings_keep_absolute_paths_for_ids(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE findings (file TEXT, line INTEGER)")
    conn.execute(
        "INSERT INTO findings VALUES (?, 4)", (str(tmp_path / "src" / "a.py"),)
    )
    item = rule("relative", "SELECT file, line FROM findings")

    findings, diagnostics = run_sql_rules_in_repo(
        [item], conn, tmp_path, FakeProvider()
    )

    assert diagnostics == []
    assert findings[0].location.file == str(tmp_path / "src" / "a.py")
    assert findings[0].id == finding_id(
        "relative", str(tmp_path / "src" / "a.py"), findings[0].location.span
    )


def test_sql_string_binding_and_unreferenced_parameters():
    conn = connection()
    item = rule(
        "needle",
        "SELECT file, line, note FROM t WHERE note = :needle",
        strings={"needle": "beta", "unused": "ignore"},
    )

    findings, diagnostics = run_sql_rules([item], conn)

    assert diagnostics == []
    assert [(f.location.file, f.evidence) for f in findings] == [
        ("b.rs", {"note": "beta"})
    ]


def test_sql_missing_bind_ignores_comment_parameters() -> None:
    conn = connection()
    item = rule(
        "nullable",
        (
            "SELECT file, line, note FROM t WHERE note = :missing AND "
            "':inside' = ':inside' -- :comment"
        ),
    )
    findings, diagnostics = run_sql_rules([item], conn)
    assert findings == []
    assert diagnostics == []


def test_message_scanner_uses_first_open_and_following_close_brace() -> None:
    conn = connection()
    item = rule(
        "nested",
        'SELECT file, line, 1 AS "outer{inner" FROM t WHERE count = 5',
        message="x {outer{inner} y",
    )

    findings, diagnostics = run_sql_rules([item], conn)

    assert diagnostics == []
    assert [finding.message for finding in findings] == ["x 1 y"]


def test_invalid_rules_report_diagnostics_and_allow_later_rules():
    conn = connection()
    items = [
        rule("bad-sql", "SELECT FROM"),
        rule("bad-cols", "SELECT count FROM t"),
        rule("good", "SELECT file, line, count FROM t WHERE count = 5"),
    ]

    findings, diagnostics = run_sql_rules(items, conn)

    assert [f.rule_id for f in findings] == ["good"]
    assert [d.rule_id for d in diagnostics] == ["bad-sql", "bad-cols"]
    assert "SQL prepare failed" in diagnostics[0].reason
    assert "file` column and a `line` column" in diagnostics[1].reason


def test_pattern_rules_are_ignored_and_unavailable_verification_is_reported():
    conn = connection()
    pattern = Rule("pattern", RuleKind.PATTERN, Severity.ERROR, "", pattern="$X")
    verified = rule(
        "verified", "SELECT file, line FROM t", verification=Verification.EXACT_CLONE
    )

    findings, diagnostics = run_sql_rules([pattern, verified], conn)

    assert findings == []
    assert diagnostics == [
        Diagnostic(
            "verified", "<sql rule>", "source verification requires a repository root"
        )
    ]


def test_duplicate_location_names_remain_available_as_evidence():
    conn = connection()
    item = rule(
        "duplicate",
        "SELECT file, line, 'alias' AS file FROM t LIMIT 1",
        message="{file}",
    )

    findings, diagnostics = run_sql_rules([item], conn)

    assert diagnostics == []
    assert findings[0].location.file == "a.rs"
    assert findings[0].evidence == {"file": "alias"}
    assert findings[0].message == "alias"


def test_repo_sql_honors_unconfigured_dependency_boundary():
    conn = connection()
    item = rule(
        "boundary",
        "SELECT file, line FROM t",
        verification=Verification.DEPENDENCY_BOUNDARY,
    )

    findings, diagnostics = run_sql_rules_in_repo(
        [item], conn, Path("."), FakeProvider()
    )

    assert findings == []
    assert diagnostics == []


def test_repo_sql_reports_unexpected_clone_verification_failure(
    tmp_path: Path, monkeypatch
) -> None:
    from varde_code.rules import sql

    def crash(*_args):
        raise RuntimeError("verification crashed")

    monkeypatch.setattr(sql, "verify_clones", crash)
    conn = connection()
    item = rule(
        "clone",
        "SELECT file, line FROM t",
        verification=Verification.EXACT_CLONE,
    )

    findings, diagnostics = run_sql_rules_in_repo(
        [item], conn, tmp_path, FakeProvider()
    )

    assert findings == []
    assert len(diagnostics) == 1
    assert diagnostics[0].reason == (
        "clone verification failed: RuntimeError: verification crashed"
    )


def test_repo_sql_reports_malformed_dependency_boundary_prefix():
    conn = connection()
    item = rule(
        "boundary",
        "SELECT file, line FROM t",
        verification=Verification.DEPENDENCY_BOUNDARY,
        strings={"source_prefix": "src//bad", "target_prefix": "lib"},
    )

    findings, diagnostics = run_sql_rules_in_repo(
        [item], conn, Path("."), FakeProvider()
    )

    assert findings == []
    assert len(diagnostics) == 1
    assert diagnostics[0].reason == (
        "source_prefix must be a normalized relative directory or '.'; "
        "configure both prefixes"
    )


def test_dependency_facts_aggregates_rust_builder_with_explicit_provider(tmp_path):
    source_path = tmp_path / "src" / "lib.rs"
    source_path.parent.mkdir()
    source_path.write_text("#[cfg(unix)]\nmod absent;\n", encoding="utf-8")
    conn = sqlite3.connect(":memory:")
    conn.execute(
        (
            "CREATE TABLE files (id INTEGER, path TEXT, is_test_path INTEGER, "
            "is_tooling_path INTEGER)"
        )
    )
    conn.execute(
        (
            "CREATE TABLE entities (id INTEGER, file_id INTEGER, kind INTEGER, "
            "name TEXT, body_shape TEXT)"
        )
    )
    conn.execute(
        (
            "CREATE TABLE resolved_edges (id INTEGER, kind INTEGER, "
            "from_file_id INTEGER, from_entity_id INTEGER, to_file_id INTEGER, "
            "resolved INTEGER)"
        )
    )
    conn.execute("INSERT INTO files VALUES (1, 'src/lib.rs', 0, 0)")
    conn.execute("INSERT INTO entities VALUES (7, 1, 9, 'mod absent', NULL)")
    provider = FakeProvider(
        [Entity(EntityKind.IMPORT, "mod absent", 1, Span(15, 25, 2, 0, 2, 10))]
    )

    prepare(conn, tmp_path, provider)

    assert provider.calls == [(source_path, "rust")]
    assert conn.execute("SELECT COUNT(*) FROM temp.dependency_facts").fetchone() == (0,)
