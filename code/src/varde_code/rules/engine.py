"""Run pattern and SQL rules in scan order."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from varde_code.rules.finding import Finding
from varde_code.rules.model import Diagnostic, Rule
from varde_code.rules.pattern import run_pattern_rules
from varde_code.rules.sql import run_sql_rules_in_repo
from varde_code.seams import ExtractionProvider


def run_rules(
    rules: list[Rule],
    repo_root: str | Path,
    conn: sqlite3.Connection,
    provider: ExtractionProvider,
) -> tuple[list[Finding], list[Diagnostic]]:
    """Run pattern rules before SQL rules, retaining each runner's order."""
    pattern_findings, pattern_diagnostics = run_pattern_rules(rules, repo_root, conn)
    sql_findings, sql_diagnostics = run_sql_rules_in_repo(
        rules, conn, Path(repo_root), provider
    )
    return (
        [*pattern_findings, *sql_findings],
        [*pattern_diagnostics, *sql_diagnostics],
    )
