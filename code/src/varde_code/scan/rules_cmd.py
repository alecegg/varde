"""Command wrappers for listing and managing rule packs."""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any

from varde_code.query.params import QueryError, req_str
from varde_code.rules import loader
from varde_code.rules.model import Verification, boundary_configured
from varde_code.rules.scan_output import _rule_dict


def run(
    operation: str, input: object, *, user: bool = False, force: bool = False
) -> dict[str, Any]:
    if not isinstance(input, dict):
        raise QueryError("invalid_input", "input must be a JSON object")
    if operation == "diff":
        rule_id = input.get("ruleId")
        if not isinstance(rule_id, str):
            message = (
                "ruleId is required for a rules diff"
                if rule_id is None
                else "ruleId must be a built-in rule ID string"
            )
            raise QueryError("invalid_input", message)
        return diff(input, rule_id)
    root = _repo_dir(input)
    if operation == "list":
        return list_rules(root)
    if operation == "seed":
        return seed(root, input, user=user, force=force)
    if operation == "remove":
        return remove(root, user=user, force=force)
    raise QueryError("invalid_input", f"unknown rules operation {operation!r}")


def list_rules(root: Path) -> dict[str, Any]:
    rules, diagnostics, details = loader.load_rules_with_details(root)
    rows = []
    for rule in rules:
        row = _rule_dict(rule)
        if rule.verification is Verification.DEPENDENCY_BOUNDARY:
            row["configuration_status"] = (
                "configured"
                if boundary_configured(rule) is True
                else "requires_configuration"
            )
        row.update(
            {
                "source": details.origins.get(rule.id, "custom"),
                "severitySource": details.severity_sources[rule.id],
                "drifted": rule.id in details.drifted,
                "name": rule.name,
                "description": rule.description,
            }
        )
        rows.append(row)
    for disabled in details.disabled_rules:
        row = _rule_dict(disabled.rule)
        if disabled.rule.verification is Verification.DEPENDENCY_BOUNDARY:
            row["configuration_status"] = (
                "configured"
                if boundary_configured(disabled.rule) is True
                else "requires_configuration"
            )
        row.update(
            {
                "severity": "off",
                "source": "override",
                "severitySource": disabled.severity_source,
                "drifted": disabled.rule.id in details.drifted,
                "disabled": True,
                "name": disabled.rule.name,
                "description": disabled.rule.description,
            }
        )
        rows.append(row)
    return {
        "rules": rows,
        "diagnostics": [_diagnostic(item) for item in diagnostics],
        "orphanedOverrides": [
            {
                "ruleId": item.rule_id,
                "severity": item.severity,
                "source": item.source,
                "file": item.file,
            }
            for item in details.orphaned_overrides
        ],
    }


def diff(input: dict[str, Any], rule_id: str) -> dict[str, Any]:
    if not rule_id:
        raise QueryError("invalid_input", "ruleId must not be empty")
    root = _repo_dir(input)
    builtin = loader.builtin_rule_pack_for(rule_id)
    if builtin is None:
        raise QueryError("invalid_input", f"unknown built-in rule id: {rule_id}")
    label, builtin_contents = builtin
    _, _, details = loader.load_rules_with_details(root)
    seeded_file = details.definition_files.get(rule_id)
    if seeded_file is None:
        raise QueryError(
            "invalid_input", f"no seeded pack file found for built-in rule {rule_id}"
        )
    scope = details.definition_scopes.get(rule_id)
    if scope is None:
        raise QueryError(
            "invalid_input", f"no seeded pack scope found for built-in rule {rule_id}"
        )
    try:
        seeded_contents = Path(seeded_file).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise QueryError(
            "io_error", f"failed to read seeded pack {seeded_file}: {error}"
        ) from error
    lines = difflib.unified_diff(
        seeded_contents.splitlines(keepends=True),
        builtin_contents.splitlines(keepends=True),
        fromfile=f"a/{seeded_file}",
        tofile=f"b/{Path(label).name}",
        lineterm="\n",
    )
    return {
        "ruleId": rule_id,
        "file": seeded_file,
        "seedScope": scope,
        "diff": "".join(lines),
    }


def seed(
    root: Path, input: dict[str, Any], *, user: bool, force: bool
) -> dict[str, Any]:
    rule_id = input.get("ruleId")
    if rule_id is not None and not isinstance(rule_id, str):
        raise QueryError("invalid_input", "ruleId must be a built-in rule ID string")
    if rule_id == "":
        raise QueryError("invalid_input", "ruleId must not be empty")
    target = loader.user_rules_dir() if user else root / ".varde-code" / "rules"
    try:
        results = loader.seed_builtin_rules_for(target, force=force, rule_id=rule_id)
    except ValueError as error:
        raise QueryError(
            "invalid_input", f"failed to seed rules into {target}: {error}"
        ) from error
    except OSError as error:
        raise QueryError(
            "io_error", f"failed to seed rules into {target}: {error}"
        ) from error
    return {
        "targetDir": _display_path(root, target),
        "seeded": [
            {
                "fileName": item.file_name,
                "path": _display_path(root, item.path),
                "written": item.written,
                "skippedExisting": item.skipped_existing,
            }
            for item in results
        ],
    }


def remove(root: Path, *, user: bool, force: bool) -> dict[str, Any]:
    target = loader.user_rules_dir() if user else root / ".varde-code" / "rules"
    try:
        results = loader.remove_builtin_rules(target, force=force)
    except OSError as error:
        raise QueryError(
            "io_error", f"failed to remove seeded rules from {target}: {error}"
        ) from error
    return {
        "targetDir": _display_path(root, target),
        "removed": [
            {
                "fileName": item.file_name,
                "path": _display_path(root, item.path),
                "removed": item.removed,
                "skippedModified": item.skipped_modified,
            }
            for item in results
        ],
    }


def _repo_dir(input: dict[str, Any]) -> Path:
    raw = req_str(input, "repoRoot")
    root = Path(raw)
    if not root.is_dir():
        raise QueryError("invalid_input", f"repoRoot is not a directory: {raw}")
    return root


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _diagnostic(item: Any) -> dict[str, Any]:
    result = {"file": item.file, "reason": item.reason}
    if item.rule_id is not None:
        result["rule_id"] = item.rule_id
    return result
