from __future__ import annotations

import sqlite3

from varde_code.model import Entity, EntityKind, ExtractOutput, Span
from varde_code.rules.engine import run_rules
from varde_code.rules.model import Rule, RuleKind, Severity, Verification


class FakeProvider:
    def __init__(self, entities=None):
        self.entities = entities or []
        self.calls = []

    def extract(self, path, source, language):
        self.calls.append((path, language))
        return ExtractOutput(entities=self.entities)


def _rule(rule_id: str, kind: RuleKind, severity: Severity, **fields) -> Rule:
    return Rule(id=rule_id, kind=kind, severity=severity, message=rule_id, **fields)


def test_engine_runs_pattern_then_sql_and_preserves_rule_severity_and_order(tmp_path):
    (tmp_path / "sample.rs").write_text(
        "fn main() { alpha(1); beta(2); }", encoding="utf-8"
    )
    conn = sqlite3.connect(":memory:")
    conn.execute(
        (  # noqa: UP034 - grouping keeps adjacent SQL literals clear
            "CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT, is_test_path "
            "INTEGER, is_tooling_path INTEGER)"
        )
    )
    conn.execute(
        (  # noqa: UP034 - grouping keeps adjacent SQL literals clear
            "CREATE TABLE entities (file_id INTEGER, kind INTEGER, start_byte INTEGER, "
            "end_byte INTEGER, name TEXT, is_async INTEGER)"
        )
    )
    conn.execute("CREATE TABLE sql_hits (file TEXT, line INTEGER, label TEXT)")
    conn.executemany(
        "INSERT INTO sql_hits VALUES (?, ?, ?)",
        [("z.rs", 3, "first"), ("a.rs", 1, "second")],
    )
    rules = [
        _rule(
            "sql-first-in-input",
            RuleKind.SQL,
            Severity.ERROR,
            query="SELECT file, line, label FROM sql_hits",
        ),
        _rule(
            "pattern-one",
            RuleKind.PATTERN,
            Severity.INFO,
            pattern="alpha($VALUE)",
            languages=["rust"],
        ),
        _rule(
            "sql-second-in-input",
            RuleKind.SQL,
            Severity.WARNING,
            query="SELECT file, line, label FROM sql_hits WHERE label = 'second'",
        ),
        _rule(
            "pattern-two",
            RuleKind.PATTERN,
            Severity.WARNING,
            pattern="beta($VALUE)",
            languages=["rust"],
        ),
    ]

    findings, diagnostics = run_rules(rules, tmp_path, conn, FakeProvider())

    assert diagnostics == []
    assert [finding.rule_id for finding in findings] == [
        "pattern-one",
        "pattern-two",
        "sql-first-in-input",
        "sql-first-in-input",
        "sql-second-in-input",
    ]
    assert [finding.severity for finding in findings] == [
        Severity.INFO,
        Severity.WARNING,
        Severity.ERROR,
        Severity.ERROR,
        Severity.WARNING,
    ]
    assert [finding.location.file for finding in findings[2:4]] == ["z.rs", "a.rs"]


def test_structural_policy_budget_boundary_and_file_scoping(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        (  # noqa: UP034 - grouping keeps adjacent SQL literals clear
            "CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT, is_test_path "
            "INTEGER, is_tooling_path INTEGER)"
        )
    )
    conn.execute(
        (  # noqa: UP034 - grouping keeps adjacent SQL literals clear
            "CREATE TABLE entities (file_id INTEGER, kind INTEGER, name TEXT, "
            "is_async INTEGER, start_byte INTEGER, end_byte INTEGER, owner_type TEXT)"
        )
    )
    conn.executemany(
        "INSERT INTO files VALUES (?, ?, ?, ?)",
        [
            (1, "src/boundary.ts", 0, 0),
            (2, "src/positive.ts", 0, 0),
            (3, "tests/generated.ts", 1, 0),
            (4, "scripts/generated.ts", 0, 1),
        ],
    )
    conn.executemany(
        "INSERT INTO entities (file_id, kind, owner_type) VALUES (?, ?, ?)",
        [(1, 1, "Boundary")]
        + [(1, 0, "Boundary")] * 15
        + [(2, 1, "Positive")]
        + [(2, 0, "Positive")] * 16
        + [(3, 1, "Generated")]
        + [(3, 0, "Generated")] * 20
        + [(4, 1, "Tooling")]
        + [(4, 0, "Tooling")] * 20,
    )
    rule = _rule(
        "fat-interface",
        RuleKind.SQL,
        Severity.WARNING,
        query="""
            SELECT f.path AS file, 1 AS line, c.owner_type AS class_name,
                   COUNT(*) AS member_count, :budget AS threshold
            FROM entities c JOIN files f ON f.id = c.file_id
            WHERE c.kind = 0 AND f.is_test_path = 0 AND f.is_tooling_path = 0
            GROUP BY f.id, c.owner_type
            HAVING COUNT(*) > :budget
        """,
        thresholds={"budget": 15},
    )

    findings, diagnostics = run_rules([rule], tmp_path, conn, FakeProvider())

    assert diagnostics == []
    assert len(findings) == 1
    assert findings[0].location.file == "src/positive.ts"
    assert findings[0].evidence == {
        "class_name": "Positive",
        "member_count": 16,
        "threshold": 15,
    }


def test_engine_threads_provider_to_dependency_fact_sql(tmp_path):
    source = tmp_path / "src" / "lib.rs"
    source.parent.mkdir()
    source.write_text("#[cfg(unix)]\nmod absent;\n", encoding="utf-8")
    conn = sqlite3.connect(":memory:")
    conn.execute(
        (  # noqa: UP034 - grouping keeps adjacent SQL literals clear
            "CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT, is_test_path "
            "INTEGER, is_tooling_path INTEGER)"
        )
    )
    conn.execute(
        (  # noqa: UP034 - grouping keeps adjacent SQL literals clear
            "CREATE TABLE entities (id INTEGER, file_id INTEGER, kind INTEGER, "
            "name TEXT, body_shape TEXT, is_async INTEGER, start_byte INTEGER, "
            "end_byte INTEGER, owner_type TEXT)"
        )
    )
    conn.execute(
        (  # noqa: UP034 - grouping keeps adjacent SQL literals clear
            "CREATE TABLE resolved_edges (id INTEGER, kind INTEGER, from_file_id "
            "INTEGER, from_entity_id INTEGER, to_file_id INTEGER, resolved INTEGER)"
        )
    )
    conn.execute("INSERT INTO files VALUES (1, 'src/lib.rs', 0, 0)")
    conn.execute(
        (  # noqa: UP034 - grouping keeps adjacent SQL literals clear
            "INSERT INTO entities (id, file_id, kind, name, body_shape) "
            "VALUES (7, 1, 9, 'mod absent', NULL)"
        )
    )
    provider = FakeProvider(
        [Entity(EntityKind.IMPORT, "mod absent", 1, Span(15, 25, 2, 0, 2, 10))]
    )
    policy = _rule(
        "dependency-check",
        RuleKind.SQL,
        Severity.ERROR,
        verification=Verification.DEPENDENCY_FACTS,
        query="SELECT from_unit AS file, 1 AS line FROM dependency_facts WHERE 0",
    )

    findings, diagnostics = run_rules([policy], tmp_path, conn, provider)

    assert findings == []
    assert diagnostics == []
    assert provider.calls == [(source, "rust")]
