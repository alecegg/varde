"""Pure scan payload post-processing shared by JSON rule runners."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path, PurePath
from typing import Any

from varde_code.rules.finding import Finding, Location, finding_id
from varde_code.rules.loader import discover, user_rules_dir
from varde_code.rules.model import Rule, Severity

_GENERATED_COMPONENTS = {
    "target",
    "node_modules",
    "dist",
    "build",
    "vendor",
    "externals",
    "third_party",
    "third-party",
    "bower_components",
    ".next",
    ".nuxt",
    "grammars",
}
_GENERATED_SUFFIXES = (
    ".min.js",
    ".min.mjs",
    ".min.cjs",
    ".min.css",
    ".bundle.js",
    ".bundle.mjs",
    ".pb.go",
    ".gen.go",
    ".gen.ts",
    ".gen.tsx",
    ".gen.js",
    ".gen.mjs",
    ".gen.cjs",
)


def filter_generated(findings: list[Finding]) -> list[Finding]:
    """Drop generated and vendored paths using the scan path rules."""
    return [
        finding for finding in findings if not is_generated_path(finding.location.file)
    ]


def is_generated_path(path: str) -> bool:
    parts = PurePath(path).parts
    if any(
        part in _GENERATED_COMPONENTS or part.endswith(("_fixture", "_fixtures"))
        for part in parts
    ):
        return True
    if any(
        tuple(parts[i : i + len(seq)]) == seq
        for seq in (
            ("priv", "static"),
            ("alembic", "versions"),
            ("migrations", "versions"),
        )
        for i in range(len(parts) - len(seq) + 1)
    ):
        return True
    return bool(parts and parts[-1].lower().endswith(_GENERATED_SUFFIXES))


def normalize_diagnostic(diagnostic: dict[str, Any]) -> dict[str, Any]:
    """Add the common scan diagnostic fields while retaining legacy fields."""
    persisted = diagnostic.get("source") == "persisted"
    blocking = blocks_gate(diagnostic)
    diagnostic.update(
        {
            "kind": "source" if persisted else "rules",
            "source": "persisted" if persisted else "rules",
            "message": diagnostic.get(
                "message", diagnostic.get("reason", "analysis diagnostic")
            ),
            "severity": diagnostic.get("severity", "error" if blocking else "info"),
            "blocking": blocking,
            "location": {
                "file": diagnostic.get("path", diagnostic.get("file", "<unknown>"))
            },
        }
    )
    return diagnostic


def blocks_gate(diagnostic: dict[str, Any]) -> bool:
    if isinstance(diagnostic.get("blocking"), bool):
        return diagnostic["blocking"]
    if diagnostic.get("source") != "persisted":
        return True
    message = diagnostic.get("message")
    expected_skip = message in {
        "unsupported file type — skipped",
        "minified/generated source — skipped",
    }
    return not (diagnostic.get("is_test_path") is True or expected_skip)


def collapse_clone_bands(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bands: dict[str, list[dict[str, Any]]] = {}
    output = []
    for finding in findings:
        label = finding.get("evidence", {}).get("label")
        if finding.get("rule_id") == "duplicate-code-clone" and isinstance(label, str):
            bands.setdefault(label, []).append(finding)
        else:
            output.append(finding)
    grouped: dict[
        tuple[tuple[str, int, int], ...], tuple[list[str], list[dict[str, Any]]]
    ] = {}
    for label, members in sorted(bands.items()):
        members.sort(key=_clone_member_key)
        if members[0].get("evidence", {}).get("verification") == "exact-clone":
            output.append(_collapsed_clone([label], members))
            continue
        key = tuple(_clone_member_key(member) for member in members)
        if key not in grouped:
            grouped[key] = ([label], members)
        else:
            grouped[key][0].append(label)
    output.extend(
        _collapsed_clone(sorted(labels), members)
        for labels, members in grouped.values()
    )
    return output


def _clone_member_key(finding: dict[str, Any]) -> tuple[str, int, int]:
    span = finding["location"]["span"]
    return finding["location"]["file"], span["start_line"], span["end_line"]


def _collapsed_clone(
    labels: list[str], members: list[dict[str, Any]]
) -> dict[str, Any]:
    anchor = members[0]
    label = labels[0]
    evidence = dict(anchor.get("evidence", {}))
    evidence.update(
        {
            "band": label,
            "bands": labels,
            "members": [
                {
                    "file": item["location"]["file"],
                    "startLine": item["location"]["span"]["start_line"],
                    "endLine": item["location"]["span"]["end_line"],
                }
                for item in members
            ],
        }
    )
    item = dict(anchor)
    span = anchor.get("_identity_span") or _span_from_finding(anchor)
    item.pop("_identity_span", None)
    item.update(
        {"id": finding_id(anchor["rule_id"], label, span), "evidence": evidence}
    )
    return item


def _span_from_finding(finding: dict[str, Any]):
    from varde_code.model import Span

    return Span(**finding["location"]["span"])


def build_scan_payload(
    findings: list[Finding],
    diagnostics: list[dict[str, Any]],
    stale_suppressions: list[Any],
    rules: list[Rule],
    repo_root: str | Path,
) -> dict[str, Any]:
    _normalize_display_paths(findings, Path(repo_root))
    records = [normalize_diagnostic(item) for item in diagnostics]
    serialized_findings = [finding.to_dict() for finding in findings]
    for finding, record in zip(findings, serialized_findings, strict=False):
        if finding.rule_id == "duplicate-code-clone":
            record["_identity_span"] = finding.location.span
    payload: dict[str, Any] = {
        "findings": collapse_clone_bands(serialized_findings),
        "diagnostics": records,
    }
    if stale_suppressions:
        payload["stale_suppressions"] = [
            {
                "file": item.file,
                "comment_line": item.comment_line,
                "rule_ids": item.rule_ids,
                **({"reason": item.reason} if item.reason is not None else {}),
            }
            for item in stale_suppressions
        ]
    attach_gate(payload)
    attach_policy(payload, rules, repo_root)
    attach_findings_summary(payload)
    hoist_rule_legend(payload, rules)
    truncate_findings(payload)
    return sort_json_maps(payload)


def _normalize_display_paths(findings: list[Finding], repo_root: Path) -> None:
    root = repo_root.resolve()
    for finding in findings:
        path = Path(finding.location.file)
        if not path.is_absolute():
            continue
        try:
            relative = path.resolve().relative_to(root).as_posix()
        except ValueError:
            continue
        finding.location = Location(relative, finding.location.span)


def attach_gate(payload: dict[str, Any], threshold: Severity = Severity.ERROR) -> None:
    diagnostics = payload["diagnostics"]
    blocking_diagnostics = sum(blocks_gate(item) for item in diagnostics)
    blocking_findings = sum(
        _severity_rank(item.get("severity")) >= threshold.rank
        for item in payload["findings"]
    )
    incomplete = blocking_diagnostics > 0
    if blocking_findings:
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
    payload.update(
        {
            "analysis": {"status": "incomplete" if incomplete else "complete"},
            "outcome": outcome,
            "outcome_reasons": reasons,
            "gate": {
                "status": status,
                "severity_threshold": threshold.value,
                "blocking_findings": blocking_findings,
                "diagnostic_count": len(diagnostics),
                "blocking_diagnostic_count": blocking_diagnostics,
            },
        }
    )


def attach_policy(
    payload: dict[str, Any], rules: list[Rule], repo_root: str | Path
) -> None:
    origins = _rule_origins(rules, Path(repo_root))
    definitions = [
        {"id": rule.id, "origin": origins[rule.id], "definition": _rule_dict(rule)}
        for rule in rules
    ]
    definitions.sort(key=lambda item: item["id"])
    canonical = json.dumps(
        {"threshold": "error", "selected": None, "rules": definitions},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    value = 0xCBF29CE484222325
    for byte in canonical.encode("utf-8"):
        value = ((value ^ byte) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    counts = {"builtin": 0, "custom": 0, "override": 0}
    for origin in origins.values():
        counts[origin] += 1
    payload["policy"] = {
        "mode": "severity-threshold",
        "active_rule_count": len(rules),
        "gating_rule_count": sum(
            rule.severity.rank >= Severity.ERROR.rank for rule in rules
        ),
        "severity_threshold": "error",
        "sources": counts,
        "fingerprint": f"fnv1a64:{value:016x}",
    }


def _rule_origins(rules: list[Rule], repo_root: Path) -> dict[str, str]:
    builtin_ids = set()
    builtin_dir = Path(__file__).parent / "builtin"
    for path in builtin_dir.glob("*.toml"):
        try:
            builtin_ids.update(
                item.get("id")
                for item in tomllib.loads(path.read_text()).get("rule", [])
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            )
        except OSError, tomllib.TOMLDecodeError:
            continue
    external_ids = set()
    files, _ = discover(repo_root, user_rules_dir())
    for item in files:
        try:
            entries = tomllib.loads(item.path.read_text(encoding="utf-8")).get(
                "rule", []
            )
        except OSError, tomllib.TOMLDecodeError:
            continue
        external_ids.update(
            entry.get("id")
            for entry in entries
            if isinstance(entry, dict) and isinstance(entry.get("id"), str)
        )
    return {
        rule.id: "override"
        if rule.id in builtin_ids and rule.id in external_ids
        else "builtin"
        if rule.id in builtin_ids
        else "custom"
        for rule in rules
    }


def _rule_dict(rule: Rule) -> dict[str, Any]:
    result = {}
    for name in (
        "id",
        "kind",
        "verification",
        "severity",
        "message",
        "name",
        "description",
        "remediation",
        "pattern",
        "query",
        "thresholds",
        "strings",
        "constraints",
        "fix",
        "rewrite",
        "languages",
        "exclude_test_paths",
        "exclude_tooling_paths",
    ):
        value = getattr(rule, name)
        if value is None:
            continue
        if name == "constraints":
            value = {
                key: spec.patterns[0]
                if len(spec.patterns) == 1
                else list(spec.patterns)
                for key, spec in value.items()
            }
        elif name in {"kind", "verification", "severity"}:
            value = value.value if value is not None else None
        result[name] = value
    return result


def attach_findings_summary(payload: dict[str, Any]) -> None:
    findings = payload["findings"]
    by_rule: dict[str, int] = {}
    by_severity = {"error": 0, "warning": 0, "info": 0}
    for finding in findings:
        by_rule[finding["rule_id"]] = by_rule.get(finding["rule_id"], 0) + 1
        by_severity[finding["severity"]] = by_severity.get(finding["severity"], 0) + 1
    payload["findings_summary"] = {
        "total": len(findings),
        "shown": len(findings),
        "truncated": False,
        "by_rule": by_rule,
        "by_severity": by_severity,
    }


def hoist_rule_legend(payload: dict[str, Any], rules: list[Rule]) -> None:
    if not payload["findings"]:
        return
    by_id = {rule.id: rule for rule in rules}
    legend = {}
    for finding in payload["findings"]:
        rule = by_id.get(finding.get("rule_id"))
        if rule is None:
            continue
        finding.pop("remediation", None)
        if finding.get("message") == rule.message:
            finding.pop("message", None)
        entry = {"message": rule.message}
        if rule.remediation is not None:
            entry["remediation"] = rule.remediation
        legend.setdefault(rule.id, entry)
    payload["rules"] = legend


def truncate_findings(
    payload: dict[str, Any], limit: int = 100, offset: int = 0, full: bool = False
) -> None:
    findings = payload["findings"]
    start = min(offset, len(findings))
    end = len(findings) if full else min(start + limit, len(findings))
    shown = end - start
    truncated = start > 0 or end < len(findings)
    payload["findings"] = findings[start:end]
    payload["findings_summary"].update(
        {"shown": shown, "truncated": truncated, "offset": start}
    )
    if truncated:
        payload.setdefault("guide", {}).setdefault("truncated", {})["findings"] = {
            "shown": shown,
            "total": len(findings),
            "offset": start,
            "limit": None if full else limit,
            "next_offset": end if end < len(findings) else None,
            "request": "set findingsOffset to next_offset, or set fullFindings to true"
            if end < len(findings)
            else "set fullFindings to true for all findings",
        }


def _severity_rank(value: Any) -> int:
    return {"error": 2, "warning": 1, "info": 0}.get(value, 0)


def sort_json_maps(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: sort_json_maps(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [sort_json_maps(item) for item in value]
    return value
