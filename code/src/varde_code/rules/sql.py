"""Execute SQL rules against an open code index connection."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Never

from varde_code.model import Span
from varde_code.rules.clone_verification import verify as verify_clones
from varde_code.rules.finding import Finding, Location, finding_id
from varde_code.rules.model import (
    Diagnostic,
    Rule,
    RuleKind,
    Verification,
    boundary_configured,
)
from varde_code.seams import ExtractionProvider


def _raise(error: Exception) -> Never:
    raise error


def run_sql_rules(
    rules: list[Rule] | tuple[Rule, ...], conn: sqlite3.Connection
) -> tuple[list[Finding], list[Diagnostic]]:
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
        try:
            findings.extend(_run_rule(rule, conn))
        except (sqlite3.Error, ValueError, TypeError, OverflowError) as error:
            diagnostics.append(_diagnostic(rule, str(error)))
    return findings, diagnostics


def run_sql_rules_in_repo(
    rules: list[Rule] | tuple[Rule, ...],
    conn: sqlite3.Connection,
    repo_root: Path,
    provider: ExtractionProvider,
) -> tuple[list[Finding], list[Diagnostic]]:
    from varde_code.rules.dependency_facts import prepare

    needs_facts = any(
        rule.verification
        in (Verification.DEPENDENCY_FACTS, Verification.DEPENDENCY_BOUNDARY)
        and _boundary_configured(rule) is True
        for rule in rules
    )
    fact_error: str | None = None
    if needs_facts:
        try:
            prepare(conn, repo_root, provider)
        except (OSError, sqlite3.Error, ValueError) as error:
            fact_error = str(error)

    findings: list[Finding] = []
    diagnostics: list[Diagnostic] = []
    for rule in rules:
        if rule.kind is not RuleKind.SQL:
            continue
        configured = _boundary_configured(rule)
        if isinstance(configured, str):
            diagnostics.append(_diagnostic(rule, configured))
            continue
        if not configured:
            continue
        if (
            rule.verification
            in (Verification.DEPENDENCY_FACTS, Verification.DEPENDENCY_BOUNDARY)
            and fact_error
        ):
            diagnostics.append(
                _diagnostic(rule, f"dependency certification failed: {fact_error}")
            )
            continue
        try:
            candidates = _run_rule(rule, conn)
        except (sqlite3.Error, ValueError, TypeError, OverflowError) as error:
            diagnostics.append(_diagnostic(rule, str(error)))
            continue
        if rule.verification is Verification.EXACT_CLONE:
            try:
                verified, issues = verify_clones(rule, repo_root, candidates)
            except Exception as error:  # noqa: BLE001 - verifier failures must degrade to diagnostics
                diagnostics.append(
                    _diagnostic(
                        rule,
                        f"clone verification failed: {type(error).__name__}: {error}",
                    )
                )
                continue
            findings.extend(verified)
            diagnostics.extend(issues)
        else:
            findings.extend(candidates)
    return findings, diagnostics


_boundary_configured = boundary_configured


def _run_rule(rule: Rule, conn: sqlite3.Connection) -> list[Finding]:
    if rule.query is None:
        raise ValueError("rule kind=sql is missing its `query` field")
    try:
        cursor = conn.execute(rule.query, _params(rule, rule.query))
    except sqlite3.Error as error:
        raise ValueError(f"SQL prepare failed: {error}") from error
    names = [column[0] for column in cursor.description or ()]
    if "file" not in names or "line" not in names:
        raise ValueError("query must select a `file` column and a `line` column")
    location_indexes = {
        names.index(name)
        for name in (
            "file",
            "line",
            "start_byte",
            "end_byte",
            "start_col",
            "end_line",
            "end_col",
        )
        if name in names
    }
    findings = []
    try:
        rows = cursor.fetchall()
    except sqlite3.Error as error:
        raise ValueError(f"SQL execution failed: {error}") from error
    for values in rows:
        row = dict(zip(names, values, strict=True))
        try:
            file_value = values[names.index("file")]
            if not isinstance(file_value, str):
                _raise(ValueError("file column must contain text"))
            file = file_value
            line = _u32(values[names.index("line")])
            start_byte = _optional_u32(row.get("start_byte"), 0)
            end_byte = _optional_u32(row.get("end_byte"), 0)
            start_col = _optional_u32(row.get("start_col"), 0)
            end_line = _optional_u32(row.get("end_line"), line)
            end_col = _optional_u32(row.get("end_col"), 0)
            span = Span(start_byte, end_byte, line, start_col, end_line, end_col)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError(f"SQL execution failed: {error}") from error
        evidence = {
            name: _json_value(value)
            for index, (name, value) in enumerate(zip(names, values, strict=True))
            if index not in location_indexes
        }
        findings.append(
            Finding(
                id=finding_id(rule.id, file, span),
                rule_id=rule.id,
                severity=rule.severity,
                message=_render_message(rule.message, evidence),
                location=Location(file, span),
                evidence=evidence,
                remediation=rule.remediation,
                certainty=None,
                agent_instructions=rule.fix,
            )
        )
    return findings


def _params(rule: Rule, query: str) -> dict[str, Any]:
    declared = _named_parameters(query)
    values = dict.fromkeys(declared)
    values.update(
        (key, value)
        for key, value in (rule.thresholds or {}).items()
        if key in declared
    )
    values.update(
        (key, value) for key, value in (rule.strings or {}).items() if key in declared
    )
    return values


def _named_parameters(query: str) -> set[str]:
    """Find SQLite named parameters while ignoring quoted text and comments."""
    import re

    clean = list(query)
    index = 0
    while index < len(query):
        if query.startswith("--", index):
            end = query.find("\n", index)
            end = len(query) if end < 0 else end
            clean[index:end] = " " * (end - index)
            index = end
            continue
        if query.startswith("/*", index):
            end = query.find("*/", index + 2)
            end = len(query) if end < 0 else end + 2
            clean[index:end] = " " * (end - index)
            index = end
            continue
        if query[index] in ("'", '"', "`", "["):
            opening = query[index]
            closing = "]" if opening == "[" else opening
            end = index + 1
            while end < len(query):
                if query[end] == closing:
                    if (
                        closing != "]"
                        and end + 1 < len(query)
                        and query[end + 1] == closing
                    ):
                        end += 2
                        continue
                    end += 1
                    break
                end += 1
            clean[index:end] = " " * (end - index)
            index = end
            continue
        index += 1
    return set(re.findall(r"(?<!:):([A-Za-z_][A-Za-z_0-9]*)", "".join(clean)))


def _render_message(template: str, evidence: dict[str, Any]) -> str:
    output = []
    cursor = 0
    while True:
        opening = template.find("{", cursor)
        if opening < 0:
            return "".join((*output, template[cursor:]))
        closing = template.find("}", opening + 1)
        if closing < 0:
            return "".join((*output, template[cursor:]))
        output.append(template[cursor:opening])
        key = template[opening + 1 : closing]
        value = evidence.get(key)
        if isinstance(value, bool):
            output.append("true" if value else "false")
        elif isinstance(value, (str, int, float)):
            output.append(str(value))
        else:
            output.append(template[opening : closing + 1])
        cursor = closing + 1


def _json_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _u32(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("location columns must contain integers")
    return max(0, min(value, 0xFFFFFFFF))


def _optional_u32(value: Any, default: int) -> int:
    return _u32(value) if value is not None else default


def _diagnostic(rule: Rule, reason: str) -> Diagnostic:
    return Diagnostic(rule.id, "<sql rule>", reason)
