"""Pure helpers for classifying permission requests and decision cards."""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import PurePosixPath
from typing import Any

SUPPORTED_GROUPS = frozenset(
    {"role", "model", "harness", "request_kind", "card_kind", "day", "week"}
)


def _find(payload: Any, keys: set[str]) -> Any:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key.lower() in keys and isinstance(value, str):
                return value
        for value in payload.values():
            found = _find(value, keys)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _find(value, keys)
            if found is not None:
                return found
    return None


def classify_request_kind(payload: dict[str, Any]) -> str:
    if _find(payload, {"command", "cmd", "shell"}) is not None:
        return "command_prefix"
    if _find(payload, {"path", "file_path", "directory"}) is not None:
        return "path_scope"
    if _find(payload, {"url", "uri", "host", "hostname"}) is not None:
        return "network"
    if _find(payload, {"credential", "secret", "token", "password"}) is not None:
        return "credential"
    if _find(payload, {"scope", "permissions"}) is not None:
        return "scope_change"
    return "other"


def redact_request_key(
    kind: str, payload: dict[str, Any], workspace_root: str | None = None
) -> str:
    if kind == "command_prefix":
        command = _find(payload, {"command", "cmd", "shell"}) or ""
        words = command.split()
        while words and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0]):
            words.pop(0)
        candidate = words[0] if words else ""
        prefix = (
            candidate
            if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,31}", candidate)
            and not _is_secret_like(candidate)
            else "*"
        )
        return f"{kind}:{prefix}"
    if kind == "path_scope":
        value = _find(payload, {"path", "file_path", "directory"})
        if not value:
            return f"{kind}:*"
        path = PurePosixPath(value)
        if not workspace_root:
            return f"{kind}:*"
        root = PurePosixPath(workspace_root)
        try:
            relative = path.relative_to(root) if root else path
        except ValueError:
            return f"{kind}:*"
        # The final path component is always treated as a file name and dropped.
        parts = relative.parts[:-1][:2]
        parts = tuple(
            part
            if re.fullmatch(r"[A-Za-z0-9_-]{1,32}", part) and not _is_secret_like(part)
            else "*"
            for part in parts
        )
        return f"{kind}:{'/'.join(parts) if parts else '*'}"
    return kind


def _is_secret_like(value: str) -> bool:
    return bool(
        re.search(
            r"token|secret|password|credential|api.?key|(?:^|-)sk-(?:live|proj|ant)-|\bgh[pousr]_[A-Za-z0-9]+",
            value,
            re.IGNORECASE,
        )
    )


def plan_from_branch(branch: str | None) -> str | None:
    if not branch or not branch.startswith("worktree/"):
        return None
    plan = branch.removeprefix("worktree/")
    return plan or None


def card_kind_for(decision: dict[str, Any]) -> str:
    kind = decision.get("kind")
    context = decision.get("context")
    context = context if isinstance(context, dict) else {}
    if kind in {"merge", "merge_ready"}:
        return "merge"
    if kind == "design_decision":
        return "design_decision"
    if kind == "plan_question" or (
        decision.get("plan_id")
        and (context.get("type") == "question" or context.get("question"))
    ):
        return "plan_question"
    return "other"


def response_for_answer(answer: str, decision: dict[str, Any]) -> str | None:
    context = decision.get("context")
    context = context if isinstance(context, dict) else {}
    if decision.get("kind") != "approval" and context.get("type") != "approval":
        return "approve"
    first_line = answer.strip().splitlines()
    normalized = first_line[0].strip().lower() if first_line else ""
    if normalized in {"approve", "approved"} or normalized.startswith("approved:"):
        return "approve"
    if normalized in {"deny", "hold"} or normalized.startswith("hold:"):
        return "deny"
    if normalized in {"ask-more", "ask_more"} or normalized.startswith("ask-more:"):
        return "ask_more"
    return None


def summarize(
    rows: list[dict[str, Any]], group_by: str, since: str | None = None
) -> list[dict[str, Any]]:
    """Aggregate decision rows by a supported dimension or time bucket."""
    fields = SUPPORTED_GROUPS - {"day", "week"}
    if group_by not in SUPPORTED_GROUPS:
        raise ValueError(f"unsupported group_by: {group_by}")
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if since and str(row.get("created_at", "")) < since:
            continue
        value = row.get(group_by) if group_by in fields else _time_bucket(row, group_by)
        grouped[str(value) if value is not None else "unknown"].append(row)
    result = []
    for key, items in sorted(grouped.items()):
        counts = {
            response: sum(row.get("response") == response for row in items)
            for response in ("approve", "deny", "ask_more", "expired")
        }
        answered = [
            row["time_to_answer_s"]
            for row in items
            if isinstance(row.get("time_to_answer_s"), (int, float))
        ]
        result.append(
            {
                "group": key,
                "count": len(items),
                "responses": counts,
                "approve_rate": counts["approve"] / len(items),
                "deny_rate": counts["deny"] / len(items),
                "expired_rate": counts["expired"] / len(items),
                "median_time_to_answer_s": _median(answered),
            }
        )
    return result


def candidates(rows: list[dict[str, Any]], min_approvals: int = 3) -> list[str]:
    totals: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in rows:
        key = row.get("request_key")
        if key:
            totals[str(key)][str(row.get("response") or "pending")] += 1
    return sorted(
        key
        for key, counts in totals.items()
        if counts["approve"] >= min_approvals
        and not counts["deny"]
        and not counts["ask_more"]
    )


def _time_bucket(row: dict[str, Any], group_by: str) -> str:
    try:
        date = datetime.fromisoformat(str(row["created_at"]))
    except KeyError, ValueError:
        return "unknown"
    if group_by == "week":
        date = date.replace(hour=0, minute=0, second=0, microsecond=0)
        date = date - timedelta(days=date.weekday())
    return date.date().isoformat()


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[middle])
    return (ordered[middle - 1] + ordered[middle]) / 2
