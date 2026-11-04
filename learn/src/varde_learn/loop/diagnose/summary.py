"""Compact multi-session metrics and waste summary."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .. import analyzed
from ..calls import HARNESS_SESSION_VARS
from ..improve.tool_bypass import bypass_metric, load_rows
from ..skill_runs import skill_runs
from ..store.paths import resolve_store_dir
from .list import ListRequest, list_sessions
from .metrics import (
    _is_tool_call,
    _is_tool_error,
    _paired_records,
    session_metrics,
    waste_signals,
)
from .model import harness_adapter


def _roots() -> dict[str, Path]:
    from ..cli_diagnose import _opencode_root

    return {
        "codex": Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")),
        "claude": Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
        / "projects",
        "opencode": _opencode_root(),
    }


def summarize(options: dict[str, Any]):
    roots = _roots()
    harnesses = (
        ("codex", "claude", "opencode")
        if options["harness"] == "all"
        else (options["harness"],)
    )
    for name in harnesses:
        harness_adapter(name)
    listing = list_sessions(
        ListRequest(
            options["harness"],
            Path(options["repository"]),
            roots["codex"],
            roots["claude"],
            roots["opencode"],
            paseo_home=Path(os.environ["PASEO_HOME"])
            if os.environ.get("PASEO_HOME")
            else None,
            limit=int(options.get("limit", 5)),
        )
    )
    bypass_rows, bypass_notice = load_rows()
    warnings = [*listing.warnings, *([bypass_notice] if bypass_notice else [])]
    store = resolve_store_dir()
    done = (
        {(record["harness"], record["session"]) for record in analyzed.read_all(store)}
        if options.get("new")
        else set()
    )
    own = {os.environ.get(name) for name in HARNESS_SESSION_VARS} - {None, ""}
    sessions = []
    errors = []
    per_session = []
    processed = []
    for item in listing.sessions:
        key = (item.harness, item.session_id)
        if item.session_id in own or key in done:
            continue
        try:
            request = SimpleNamespace(
                root=roots[item.harness],
                source_root=roots[item.harness],
                projects_root=roots[item.harness],
                session_id=item.session_id,
                path=Path(item.path) if item.path else None,
            )
            inspected = harness_adapter(item.harness).inspect(request)
            records = inspected.records
            metrics: dict[str, Any] = dict(session_metrics(records))
            signals = waste_signals(records)
            anchors = [
                anchor["index"] for signal in signals for anchor in signal.anchors
            ]
            skills = skill_runs(records, anchors)
            if skills:
                metrics["skills"] = skills
            bypass = bypass_metric(records, item.session_id, bypass_rows)
            if bypass:
                metrics["tool_bypass"] = bypass
            session = {"id": item.session_id, "harness": item.harness, **metrics}
            sessions.append(session)
            tool_errors = session_errors(records)
            if tool_errors:
                errors.append(
                    {
                        "id": item.session_id,
                        "harness": item.harness,
                        "errors": [row["message"] for row in tool_errors],
                        "anchors": [
                            {"session": item.session_id, **row["anchor"]}
                            for row in tool_errors
                        ],
                    }
                )
            per_session.append((item.session_id, signals))
            processed.append(key)
        except Exception as error:  # noqa: BLE001 - isolate failures to one session
            errors.append(
                {
                    "id": item.session_id,
                    "harness": item.harness,
                    "error": str(error)[:150],
                    "anchors": [
                        {"session": item.session_id, "index": 0, "timestamp": None}
                    ],
                }
            )
    candidates = aggregate_patterns(per_session)
    if options.get("mark"):
        now = datetime.now(UTC).isoformat()
        for harness, session_id in processed:
            metrics = next(
                (
                    row
                    for row in sessions
                    if (row["harness"], row["id"]) == (harness, session_id)
                ),
                {},
            )
            kinds = [
                signal.kind
                for sid, signals in per_session
                if sid == session_id
                for signal in signals
            ]
            analyzed.mark(
                store,
                harness,
                session_id,
                now,
                "diagnose summary",
                metrics,
                friction_added=kinds,
            )
    data = {
        "sessions": sessions,
        "errors": errors,
        "waste_candidates": candidates,
        "top_patterns": candidates[:3],
    }
    return (
        data,
        {"truncated": bool(listing.warnings), "warnings": warnings},
        format_text(data),
    )


def aggregate_patterns(per_session):
    patterns = {}
    for session_id, signals in per_session:
        for signal in signals:
            pattern = patterns.setdefault(
                signal.kind,
                {
                    "kind": signal.kind,
                    "estimated_tokens": 0,
                    "sessions": [],
                    "anchors": [],
                },
            )
            pattern["estimated_tokens"] += signal.cost_tokens
            pattern["sessions"].append(session_id)
            pattern["anchors"].extend(
                {"session": session_id, **anchor} for anchor in signal.anchors[:3]
            )
    return sorted(
        (
            {
                **p,
                "session_count": len(set(p["sessions"])),
                "friction_candidate": len(set(p["sessions"])) >= 3,
            }
            for p in patterns.values()
        ),
        key=lambda row: row["estimated_tokens"],
        reverse=True,
    )


def session_errors(records):
    """Failed tool calls, counted the same way as session_metrics."""
    errors = []
    for index, row in enumerate(_paired_records(list(records))):
        if not (_is_tool_call(row) and _is_tool_error(row)) or len(errors) >= 3:
            continue
        message = row.get("tool_error") or row.get("tool_status")
        errors.append(
            {
                "message": " ".join(str(message).split())[:100],
                "anchor": {"index": index, "timestamp": row.get("timestamp")},
            }
        )
    return errors


def format_text(data):
    sessions, errors, candidates = (
        data["sessions"],
        data["errors"],
        data["waste_candidates"],
    )
    lines = ["ID  HARNESS  CALLS  WALL(s)  INPUT  CACHED  OUTPUT  PEAK  ERRORS"]
    lines.extend(
        (
            f"{row['id']}  {row['harness']}  {row['model_calls']}  "
            f"{row['wall_seconds']:.1f}  {row['input_tokens']}  "
            f"{row['cached_input_tokens']}  {row['output_tokens']}  "
            f"{row['peak_context']}  {row['tool_errors']}"
        )
        for row in sessions
    )
    lines.extend(
        f"SKILL {row['id']} {name}: loads={len(entry['loads'])} "
        f"post_errors={entry['post_errors']} suspected_skip={entry['suspected_skip']}"
        for row in sessions
        for name, entry in row.get("skills", {}).items()
    )
    lines.extend(
        (
            f"ERROR {row['harness']} {row['id']}: "
            f"{row.get('error', '; '.join(row.get('errors', [])))}"
        )
        for row in errors
    )
    lines.extend(
        (
            f"WASTE {row['kind']}: ~{row['estimated_tokens']} tokens across "
            f"{row['session_count']} sessions"
        )
        for row in candidates
    )
    return "\n".join(lines)
