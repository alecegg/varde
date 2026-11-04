"""Run the inline pattern and SQL tests declared by rules."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from typing import Any, Never

from varde_code import ApiError
from varde_code.parse import SUPPORTED_LANGUAGES, language_for_path, language_from_name
from varde_code.rules.finding import Finding
from varde_code.rules.model import Rule, RuleKind, TestCase
from varde_code.rules.pattern import (
    _has_pattern_error,
    _match_source,
    apply_constraints,
)
from varde_code.rules.rewrite import substitute_with_source
from varde_code.rules.sql import run_sql_rules_in_repo
from varde_code.seams import ExtractionProvider


def _raise(error: Exception) -> Never:
    raise error


class TestResult:
    """Outcome of one declared rule test."""

    __test__ = False

    def __init__(
        self, rule_id: str, test_name: str, passed: bool, detail: str | None = None
    ):
        self.rule_id = rule_id
        self.test_name = test_name
        self.passed = passed
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        result = {
            "rule_id": self.rule_id,
            "test_name": self.test_name,
            "pass": self.passed,
        }
        if self.detail is not None:
            result["detail"] = self.detail
        return result


def _pass(rule: Rule, case: TestCase) -> TestResult:
    return TestResult(rule.id, case.name, True)


def _fail(rule: Rule, case: TestCase, detail: str) -> TestResult:
    return TestResult(rule.id, case.name, False, detail)


def run_pattern_rule_tests(rule: Rule) -> list[TestResult]:
    if rule.kind is not RuleKind.PATTERN or rule.test is None:
        return []
    return [_run_pattern_case(rule, case) for case in rule.test]


def _run_pattern_case(rule: Rule, case: TestCase) -> TestResult:
    if rule.pattern is None:
        return _fail(rule, case, "rule kind=pattern is missing its `pattern` field")
    for snippet in case.valid or []:
        try:
            matches = _match_snippet(rule, snippet)
        except (ApiError, ValueError, OSError) as error:
            return _fail(
                rule,
                case,
                f"valid snippet {snippet} failed to evaluate: {_error_message(error)}",
            )
        if matches:
            return _fail(
                rule,
                case,
                (
                    f"valid snippet unexpectedly matched:\nsnippet: {snippet}\n"
                    f"expected match count: 0\nactual match count: {len(matches)}"
                ),
            )
    for snippet in case.invalid or []:
        try:
            matches = _match_snippet(rule, snippet)
        except (ApiError, ValueError, OSError) as error:
            return _fail(
                rule,
                case,
                (
                    f"invalid snippet {snippet} failed to evaluate: "
                    f"{_error_message(error)}"
                ),
            )
        if not matches:
            return _fail(
                rule,
                case,
                (
                    f"invalid snippet unexpectedly had zero matches:\n"
                    f"snippet: {snippet}\nexpected match count: >=1\n"
                    "actual match count: 0"
                ),
            )
    if case.expect_rewrite is not None:
        if rule.rewrite is None:
            return _fail(
                rule,
                case,
                "expect_rewrite entries declared but rule has no `rewrite` field",
            )
        for snippet, expected in case.expect_rewrite.items():
            try:
                matches = _match_snippet(rule, snippet)
            except (ApiError, ValueError, OSError) as error:
                return _fail(
                    rule,
                    case,
                    (
                        f"expect_rewrite snippet {snippet} failed to evaluate: "
                        f"{_error_message(error)}"
                    ),
                )
            if not matches:
                return _fail(
                    rule,
                    case,
                    (
                        "expect_rewrite snippet did not match:\n"
                        f"snippet: {snippet}\nexpected output: {expected}\n"
                        "actual: no match"
                    ),
                )
            actual = substitute_with_source(
                rule.rewrite, matches[0].get("captures"), snippet
            )
            if actual != expected:
                return _fail(
                    rule,
                    case,
                    (
                        "expect_rewrite output mismatch:\n"
                        f"snippet: {snippet}\nexpected output: {expected}\n"
                        f"actual output: {actual}"
                    ),
                )
    return _pass(rule, case)


def _error_message(error: Exception) -> str:
    return error.message if isinstance(error, ApiError) else str(error)


def _match_snippet(rule: Rule, snippet: str) -> list[dict[str, Any]]:
    if rule.pattern is None:
        raise ApiError(
            "invalid_input", "rule kind=pattern is missing its `pattern` field"
        )
    languages = rule.languages or list(SUPPORTED_LANGUAGES)
    results: list[dict[str, Any]] = []
    evaluated = False
    last_error: Exception | None = None
    for requested in languages:
        language = language_from_name(requested)
        if language is None:
            continue
        try:
            if _has_pattern_error(rule.pattern, language):
                _raise(ValueError("pattern failed to parse"))
            rows = _match_source(snippet, rule.pattern, language)
        except (ApiError, ValueError) as error:
            last_error = error
            continue
        evaluated = True
        results.extend(apply_constraints(rows, rule.constraints or {}))
    if not evaluated:
        if last_error:
            raise ApiError("invalid_input", str(last_error)) from last_error
        raise ApiError("invalid_input", "rule did not target a supported language")
    return results


def run_sql_rule_tests(rule: Rule, provider: ExtractionProvider) -> list[TestResult]:
    if rule.kind is not RuleKind.SQL or rule.test is None:
        return []
    return [_run_sql_case(rule, case, provider) for case in rule.test]


def _finding_row(finding: Finding) -> dict[str, Any]:
    row = {"file": finding.location.file, "line": finding.location.span.start_line}
    if isinstance(finding.evidence, dict):
        row.update(finding.evidence)
    return row


def _compare_rows(
    expected: list[dict[str, Any]], actual: list[dict[str, Any]]
) -> str | None:
    remaining = list(actual)
    missing = []
    for row in expected:
        try:
            remaining.remove(row)
        except ValueError:
            missing.append(row)
    if not missing and not remaining:
        return None
    detail = (
        "row mismatch (order-insensitive multiset comparison):\n"
        f"expected rows: {expected!r}\nactual rows: {actual!r}"
    )
    if missing:
        detail += f"\nmissing expected rows (no matching actual row): {missing!r}"
        actual_columns = {key for row in actual for key in row}
        for row in missing:
            unknown = set(row) - actual_columns
            if unknown:
                detail += (
                    "\nexpected row has keys not present in any actual query result "
                    f"column: {sorted(unknown)!r} (available columns: "
                    f"{sorted(actual_columns)!r})"
                )
    if remaining:
        detail += f"\nunexpected extra actual rows: {remaining!r}"
    return detail


def _run_sql_case(
    rule: Rule, case: TestCase, provider: ExtractionProvider
) -> TestResult:
    if case.fixture is None:
        return _fail(rule, case, "sql test case is missing its `fixture` table")
    if case.expect_rows is None:
        return _fail(rule, case, "sql test case is missing its `expect_rows` rows")
    try:
        actual = _run_fixture(rule, case.fixture, provider)
    except Exception as error:
        return _fail(rule, case, str(error))
    detail = _compare_rows(case.expect_rows, actual)
    return _pass(rule, case) if detail is None else _fail(rule, case, detail)


def _run_fixture(
    rule: Rule, files: dict[str, str], provider: ExtractionProvider
) -> list[dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="varde-sql-test-") as directory:
        root = Path(directory)
        db = sqlite3.connect(":memory:")
        try:
            _index_fixture(db, root, files, provider)
            findings, diagnostics = run_sql_rules_in_repo([rule], db, root, provider)
            diagnostic = next(
                (item for item in diagnostics if item.rule_id == rule.id), None
            )
            if diagnostic:
                _raise(ValueError(f"query execution failed: {diagnostic.reason}"))
            return [_finding_row(finding) for finding in findings]
        except Exception as error:
            raise ValueError(f"running rule query failed: {error}") from error
        finally:
            db.close()


def _index_fixture(
    conn: sqlite3.Connection,
    root: Path,
    files: dict[str, str],
    provider: ExtractionProvider,
) -> None:
    conn.executescript(
        """
        CREATE TABLE files (id INTEGER PRIMARY KEY, path TEXT,
            is_test_path INTEGER DEFAULT 0, is_tooling_path INTEGER DEFAULT 0);
        CREATE TABLE entities (id INTEGER PRIMARY KEY, file_id INTEGER,
            kind INTEGER, name TEXT,
            start_byte INTEGER, end_byte INTEGER, start_line INTEGER, start_col INTEGER,
            end_line INTEGER, end_col INTEGER, is_async INTEGER, body_shape TEXT);
        """
    )
    entity_id = 0
    for file_id, (relative, source) in enumerate(files.items(), start=1):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        conn.execute("INSERT INTO files(id,path) VALUES (?,?)", (file_id, relative))
        language = language_for_path(path)
        if language is None:
            continue
        extracted = provider.extract(path, source, language)
        for entity in extracted.entities:
            entity_id += 1
            span = entity.span
            conn.execute(
                """INSERT INTO entities(
                    id,file_id,kind,name,start_byte,end_byte,start_line,start_col,
                    end_line,end_col,is_async,body_shape
                )
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    entity_id,
                    file_id,
                    int(entity.kind),
                    entity.name,
                    span.start_byte,
                    span.end_byte,
                    span.start_line,
                    span.start_col,
                    span.end_line,
                    span.end_col,
                    int(entity.is_async or False),
                    entity.body_shape,
                ),
            )
    conn.commit()
