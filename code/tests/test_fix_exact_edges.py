from __future__ import annotations

import sqlite3

from varde_code.index.persist.entities import FileIds
from varde_code.index.persist.metrics import write_function_metrics
from varde_code.index.resolve.calls import resolve_calls
from varde_code.model import (
    EdgeKind,
    Entity,
    EntityKind,
    ExtractOutput,
    Span,
    SymbolKind,
)


def test_persisted_complexity_uses_nested_decision_metrics():
    connection = sqlite3.connect(":memory:")
    connection.execute("""
        CREATE TABLE function_metrics (
            file_id INTEGER, identity TEXT, name TEXT, owner_type TEXT,
            start_byte INTEGER, end_byte INTEGER, start_line INTEGER, start_col INTEGER,
            end_line INTEGER, end_col INTEGER, cyclomatic INTEGER, cognitive INTEGER,
            max_nesting INTEGER, line_span INTEGER, byte_size INTEGER, confidence TEXT,
            confidence_reasons TEXT, metric_version INTEGER
        )
    """)
    output = ExtractOutput(
        files=["src/main.py"],
        entities=[
            _entity(EntityKind.FUNCTION, "work", 0, 100),
            _entity(EntityKind.CONTROL_FLOW, "if_statement", 10, 90),
            _entity(EntityKind.CONTROL_FLOW, "if_statement", 20, 70),
            _entity(EntityKind.CONTROL_FLOW, "if_statement", 30, 60),
        ],
    )

    write_function_metrics(connection, [output], FileIds([9], [0]))

    row = connection.execute(
        "SELECT file_id,cyclomatic,cognitive,max_nesting,confidence,confidence_reasons "
        "FROM function_metrics"
    ).fetchone()
    assert row == (9, 4, 6, 2, "high", "[]")


def test_resolves_calls_through_imported_python_package_submodule():
    entities = [
        {
            "kind": EntityKind.IMPORT,
            "name": "varde_core/redact",
            "file_id": 0,
            "start_byte": 0,
            "end_byte": 20,
        },
        {"kind": EntityKind.CALL, "name": "values.from_dotenv", "file_id": 0},
        {"kind": EntityKind.FUNCTION, "name": "from_dotenv", "file_id": 2},
    ]
    imports = [
        {"from": 0, "to": {"id": 1}, "kind": EdgeKind.IMPORT.as_str(), "resolved": True}
    ]
    symbols = [
        {
            "kind": SymbolKind.REFERENCE,
            "name": "values",
            "file_id": 0,
            "start_byte": 10,
            "end_byte": 16,
        }
    ]

    edges = resolve_calls(
        entities,
        imports,
        [
            "varde_core/redact/tests/test_redact.py",
            "varde_core/redact/__init__.py",
            "varde_core/redact/values.py",
        ],
        symbols,
    )

    assert edges[0]["to"] == {"target": "entity", "id": 2}


def _entity(kind: EntityKind, name: str, start: int, end: int) -> Entity:
    return Entity(
        kind=kind,
        name=name,
        file_id=0,
        span=Span(start, end, start // 10 + 1, 0, end // 10 + 1, 0),
    )
