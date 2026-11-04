"""Pure helpers and TEMP-table writers that wire quality rules into scan.

Quality rules read three TEMP tables: ``quality_scores`` (scan/quality_scores.py),
``quality_thresholds`` (filled here from the calibration) and
``quality_suppressions`` (created empty here; the suppression task fills it).
"""

from __future__ import annotations

import dataclasses
import sqlite3
from collections.abc import Callable, Iterable

from varde_code.quality_score.calibration import Calibration
from varde_code.rules.finding import Finding
from varde_code.rules.model import Rule, Severity
from varde_code.scan.quality_mode import (
    StateLookup,
    effective_mode,
    language_is_validated,
)
from varde_code.scan.quality_scores import LANGUAGE_FALLBACKS, REPO_SCOPE, QualityRow

QUALITY_PREFIX = "quality-"
GATE_RULE_IDS = frozenset(
    {"quality-file-floor", "quality-function-cap", "quality-scope-mean"}
)
MODE_EVIDENCE_KEY = "quality_mode"
UNSCORED_RULE_ID = "quality-unscored-share"

_CREATE_THRESHOLDS = (
    "CREATE TEMP TABLE quality_thresholds (scope TEXT, language TEXT, "
    "mean_x INTEGER, file_floor_y INTEGER, function_cap INTEGER)"
)
_CREATE_SUPPRESSIONS = (
    "CREATE TEMP TABLE quality_suppressions "
    "(scope TEXT, rule_id TEXT, suppressed INTEGER)"
)

ThresholdRow = tuple[str, str | None, int, int, int]


def is_quality_rule(rule: Rule) -> bool:
    return rule.id.startswith(QUALITY_PREFIX)


def without_quality(rules: list[Rule]) -> list[Rule]:
    return [rule for rule in rules if not is_quality_rule(rule)]


def has_quality_rules(rules: list[Rule]) -> bool:
    return any(is_quality_rule(rule) for rule in rules)


def threshold_rows(
    calibration: Calibration, scope: str = REPO_SCOPE
) -> list[ThresholdRow]:
    """One row per calibrated language plus the scope-mean row (language NULL).

    The scope mean spans languages, so its threshold is the lowest language X:
    the mean rule never fires on a bar stricter than any single language's.
    """
    rows: list[ThresholdRow] = []
    for name in sorted(calibration.languages):
        params = calibration.languages[name].parameters
        rows.append((scope, name, params["X"], params["Y"], params["cap"]))
    if rows:
        lowest = min(row[2] for row in rows)
        rows.append((scope, None, lowest, 0, 0))
    return rows


def write_thresholds(conn: sqlite3.Connection, rows: Iterable[ThresholdRow]) -> None:
    conn.execute("DROP TABLE IF EXISTS temp.quality_thresholds")
    conn.execute(_CREATE_THRESHOLDS)
    conn.executemany("INSERT INTO quality_thresholds VALUES (?, ?, ?, ?, ?)", rows)


def create_empty_suppressions(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS temp.quality_suppressions")
    conn.execute(_CREATE_SUPPRESSIONS)


def calibration_state_lookup(calibration: Calibration) -> StateLookup:
    """Return each language's recorded validation state; None when it records none.

    Whether the state gates is decided by ``quality_mode`` from the calibration's
    ``GATING_STATES`` (``panel-validated`` and ``baseline-validated``).
    """

    def state_of(language: str) -> str | None:
        entry = calibration.languages.get(language)
        if entry is None:
            entry = calibration.languages.get(LANGUAGE_FALLBACKS.get(language, ""))
        if entry is None:
            return None
        state = entry.validation.get("state")
        return state if isinstance(state, str) else None

    return state_of


def scan_languages(rows: Iterable[QualityRow]) -> list[str]:
    return sorted(
        {row.language for row in rows if row.level == "file" and row.language}
    )


def apply_quality_mode(
    findings: list[Finding], state_of: StateLookup, languages: list[str]
) -> list[Finding]:
    """Cap gate findings of non-validated languages at info and label them.

    A scope-level finding (no language) gates only when every scored language is
    validated.
    """
    all_validated = bool(languages) and all(
        language_is_validated(state_of, language) for language in languages
    )
    scope_language = languages[0] if all_validated else None
    return [_moded(f, state_of, scope_language) for f in findings]


def _moded(
    finding: Finding, state_of: StateLookup, scope_language: str | None
) -> Finding:
    if finding.rule_id not in GATE_RULE_IDS:
        return finding
    language = finding.evidence.get("language") or scope_language
    mode = effective_mode(finding.severity.value, language, state_of)
    if mode.label is None:
        return finding
    evidence = {**finding.evidence, MODE_EVIDENCE_KEY: mode.label}
    return dataclasses.replace(
        finding, severity=Severity(mode.severity), evidence=evidence
    )


def unscored_blocking_diagnostics(findings: list[Finding]) -> list[dict]:
    """One blocking diagnostic per unscored-share finding with blocking = 1."""
    return [
        {
            "rule_id": UNSCORED_RULE_ID,
            "path": finding.location.file,
            "message": finding.message,
            "blocking": True,
            "severity": "error",
            "source": "rules",
        }
        for finding in findings
        if finding.rule_id == UNSCORED_RULE_ID and finding.evidence.get("blocking") == 1
    ]


def split_generated_filter(
    findings: list[Finding], filter_generated: Callable[[list[Finding]], list[Finding]]
) -> list[Finding]:
    """Apply the generated-path filter to non-quality findings; keep quality ones.

    Scope-level quality findings use file ``.``; file and function findings come
    from rows the scorer already classified, so the path filter must not drop them.
    """
    quality = [f for f in findings if f.rule_id.startswith(QUALITY_PREFIX)]
    others = [f for f in findings if not f.rule_id.startswith(QUALITY_PREFIX)]
    kept = filter_generated(others)
    order = {id(f): index for index, f in enumerate(findings)}
    return sorted([*kept, *quality], key=lambda f: order[id(f)])
