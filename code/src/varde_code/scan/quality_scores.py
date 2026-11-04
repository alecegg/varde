"""Materialize the TEMP ``quality_scores`` table for scan-time quality rules.

Three layers, kept apart: ``compute_scope_score`` runs the quality pass and the
scorer, ``build_quality_rows`` turns a score into plain rows (pure), and
``write_quality_scores`` creates the TEMP table on a connection. Nothing here is
wired into ``scan_repo`` yet.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import astuple, dataclass
from pathlib import Path
from typing import Any

from varde_code.quality_pass.pass_ import read_facts, read_measures, run_quality_pass
from varde_code.quality_score import score_scope
from varde_code.quality_score.calibration import Calibration
from varde_code.quality_score.scoring import ScopeScore

REPO_SCOPE = "repo"
# A language the calibration lacks is scored under its nearest calibrated language.
LANGUAGE_FALLBACKS = {"tsx": "typescript"}
UNPARSED_DIAGNOSTIC = "parse contains errors"
UNPARSED_REASON = "unparsed: syntax error, partial extract kept"
_MEASURE_KEYS = ("depth", "fan_out", "tree_size", "callers_in_module", "fragment_scope")

COLUMNS = (
    "scope",
    "level",
    "path",
    "language",
    "function_id",
    "line",
    "score",
    "tokens",
    "debt",
    "exempt",
    "exempt_reason",
    "diagnostics",
    "calibration_id",
    "metric_version",
)
_CREATE = (
    "CREATE TEMP TABLE quality_scores ("
    "scope TEXT NOT NULL, level TEXT NOT NULL, path TEXT, language TEXT, "
    "function_id TEXT, line INTEGER, score INTEGER, tokens INTEGER, debt INTEGER, "
    "exempt INTEGER NOT NULL, exempt_reason TEXT, diagnostics TEXT NOT NULL, "
    "calibration_id TEXT NOT NULL, metric_version TEXT NOT NULL)"
)
_INSERT = "INSERT INTO quality_scores VALUES (" + ", ".join("?" * len(COLUMNS)) + ")"  # noqa: S608 - Placeholders only.


@dataclass(frozen=True)
class QualityRow:
    """One flat evidence row; ``score`` is micro-points (0 to 100_000_000)."""

    scope: str
    level: str
    path: str | None
    language: str | None
    function_id: str | None
    line: int | None
    score: int | None
    tokens: int | None
    debt: int | None
    exempt: bool
    exempt_reason: str | None
    diagnostics: str
    calibration_id: str
    metric_version: str


def merge_measures(root: str | Path) -> list[dict[str, Any]]:
    """Return stored facts with their L3 measures merged in, ready for scoring."""
    measures = {record["path"]: record for record in read_measures(root)}
    records = []
    for fact in read_facts(root):
        measure = measures.get(fact["path"])
        if measure is None:
            continue
        per_function = measure["functions"]
        functions = [
            {**fn, **{key: per_function[fn["id"]][key] for key in _MEASURE_KEYS}}
            for fn in fact["functions"]
        ]
        records.append(
            {
                **fact,
                "functions": functions,
                "module": measure["module"],
                "structure_confidence": measure["structure_confidence"],
            }
        )
    return records


def is_unparsed(record: Mapping[str, Any]) -> bool:
    """Whether the persisted facts say the parser reported a syntax error."""
    return UNPARSED_DIAGNOSTIC in record.get("diagnostics", [])


def unparsed_row(record: Mapping[str, Any], scope_name: str, stamp) -> QualityRow:
    """A syntax-error file row: its tokens count as unscored, never scored."""
    return QualityRow(
        scope_name, "file", record["path"], record.get("language"), None, None,
        None, record.get("tokens") or 0, None, False, UNPARSED_REASON,
        "; ".join(record.get("diagnostics", [])), *stamp,
    )  # fmt: skip


def calibrated_records(
    records: Iterable[dict[str, Any]], calibration: Calibration
) -> list[dict[str, Any]]:
    """Alias languages the calibration lacks to their fallback, leaving others as-is."""
    return [_aliased(record, calibration) for record in records]


def _aliased(record: dict[str, Any], calibration: Calibration) -> dict[str, Any]:
    language = record.get("language")
    if language is None:
        return record
    fallback = LANGUAGE_FALLBACKS.get(language)
    if language in calibration.languages or fallback not in calibration.languages:
        return record
    return {**record, "language": fallback}


def build_quality_rows(
    scope: ScopeScore,
    records: Iterable[dict[str, Any]],
    calibration: Calibration,
    *,
    scope_name: str = REPO_SCOPE,
) -> list[QualityRow]:
    """Return scope, file and function rows in deterministic order (pure)."""
    facts = {record["path"]: record for record in records}
    stamp = (calibration.id, calibration.formula)
    rows = [_scope_row(scope, scope_name, stamp)]
    for file in sorted(scope.files, key=lambda f: f.path):
        fact = facts.get(file.path, {})
        language = fact.get("language", file.language)
        diagnostics = "; ".join(fact.get("diagnostics", []))
        rows.append(_file_row(file, scope_name, language, diagnostics, stamp))
        functions = sorted(file.functions, key=lambda f: (f.line or 0, f.id))
        rows.extend(_function_row(fn, scope_name, language, stamp) for fn in functions)
    return rows


def _scope_row(scope: ScopeScore, name: str, stamp: tuple[str, str]) -> QualityRow:
    score = scope.score.numerator // scope.score.denominator if scope.score else None
    return QualityRow(
        name, "scope", None, None, None, None, score, scope.tokens, scope.debt,
        False, None, "", *stamp,
    )  # fmt: skip


def _file_row(file, name, language, diagnostics, stamp) -> QualityRow:
    exempt = file.exempt_from_floor
    reason = file.floor_exemption_reason if exempt else file.excluded
    return QualityRow(
        name, "file", file.path, language, None, None,
        None if file.not_applicable else file.gate_score,
        file.tokens, file.debt, exempt, reason, diagnostics, *stamp,
    )  # fmt: skip


def _function_row(fn, name, language, stamp) -> QualityRow:
    return QualityRow(
        name, "function", fn.path, language, fn.id, fn.line, None, None, fn.debt,
        fn.exempt_role is not None, fn.exempt_role, "", *stamp,
    )  # fmt: skip


def write_quality_scores(conn: sqlite3.Connection, rows: Iterable[QualityRow]) -> None:
    """Create the TEMP ``quality_scores`` table (replacing any prior) and fill it."""
    conn.execute("DROP TABLE IF EXISTS temp.quality_scores")
    conn.execute(_CREATE)
    conn.executemany(_INSERT, (astuple(row) for row in rows))


def compute_scope_score(
    root: str | Path, calibration: Calibration, *, workers: int | None = None
) -> tuple[ScopeScore, list[dict[str, Any]]]:
    """Run the quality pass; return the score and the records with own languages."""
    run_quality_pass(root, workers=workers)
    records = merge_measures(root)
    return score_scope(calibrated_records(records, calibration), calibration), records


def split_records_by_scope(
    records: Iterable[dict[str, Any]], scope_of: Mapping[str, str] | None
) -> dict[str, list[dict[str, Any]]]:
    """Group records by scope name (pure); the repo scope always exists.

    A path missing from ``scope_of`` belongs to the repo scope.
    """
    groups: dict[str, list[dict[str, Any]]] = {REPO_SCOPE: []}
    for record in records:
        name = (scope_of or {}).get(record["path"], REPO_SCOPE)
        groups.setdefault(name, []).append(record)
    return groups


def materialize_quality_scores(
    conn: sqlite3.Connection,
    root: str | Path,
    calibration: Calibration,
    *,
    workers: int | None = None,
    scope_of: Mapping[str, str] | None = None,
) -> list[QualityRow]:
    """Score the repo and write ``quality_scores`` onto ``conn``; return the rows.

    ``scope_of`` maps a path to its scope name (repo, tests, tooling); each scope
    is scored on its own so test and tooling code never dilute the repo mean.
    Syntax-error files are not scored; they become unscored file rows.
    """
    run_quality_pass(root, workers=workers)
    records = merge_measures(root)
    rows: list[QualityRow] = []
    for name, group in sorted(split_records_by_scope(records, scope_of).items()):
        parsed = [record for record in group if not is_unparsed(record)]
        scored = score_scope(calibrated_records(parsed, calibration), calibration)
        rows.extend(build_quality_rows(scored, parsed, calibration, scope_name=name))
        stamp = (calibration.id, calibration.formula)
        rows.extend(
            unparsed_row(record, name, stamp)
            for record in sorted(group, key=lambda r: r["path"])
            if is_unparsed(record)
        )
    write_quality_scores(conn, rows)
    return rows


__all__ = [
    "COLUMNS",
    "QualityRow",
    "build_quality_rows",
    "calibrated_records",
    "compute_scope_score",
    "materialize_quality_scores",
    "merge_measures",
    "split_records_by_scope",
    "write_quality_scores",
]
