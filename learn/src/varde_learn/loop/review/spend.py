"""Aggregate review-window usage into redacted spend report data."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .extract import redact_value
from .spend_roles import attribute, plan
from .spend_usage import aggregate, coverage
from .spend_usage import rows as usage_rows
from .spend_waste import analyze


def _table(
    groups: dict[str, list[dict[str, Any]]], total: float
) -> list[dict[str, Any]]:
    result = []
    for name, sessions in sorted(
        groups.items(), key=lambda item: -sum(x["totals"]["weighted"] for x in item[1])
    ):
        totals = Counter()
        for session in sessions:
            totals.update(session["totals"])
        result.append(
            {
                "name": name,
                "sessions": len(sessions),
                **dict(totals),
                "share": totals["weighted"] / total if total else 0.0,
            }
        )
    return result


def build(
    records_by_session: list[dict[str, Any]],
    harnesses: list[str],
    start: datetime | None = None,
    end: datetime | None = None,
) -> dict[str, Any]:
    """Build report data from inspected adapter records in the requested window."""
    session_rows = []
    coverage_rows = []
    for item in records_by_session:
        if "usage_rows" in item:
            usage = item["usage_rows"]
            coverage_rows.append(item["coverage"])
            tool_names = item.get("tool_names", [])
        else:
            records = item["records"]
            usage = usage_rows(records, start, end)
            coverage_rows.append(coverage(item["harness"], records))
            tool_names = _tool_names(records, usage)
        if item.get("inspection_status"):
            coverage_rows[-1] = {
                "harness": item["harness"],
                "status": item["inspection_status"],
            }
        if not usage:
            continue
        totals = aggregate(usage)
        session_rows.append(
            {
                "session_id": item["session_id"],
                "harness": item["harness"],
                "project": item.get("project") or "(unknown)",
                "first_prompt": item.get("first_prompt", ""),
                "is_subagent": item.get("is_subagent", False),
                "parent_session_id": item.get("parent_session_id"),
                "rows": usage,
                "totals": totals,
                **totals,
                "tool_names": tool_names,
                "target": item.get("target")
                or review_target(item.get("first_prompt", "")),
                "first_call_context": usage[0]["context_size"],
            }
        )
    attribution = attribute(session_rows)
    attributed = attribution["sessions"]
    weighted_total = sum(item["totals"]["weighted"] for item in attributed)
    role_rows = _table(_group(attributed, "role"), weighted_total)
    plan_rows = _table(_group(attributed, "plan", "(unattributed)"), weighted_total)
    top = sorted(attributed, key=lambda item: -item["totals"]["weighted"])[:10]
    totals = aggregate(row for item in attributed for row in item["rows"])
    by_harness = {}
    for name in sorted(set(harnesses)):
        counts = Counter(
            row["status"] for row in coverage_rows if row["harness"] == name
        )
        by_harness[name] = {
            "sessions": sum(counts.values()),
            "per_call": counts["per_call"],
            "session_total": counts["session_total"],
            "no_usage": counts["no_usage"],
            "inspection_failed": counts["inspection_failed"],
        }
    waste_records = [
        {
            key: item[key]
            for key in (
                "session_id",
                "rows",
                "tool_names",
                "role",
                "target",
                "first_call_context",
            )
            if key in item
        }
        for item in attributed
    ]
    waste = analyze(waste_records)
    findings = _findings(waste, attributed, waste_records)
    snapshot = {
        "totals": totals,
        "by_role": role_rows,
        "by_plan": plan_rows,
        "coverage": by_harness,
        "window": {
            "start": start.isoformat() if start else None,
            "end": end.isoformat() if end else None,
        },
        "unattributed_share": sum(
            x["weighted"] for x in plan_rows if x["name"] == "(unattributed)"
        )
        / weighted_total
        if weighted_total
        else 0.0,
    }
    return {
        "snapshot": snapshot,
        "by_role": role_rows,
        "by_plan": plan_rows,
        "top_sessions": top,
        "coverage": by_harness,
        "unattributed_share": snapshot["unattributed_share"],
        "findings": findings,
        "waste": waste,
    }


_BRANCH_TARGET = re.compile(
    r"(?i)\b(?:branch|target|pr)\s*(?:is|:|=)?\s*[`'\"]?([a-z0-9][a-z0-9._/-]{2,})"
)
_REVIEW_SUBJECT = re.compile(
    r"(?i)\breview(?:ing)?\s+(?:of\s+)?[`'\"]?([a-z0-9][a-z0-9._/-]{2,})"
)


def review_target(prompt: str) -> str | None:
    """Extract a stable plan or branch target for repeated-review grouping."""
    plan_id = plan(prompt)
    if plan_id:
        return plan_id
    match = _BRANCH_TARGET.search(prompt[:1500])
    if match:
        return match.group(1).strip("./")
    match = _REVIEW_SUBJECT.search(prompt[:1500])
    if match and match.group(1).lower() not in {"the", "this", "that"}:
        return match.group(1).strip("./")
    return None


def prepare_session(
    item: dict[str, Any], start: datetime, end: datetime
) -> dict[str, Any]:
    """Retain only windowed usage rows and detector metadata from a transcript."""
    records = _session_records(item, item["records"])
    usage = usage_rows(records, start, end)
    session_total_records = any(
        getattr(record, "usage_total", None) is not None for record in records
    )
    usage_coverage = {
        "harness": item["harness"],
        "status": (
            "per_call"
            if usage
            else "session_total"
            if session_total_records
            else "no_usage"
        ),
    }
    return {
        **{key: value for key, value in item.items() if key != "records"},
        "usage_rows": usage,
        "tool_names": _tool_names(records, usage),
        "coverage": usage_coverage,
    }


def _session_records(item: dict[str, Any], records: list[Any]) -> list[Any]:
    if item.get("harness") != "claude":
        return records
    anchored_records = [
        record
        for record in records
        if getattr(getattr(record, "anchor", None), "source_id", None)
    ]
    if not anchored_records:
        return records
    suffix = f"/{item['session_id']}.jsonl"
    return [
        record
        for record in anchored_records
        if str(
            getattr(getattr(record, "anchor", None), "source_id", "") or ""
        ).endswith(suffix)
    ]


def _tool_names(records: list[Any], usage: list[dict[str, Any]]) -> list[str | None]:
    by_message_id = {}
    for record in records:
        message_id = getattr(record, "provider_message_id", None)
        name = getattr(record, "tool_name", None)
        if message_id and isinstance(name, str):
            by_message_id[message_id] = name
    return [by_message_id.get(row.get("provider_message_id")) for row in usage]


def _group(
    sessions: list[dict[str, Any]], key: str, fallback: str | None = None
) -> dict[str, list[dict[str, Any]]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in sessions:
        groups[str(item.get(key) or fallback or "(none)")].append(item)
    return groups


def _findings(
    detectors: dict[str, Any],
    sessions: list[dict[str, Any]],
    waste_records: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {"setup": [], "project": []}
    labels = {
        "context_over_200k": (
            "Large contexts",
            "setup",
            "Review context limits and handoff practices.",
            "medium",
        ),
        "context_over_400k": (
            "Very large contexts",
            "setup",
            "Review whether these sessions need compaction.",
            "medium",
        ),
        "poll_watch_msg_read_sleep": (
            "Polling turns",
            "setup",
            "Batch status checks or reduce polling frequency.",
            "low",
        ),
        "msg_send": (
            "Message turns",
            "setup",
            "Batch coordination messages where practical.",
            "low",
        ),
        "startup_prompt": (
            "Startup prompt spend",
            "setup",
            "Review repeatedly loaded startup instructions.",
            "low",
        ),
        "repeated_review_rounds": (
            "Repeated review rounds",
            "project",
            "Review whether later review rounds can target named findings.",
            "medium",
        ),
        "subagent": (
            "Subagent usage",
            "setup",
            "Review worker harness policy and attribution.",
            "medium",
        ),
        "cache_rebuild_after_idle": (
            "Cache rebuilds after idle",
            "setup",
            "Review whether long-lived sessions should close while idle.",
            "low",
        ),
    }
    for key, detector in detectors.items():
        if not detector or detector.get("weighted_share", 0) <= 0 or key not in labels:
            continue
        title, category, proposal, risk = labels[key]
        share = detector["weighted_share"]
        result[category].append(
            {
                "category": category,
                "title": f"{title}: {share:.1%} measured share",
                "proposal": (
                    f"{proposal} Risk: {risk}. This is measured spend exposure, "
                    "not estimated savings."
                ),
                "evidence": _evidence(key, detector, sessions, waste_records),
            }
        )
    return result


def _evidence(
    name: str,
    detector: dict[str, Any],
    sessions: list[dict[str, Any]],
    waste_records: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Return sessions contributing to a detector, ordered by measured spend."""
    rows_by_id = {item["session_id"]: item for item in sessions}
    if name.startswith("context_over_"):
        threshold = detector.get("thresholds", {}).get("context_tokens", 0)
        matching = [
            item
            for item in sessions
            if any(row.get("context_size", 0) >= threshold for row in item["rows"])
        ]
    elif name == "subagent":
        matching = [item for item in sessions if "subagent" in item.get("role", "")]
    elif name == "repeated_review_rounds":
        ids = _repeat_review_ids(waste_records)
        matching = [item for item in sessions if item["session_id"] in ids]
    elif name in {"poll_watch_msg_read_sleep", "msg_send"}:
        category = "poll" if name.startswith("poll") else "msg_send"
        matching = [
            item
            for item in sessions
            if any(
                _tool_category(tool) == category for tool in item.get("tool_names", [])
            )
        ]
    elif name == "cache_rebuild_after_idle":
        matching = [item for item in sessions if _has_cache_rebuild(item)]
    elif name == "startup_prompt":
        matching = [item for item in sessions if item.get("rows")]
    else:
        matching = []
    matching.sort(key=lambda item: -item["totals"]["weighted"])
    return [
        {
            "harness": rows_by_id[item["session_id"]]["harness"],
            "session_id": item["session_id"],
        }
        for item in matching[:10]
    ]


def _tool_category(name: Any) -> str | None:
    if not isinstance(name, str):
        return None
    lowered = name.lower()
    if lowered in {"monitor", "taskoutput", "schedulewakeup", "croncreate", "sleep"}:
        return "poll"
    if lowered in {"msg-send", "msg_send", "varde_msg_send"}:
        return "msg_send"
    if "poll" in lowered or "watch" in lowered or "sleep" in lowered:
        return "poll"
    return "other"


def _repeat_review_ids(records: list[dict[str, Any]]) -> set[str]:
    by_target: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for record in records:
        if record.get("role") == "reviewer/checker" and record.get("target"):
            by_target[record["target"]][record["session_id"]].extend(
                record.get("rows", [])
            )
    repeated = set()
    for sessions_by_id in by_target.values():
        ordered = sorted(
            sessions_by_id,
            key=lambda session_id: min(
                (row.get("timestamp") or "") for row in sessions_by_id[session_id]
            ),
        )
        repeated.update(ordered[1:])
    return repeated


def _has_cache_rebuild(session: dict[str, Any]) -> bool:
    from datetime import UTC

    calls = sorted(session["rows"], key=lambda row: row.get("timestamp") or "")
    previous = None
    for row in calls:
        try:
            current = datetime.fromisoformat(row["timestamp"])
        except KeyError, TypeError, ValueError:
            continue
        if current.tzinfo is None:
            current = current.replace(tzinfo=UTC)
        if (
            previous is not None
            and (current - previous).total_seconds() > 3600
            and row.get("cache_write", 0) > 60_000
        ):
            return True
        previous = current
    return False


def render(data: dict[str, Any], comparison: dict[str, Any]) -> str:
    """Render the compact markdown Token spend section."""
    lines = [
        "## Token spend",
        "",
        (
            "Weighted spend uses relative price ratios: input 1, cache read 0.1, "
            "cache write 2, output 5. These are not the provider's real "
            "allowance formula."
        ),
        "",
        f"Unattributed plan share: {data['unattributed_share']:.1%}.",
        "",
        "Per-harness sessions in window: "
        + "; ".join(
            _coverage_text(harness, counts)
            for harness, counts in data["coverage"].items()
        )
        + ". Session-total usage is reported as coverage but excluded from "
        "call-level totals.",
        "",
        (
            "Verified against a reference for Claude only; Codex, Pi and OpenCode "
            "are not cross-checked and may undercount long sessions."
        ),
        "",
    ]
    if comparison["status"] in {"no_previous", "not_comparable"}:
        lines.append(comparison["message"])
    else:
        lines.append("Comparison noise threshold: 5% relative change.")
        for key, value in comparison["metrics"].items():
            if value["change"] == "unavailable":
                lines.append(f"{key}: unavailable (missing from one snapshot).")
            else:
                lines.append(f"{key}: {value['change']} ({value['delta']:+g}).")
    for title, rows in (
        ("By role", data["by_role"]),
        ("By session (top 10)", data["top_sessions"]),
        ("By plan", data["by_plan"]),
    ):
        lines.extend(
            (
                "",
                f"### {title}",
                "",
                (
                    "| Name | Sessions | Calls | Cache read | Cache write | Output | "
                    "Weighted | Share |"
                ),
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            )
        )
        for row in rows:
            label = row["name"] if "name" in row else row["session_id"][:8]
            share = row.get("share")
            if share is None:
                total = data["snapshot"]["totals"]["weighted"]
                share = row["weighted"] / total if total else 0
            lines.append(
                f"| {label} | {row.get('sessions', 1)} | {row['calls']} | "
                f"{row['cache_read']} | {row['cache_write']} | {row['output']} | "
                f"{row['weighted']:.0f} | {share:.1%} |"
            )
    return "\n".join(lines) + "\n"


def _coverage_text(harness: str, counts: dict[str, int]) -> str:
    if counts["sessions"] == 0:
        return f"{harness}: no sessions in window"
    return (
        f"{harness}: {counts['sessions']} sessions, {counts['per_call']} per-call, "
        f"{counts['session_total']} session-total, {counts['no_usage']} no usage data, "
        f"{counts['inspection_failed']} inspection failed"
    )


def write_snapshot(store: str | Path, run_date: str, snapshot: dict[str, Any]) -> Path:
    """Persist redacted aggregate snapshot beside its report."""
    path = Path(store) / "reviews" / f"{run_date}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    safe = redact_value(snapshot)
    path.write_text(json.dumps(safe, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def read_previous(store: str | Path, run_date: str) -> dict[str, Any] | None:
    directory = Path(store) / "reviews"
    for path in sorted(directory.glob("????-??-??.json"), reverse=True):
        if path.stem >= run_date:
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except OSError, json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    return None
