"""Run and page the inline tests declared by rule packs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from varde_code import ApiError
from varde_code.extract.provider import CodeExtractionProvider
from varde_code.rules import scan_output
from varde_code.rules.loader import (
    discover,
    load_rules_with_details,
    parse_pack_file,
    user_rules_dir,
)
from varde_code.rules.model import RuleKind
from varde_code.rules.test_runner import run_pattern_rule_tests, run_sql_rule_tests
from varde_code.toz_bridge import PAGE_LIMIT, add_guide, capture_items

RESULTS_LIMIT = 100


def run_tests(input: object, capture=None) -> dict[str, Any]:
    """Return test results, counts, and rule loader diagnostics."""
    if not isinstance(input, dict):
        raise ApiError("invalid_input", "test input must be a JSON object")
    rules, diagnostics, rule_paths = _load_rules(input)
    provider = CodeExtractionProvider()
    results = []
    for rule in rules:
        if rule.test is None:
            continue
        if rule.kind is RuleKind.PATTERN:
            results.extend(run_pattern_rule_tests(rule))
        elif rule.kind is RuleKind.SQL:
            results.extend(run_sql_rule_tests(rule, provider))

    passed = sum(result.passed for result in results)
    failed = len(results) - passed
    entries = [_result_json(result, rule_paths) for result in results]
    total = len(entries)
    reference = (
        capture_items(capture, "test", entries) if total > RESULTS_LIMIT else None
    )
    shown = PAGE_LIMIT if reference else RESULTS_LIMIT
    entries = entries[:shown]
    payload: dict[str, Any] = {
        "results": entries,
        "summary": {"passed": passed, "failed": failed},
        "diagnostics": [_diagnostic_json(item) for item in diagnostics],
    }
    if total > RESULTS_LIMIT:
        details: dict[str, Any] = {"shown": shown, "total": total}
        if reference:
            add_guide(details, reference, shown, min(shown + PAGE_LIMIT, total))
            payload["guide"] = {"toz": reference}
        payload.setdefault("guide", {}).setdefault("truncated", {})["results"] = details
    return scan_output.sort_json_maps(payload)


def _load_rules(input: dict[str, Any]):
    rules_dir = input.get("rulesDir")
    if rules_dir is not None:
        if not isinstance(rules_dir, str):
            raise ApiError("invalid_input", "rulesDir must be a string")
        directory = Path(rules_dir)
        if not directory.is_dir():
            raise ApiError("invalid_input", f"rulesDir is not a directory: {rules_dir}")
        paths = sorted(
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix == ".toml"
        )
        rules = []
        diagnostics = []
        rule_paths = {}
        for path in paths:
            pack_rules, issues = parse_pack_file(path)
            rules.extend(pack_rules)
            diagnostics.extend(issues)
            for rule in pack_rules:
                rule_paths.setdefault(rule.id, str(path))
        return rules, diagnostics, rule_paths

    repo_root = Path.cwd()
    rules, diagnostics, details = load_rules_with_details(repo_root)
    discovered, discovery_diagnostics = discover(repo_root, user_rules_dir())
    diagnostics.extend(discovery_diagnostics)
    rule_paths = dict(details.definition_files)
    for item in discovered:
        pack_rules, _ = parse_pack_file(item.path)
        for rule in pack_rules:
            rule_paths.setdefault(rule.id, str(item.path))
    return rules, diagnostics, rule_paths


def _result_json(result, rule_paths: dict[str, str]) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "rule_id": result.rule_id,
        "test_name": result.test_name,
        "status": "pass" if result.passed else "fail",
        "file": rule_paths.get(result.rule_id),
    }
    if not result.passed and result.detail is not None:
        entry["detail"] = result.detail
    return entry


def _diagnostic_json(diagnostic: Any) -> dict[str, Any]:
    if isinstance(diagnostic, dict):
        return diagnostic
    return {
        "rule_id": diagnostic.rule_id,
        "file": diagnostic.file,
        "message": diagnostic.reason,
    }
