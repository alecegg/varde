"""Execute SQL rules against an already-open, read-only SQLite index."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from varde_code.model import Span, saturating_u32
from varde_code.rules.model import Diagnostic, Rule, RuleKind, Severity

_LOCATION_COLUMNS = {
    "file",
    "line",
    "start_byte",
    "end_byte",
    "start_col",
    "end_line",
    "end_col",
}


@dataclass(frozen=True)
class Location:
    file: str
    span: Span


@dataclass(frozen=True)
class Finding:
    id: str
    rule_id: str
    severity: Severity
    message: str
    location: Location
    evidence: dict[str, Any]
    remediation: str | None
    certainty: None = None
    agent_instructions: str | None = None


def finding_id(rule_id: str, file: str, span: Span) -> str:
    """Match Rust's FNV-1a ID over rule, file, and byte span."""
    value = 0xCBF29CE484222325
    for part in (rule_id, file, str(span.start_byte), str(span.end_byte)):
        for byte in part.encode():
            value = ((value ^ byte) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
        value = (value * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{value:016x}"


def run_sql_rules(
    rules: list[Rule], conn: sqlite3.Connection
) -> tuple[list[Finding], list[Diagnostic]]:
    """Run SQL rules independently; report malformed rules and continue."""
    findings: list[Finding] = []
    diagnostics: list[Diagnostic] = []
    for rule in rules:
        if rule.kind is not RuleKind.SQL:
            continue
        if rule.verification is not None:
            diagnostics.append(
                _diagnostic(rule, "source verification requires a repository root")
            )
            continue
        if rule.query is None:
            diagnostics.append(
                _diagnostic(rule, "rule kind=sql is missing its `query` field")
            )
            continue
        try:
            findings.extend(_run_rule(rule, conn))
        except sqlite3.Error as error:
            reason = f"SQL prepare failed: {error}"
            diagnostics.append(_diagnostic(rule, reason))
    return findings, diagnostics


def _run_rule(rule: Rule, conn: sqlite3.Connection) -> list[Finding]:
    query = rule.query
    if query is None:
        raise ValueError("rule query is required")
    columns = _query_columns(conn, query, _params(rule, query))
    names = [column[0] for column in columns]
    if "file" not in names or "line" not in names:
        raise sqlite3.OperationalError(
            "query must select a `file` column and a `line` column"
        )
    cursor = conn.execute(query, _params(rule, query))
    results = []
    for record in cursor:
        row = dict(zip(names, record, strict=True))
        file = str(row["file"])
        line = saturating_u32(int(row["line"]))
        end_line = row.get("end_line")
        span = Span(
            start_byte=saturating_u32(int(row.get("start_byte") or 0)),
            end_byte=saturating_u32(int(row.get("end_byte") or 0)),
            start_line=line,
            start_col=saturating_u32(int(row.get("start_col") or 0)),
            end_line=saturating_u32(int(end_line) if end_line is not None else line),
            end_col=saturating_u32(int(row.get("end_col") or 0)),
        )
        evidence = {
            key: _json_value(value)
            for key, value in row.items()
            if key not in _LOCATION_COLUMNS
        }
        message = _render_message(rule.message, evidence)
        results.append(
            Finding(
                id=finding_id(rule.id, file, span),
                rule_id=rule.id,
                severity=rule.severity,
                message=message,
                location=Location(file, span),
                evidence=evidence,
                remediation=rule.remediation,
                agent_instructions=rule.fix,
            )
        )
    return results


def _query_columns(
    conn: sqlite3.Connection, query: str, params: dict[str, Any]
) -> list[tuple[Any, ...]]:
    cursor = conn.execute(query, params)
    columns = cursor.description
    cursor.close()
    if columns is None:
        raise sqlite3.OperationalError("SQL rule must return rows")
    return [tuple(column) for column in columns]


def _params(rule: Rule, query: str) -> dict[str, Any]:
    from varde_code.rules.sql import _named_parameters

    declared = _named_parameters(query)
    values: dict[str, Any] = dict.fromkeys(declared)
    values.update(
        {
            key: value
            for key, value in (rule.thresholds or {}).items()
            if key in declared
        }
    )
    values.update(
        {key: value for key, value in (rule.strings or {}).items() if key in declared}
    )
    return values


def _diagnostic(rule: Rule, reason: str) -> Diagnostic:
    return Diagnostic(rule.id, "<sql rule>", reason)


def _json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _render_message(template: str, evidence: dict[str, Any]) -> str:
    from varde_code.rules.sql import _render_message as render

    return render(template, evidence)
