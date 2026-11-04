"""Run loaded code rules against a fresh persisted index."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from varde_code.extract.provider import CodeExtractionProvider
from varde_code.index.paths import repo_db_path
from varde_code.quality_pass.pass_ import QualityPassError
from varde_code.quality_score.calibration import (
    Calibration,
    load_calibration,
    shipped_calibration_path,
)
from varde_code.quality_score.vs import VS_NAMES
from varde_code.query.modes import index_service
from varde_code.query.output import compact
from varde_code.query.params import QueryError, req_str
from varde_code.rules import scan_output
from varde_code.rules.engine import run_rules
from varde_code.rules.finding import Finding
from varde_code.rules.loader import builtin_rules, load_rules_with_details
from varde_code.rules.model import Diagnostic, Rule, Severity
from varde_code.rules.scan_output import filter_generated
from varde_code.rules.suppress import filter_findings
from varde_code.scan import (
    changed_since,
    integrity,
    quality_verdict,
    quality_wiring,
)
from varde_code.scan.quality_scores import materialize_quality_scores
from varde_code.toz_bridge import capture_items

DEFAULT_FINDINGS_LIMIT = 100


def severity_threshold(input: dict[str, Any]) -> Severity:
    value = input.get("severityThreshold", "error")
    if not isinstance(value, str):
        raise QueryError(
            "invalid_input",
            "severityThreshold must be a string (expected error|warning|info)",
        )
    result = Severity.from_name(value)
    if result is None:
        raise QueryError(
            "invalid_input",
            f"unknown severityThreshold {value!r} (expected error|warning|info)",
        )
    return result


def selected_gate_rules(input: dict[str, Any], rules: list[Rule]) -> list[str] | None:
    selection = input.get("gateRules")
    if selection is None:
        return None
    if "severityThreshold" in input:
        raise QueryError(
            "invalid_input", "gateRules and severityThreshold are mutually exclusive"
        )
    if not isinstance(selection, list) or not selection:
        raise QueryError(
            "invalid_input", "gateRules must be a nonempty array of rule IDs"
        )
    if any(not isinstance(rule_id, str) for rule_id in selection):
        raise QueryError("invalid_input", "gateRules entries must be rule ID strings")
    if len(set(selection)) != len(selection):
        duplicate = next(item for item in selection if selection.count(item) > 1)
        raise QueryError("invalid_input", f"duplicate gate rule: {duplicate}")
    known = {rule.id for rule in rules}
    for rule_id in selection:
        if rule_id not in known:
            raise QueryError("invalid_input", f"unknown active gate rule: {rule_id}")
        rule = next(rule for rule in rules if rule.id == rule_id)
        from varde_code.rules.model import boundary_configured

        configured = boundary_configured(rule)
        if isinstance(configured, str):
            raise QueryError("invalid_input", configured)
        if configured is False:
            raise QueryError(
                "invalid_input",
                f"gate rule {rule_id} requires source_prefix and target_prefix "
                "configuration",
            )
    return sorted(selection)


def scan_options(input: object) -> tuple[Path, bool, bool, dict[str, Any]]:
    if not isinstance(input, dict):
        raise QueryError("invalid_input", "scan input must be a JSON object")
    root = Path(req_str(input, "repoRoot"))
    if not root.is_dir():
        raise QueryError("invalid_input", f"repoRoot is not a directory: {root}")
    apply = _bool(input, "apply")
    force = _bool(input, "force")
    severity_threshold(input)
    findings = findings_options(input)
    _bool(input, "skipQuality")
    _bool(input, "allowCalibrationChange")
    _bool(input, "migratePreview")
    _bool(input, "verdict")
    _vs_name(input)
    _optional_ref(input, "rulesRef")
    _optional_ref(input, "changedSince")
    if "output" in input and not isinstance(input["output"], str):
        raise QueryError("invalid_input", "output must be a string")
    return root, apply, force, findings


def _vs_name(input: dict[str, Any]) -> None:
    value = input.get("vs")
    if value is not None and value not in VS_NAMES:
        raise QueryError(
            "invalid_input", f"vs must be one of {', '.join(VS_NAMES)}, not {value!r}"
        )


def _optional_ref(input: dict[str, Any], name: str) -> None:
    value = input.get(name)
    if value is not None and not (isinstance(value, str) and value):
        raise QueryError("invalid_input", f"{name} must be a nonempty string")


def findings_options(input: dict[str, Any]) -> dict[str, Any]:
    full = _bool(input, "fullFindings")
    limit = _nonnegative(input, "findingsLimit", DEFAULT_FINDINGS_LIMIT)
    if limit == 0:
        raise QueryError("invalid_input", "findingsLimit must be greater than zero")
    return {
        "full": full,
        "limit": limit,
        "offset": _nonnegative(input, "findingsOffset", 0),
    }


def scan_repo(input: object, capture=None) -> dict[str, Any]:
    if isinstance(input, dict) and input.get("operation") == "setup":
        raise QueryError(
            "invalid_input", "scan setup is not available through scan_repo"
        )
    root, _apply, _force, options = scan_options(input)
    scan_input = input if isinstance(input, dict) else {}
    if _bool(scan_input, "migratePreview"):
        return _migrate_preview(root)
    rules, rule_diagnostics, details, config_files = _load_scan_rules(root, scan_input)
    integrity_diagnostics: list[dict[str, Any]] = []
    if _bool(scan_input, "skipQuality"):
        rules = quality_wiring.without_quality(rules)
    else:
        integrity_diagnostics = _integrity_diagnostics(
            root, scan_input, rules, details, config_files
        )
    gate_rules = selected_gate_rules(scan_input, rules)
    threshold = severity_threshold(scan_input)
    service = index_service()
    if service is None:
        db_path = _repo_db_path(root)
    else:
        try:
            service.ensure_fresh(root)
            db_path = Path(service.repo_db_path(root))
        except Exception as exc:
            raise QueryError("index_stale", str(exc)) from exc
    if not db_path.is_file():
        raise QueryError("index_missing", _missing_index_message(db_path))
    conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    try:
        conn.row_factory = sqlite3.Row
        quality = _prepare_quality(conn, root, rules, scan_input, config_files)
        findings, diagnostics = run_rules(rules, root, conn, CodeExtractionProvider())
        if quality is not None:
            findings = quality_wiring.apply_quality_mode(findings, *quality)
            findings = _with_suppressed(findings, rules, conn, root)
            integrity_diagnostics.extend(
                quality_wiring.unscored_blocking_diagnostics(findings)
            )
        diagnostic_rows: list[Diagnostic | dict[str, Any]] = list(diagnostics)
        diagnostic_rows.extend(_persisted_diagnostics(conn))
    except sqlite3.Error as exc:
        raise QueryError("db_error", str(exc)) from exc
    except QualityPassError as exc:
        raise QueryError("quality_pass_failed", str(exc)) from exc
    finally:
        conn.close()
    findings = quality_wiring.split_generated_filter(findings, filter_generated)
    findings, stale = integrity.filter_inline_suppressions(
        findings, root, filter_findings
    )
    findings, since_diagnostics = _limit_to_changed(findings, root, scan_input)
    integrity_diagnostics.extend(since_diagnostics)
    diagnostics = [
        _diagnostic_dict(item)
        for item in [*rule_diagnostics, *integrity_diagnostics, *diagnostic_rows]
    ]
    # Rewrite mutation is implemented by the scan apply task; this core keeps
    # the validation contract and reports findings without modifying sources.
    payload = _with_verdict(
        _build_payload(findings, diagnostics, stale, rules, root),
        quality is not None,
        root,
        scan_input,
    )
    _attach_gate(payload, threshold, gate_rules)
    _attach_policy(payload, rules, details.origins, threshold, gate_rules, root)
    compact(payload, scan_input)
    _truncate_findings(payload, options, scan_input, capture)
    return scan_output.sort_json_maps(payload)


def _with_verdict(
    payload: dict[str, Any], quality_on: bool, root: Path, scan_input: dict[str, Any]
) -> dict[str, Any]:
    if not quality_verdict.requested(scan_input):
        return payload
    if not quality_on:
        if quality_verdict.asked_by_name(scan_input):
            payload[quality_verdict.NOTE_KEY] = quality_verdict.SKIPPED_NOTE
        return payload
    calibration = load_calibration(shipped_calibration_path())
    payload[quality_verdict.KEY] = quality_verdict.build(root, scan_input, calibration)
    return payload


def _limit_to_changed(
    findings: list[Finding], root: Path, scan_input: dict[str, Any]
) -> tuple[list[Finding], list[dict[str, Any]]]:
    ref = scan_input.get("changedSince")
    if not ref:
        return findings, []
    changed = changed_since.read_changed_paths(root, ref)
    if changed is None:
        return findings, [integrity.missing_ref_diagnostic("changedSince", ref)]
    return changed_since.limit_to_changed(findings, changed), []


def _load_scan_rules(root: Path, scan_input: dict[str, Any]):
    """Load rules from the working tree, or from ``rulesRef`` when given.

    Returns the rules, loader diagnostics, details and the config files the rules
    came from (the base ref's when ``rulesRef`` is set and found).
    """
    ref = scan_input.get("rulesRef")
    base = integrity.read_ref_config(root, ref) if ref else None
    if base is None:
        rules, diagnostics, details = load_rules_with_details(root)
        return rules, diagnostics, details, integrity.read_working_config(root)
    rules, diagnostics, details = integrity.load_base_rules(
        base, load_rules_with_details
    )
    return rules, diagnostics, details, base


def _integrity_diagnostics(
    root: Path,
    scan_input: dict[str, Any],
    rules: list[Rule],
    details: Any,
    config_files: dict[str, str],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    ref = scan_input.get("rulesRef")
    if ref:
        base = integrity.read_ref_config(root, ref)
        if base is None:
            result.append(integrity.missing_ref_diagnostic("rulesRef", ref))
        else:
            changed = integrity.config_changed_diagnostic(
                base, integrity.read_working_config(root)
            )
            result.extend([changed] if changed else [])
    downgrades = integrity.severity_downgrades(
        builtin_rules(),
        rules,
        (item.rule.id for item in getattr(details, "disabled_rules", [])),
        integrity.override_reasons(config_files),
    )
    result.extend(integrity.downgrade_diagnostic(item) for item in downgrades)
    return result


def _migrate_preview(root: Path) -> dict[str, Any]:
    calibration = load_calibration(shipped_calibration_path())
    pin = integrity.read_pin(integrity.read_working_config(root))
    return {"migrate_preview": integrity.migrate_preview(pin, calibration)}


def _prepare_quality(
    conn: sqlite3.Connection,
    root: Path,
    rules: list[Rule],
    scan_input: dict[str, Any],
    config_files: dict[str, str],
) -> tuple[Any, list[str]] | None:
    """Fill the quality TEMP tables when a quality rule is active.

    Returns the state lookup and scored languages for mode capping, or None.
    """
    if not quality_wiring.has_quality_rules(rules):
        return None
    calibration: Calibration = load_calibration(shipped_calibration_path())
    integrity.check_pin(
        integrity.read_pin(config_files),
        calibration,
        allow_change=_bool(scan_input, "allowCalibrationChange"),
    )
    rows = materialize_quality_scores(
        conn, root, calibration, scope_of=integrity.read_path_scopes(conn, root)
    )
    thresholds = [
        threshold
        for scope in sorted({row.scope for row in rows})
        for threshold in quality_wiring.threshold_rows(calibration, scope)
    ]
    quality_wiring.write_thresholds(conn, thresholds)
    quality_wiring.create_empty_suppressions(conn)
    return (
        quality_wiring.calibration_state_lookup(calibration),
        quality_wiring.scan_languages(rows),
    )


def _with_suppressed(
    findings: list[Any], rules: list[Rule], conn: sqlite3.Connection, root: Path
) -> list[Any]:
    """Count inline-suppressed quality findings and add ``quality-suppressed``."""
    rule = next((r for r in rules if r.id == "quality-suppressed"), None)
    counts = integrity.count_quality_suppressions(findings, root)
    if rule is None or not counts:
        return findings
    integrity.write_suppression_counts(conn, counts)
    extra, _ = run_rules([rule], root, conn, CodeExtractionProvider())
    return [*findings, *extra]


def _repo_db_path(root: Path) -> Path:
    return repo_db_path(root)


def _missing_index_message(path: Path) -> str:
    # Keep the established diagnostic path while scan reads the Python store.
    display_path = path.parents[2] / "repos" / path.parent.name / path.name
    return (
        f"index missing at {display_path}; build it on the main checkout with "
        "`varde map build --repo-root <repo-root>`; find_pattern needs no "
        "index"
    )


def _attach_gate(
    payload: dict[str, Any], threshold: Severity, selected: list[str] | None
) -> None:
    scan_output.attach_gate(payload, threshold)
    selected_set = set(selected) if selected is not None else None
    blocking = sum(
        row.get("rewrite_status") != "applied"
        and (selected_set is None or row.get("rule_id") in selected_set)
        and (
            selected_set is not None
            or _severity(row.get("severity")).rank >= threshold.rank
        )
        for row in payload["findings"]
    )
    incomplete = payload["gate"]["blocking_diagnostic_count"] > 0
    if blocking:
        status, outcome, reasons = "fail", "code-quality-error", ["code-quality-error"]
        if incomplete:
            reasons.append("analysis-incomplete")
    elif incomplete:
        status, outcome, reasons = (
            "unknown",
            "analysis-incomplete",
            ["analysis-incomplete"],
        )
    else:
        status, outcome, reasons = "pass", "passed", ["passed"]
    payload["gate"].update({"status": status, "blocking_findings": blocking})
    payload["gate"]["severity_threshold"] = (
        threshold.value if selected is None else None
    )
    if selected is not None:
        payload["gate"]["rule_ids"] = selected
    payload["outcome"] = outcome
    payload["outcome_reasons"] = reasons


def _attach_policy(
    payload: dict[str, Any],
    rules: list[Rule],
    origins: dict[str, str],
    threshold: Severity,
    selected: list[str] | None,
    root: Path,
) -> None:
    scan_output.attach_policy(payload, rules, root)
    policy = payload["policy"]
    policy["severity_threshold"] = threshold.value
    policy["mode"] = "selected-rules" if selected is not None else "severity-threshold"
    policy["active_rule_count"] = len(rules)
    policy["gating_rule_count"] = (
        len(selected)
        if selected is not None
        else sum(rule.severity.rank >= threshold.rank for rule in rules)
    )
    counts = {"builtin": 0, "custom": 0, "override": 0}
    for rule in rules:
        counts[origins.get(rule.id, "custom")] += 1
    policy["sources"] = counts
    definitions = [
        {
            "id": rule.id,
            "origin": origins.get(rule.id, "custom"),
            "definition": scan_output._rule_dict(rule),
        }
        for rule in rules
    ]
    definitions.sort(key=lambda item: item["id"])
    canonical = json.dumps(
        {"threshold": threshold.value, "selected": selected, "rules": definitions},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    value = 0xCBF29CE484222325
    for byte in canonical.encode("utf-8"):
        value = ((value ^ byte) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    policy["fingerprint"] = f"fnv1a64:{value:016x}"
    if selected is not None:
        policy["severity_threshold"] = None
        policy["rule_ids"] = selected


def _truncate_findings(
    payload: dict[str, Any], options: dict[str, Any], input: dict[str, Any], capture
) -> None:
    findings = payload["findings"]
    total = len(findings)
    offset, limit, full = options["offset"], options["limit"], options["full"]
    reference = (
        capture_items(capture, "scan", findings)
        if not full and (offset > 0 or total > limit)
        else None
    )
    if reference and "findingsLimit" not in input:
        from varde_code.toz_bridge import PAGE_LIMIT

        limit = PAGE_LIMIT
    start = min(offset, total)
    end = total if full else min(start + limit, total)
    payload["findings"] = findings[start:end]
    payload["findings_summary"].update(
        {"shown": end - start, "truncated": start > 0 or end < total, "offset": start}
    )
    if start == 0 and end == total:
        return
    guide = {
        "shown": end - start,
        "total": total,
        "offset": start,
        "limit": None if full else limit,
        "next_offset": end if end < total else None,
        "request": "set findingsOffset to next_offset, or set fullFindings to true"
        if end < total
        else "set fullFindings to true for all findings",
    }
    if reference:
        guide["toz_read"] = (
            f"varde run query --handle {reference['handle']} --lines "
            f"{end + 1}:{min(end + limit, total)}"
        )
        guide["toz_search"] = f'varde run query --handle {reference["handle"]} "<term>"'
        payload.setdefault("guide", {})["toz"] = reference
    payload.setdefault("guide", {}).setdefault("truncated", {})["findings"] = guide


def _build_payload(
    findings, diagnostics, stale, rules: list[Rule], root: Path
) -> dict[str, Any]:
    """Apply scan_output's shared serializers without its default 100-row page."""
    scan_output._normalize_display_paths(findings, root)
    records = [scan_output.normalize_diagnostic(item) for item in diagnostics]
    serialized = [finding.to_dict() for finding in findings]
    for finding, record in zip(findings, serialized, strict=False):
        if finding.rule_id == "duplicate-code-clone":
            record["_identity_span"] = finding.location.span
    payload = {
        "findings": scan_output.collapse_clone_bands(serialized),
        "diagnostics": records,
    }
    if stale:
        payload["stale_suppressions"] = [
            {
                "file": item.file,
                "comment_line": item.comment_line,
                "rule_ids": item.rule_ids,
                **({"reason": item.reason} if item.reason is not None else {}),
            }
            for item in stale
        ]
    scan_output.attach_findings_summary(payload)
    scan_output.hoist_rule_legend(payload, rules)
    return scan_output.sort_json_maps(payload)


def _severity(value: Any) -> Severity:
    severity = Severity.from_name(value) if isinstance(value, str) else None
    return severity if severity is not None else Severity.INFO


def _persisted_diagnostics(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    try:
        rows = conn.execute(
            """SELECT d.path, d.message, d.severity, COALESCE(f.is_test_path, 0)
            FROM diagnostics d LEFT JOIN files f ON f.id = d.file_id
            ORDER BY d.id"""
        ).fetchall()
    except sqlite3.Error:
        return []
    return [
        {
            "path": row[0],
            "message": row[1],
            "severity": row[2],
            "is_test_path": bool(row[3]),
            "source": "persisted",
        }
        for row in rows
        if row[1]
        not in {
            "unsupported file type — skipped",
            "minified/generated source — skipped",
        }
    ]


def _diagnostic_dict(diagnostic: Any) -> dict[str, Any]:
    if isinstance(diagnostic, dict):
        if diagnostic.get("source") == "persisted":
            return diagnostic
        return dict(diagnostic)
    return {
        "rule_id": diagnostic.rule_id,
        "path": diagnostic.file,
        "reason": diagnostic.reason,
        "source": "rules",
    }


def _bool(input: dict[str, Any], name: str) -> bool:
    value = input.get(name, False)
    if not isinstance(value, bool):
        raise QueryError("invalid_input", f"{name} must be a boolean")
    return value


def _nonnegative(input: dict[str, Any], name: str, default: int) -> int:
    value = input.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise QueryError("invalid_input", f"{name} must be a nonnegative integer")
    return value
