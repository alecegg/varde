"""Codex trace validation and implicit skill-read scoring."""

from __future__ import annotations

from pathlib import Path

from varde_learn.loop.trigger import contains_auth_phrase, parse_events

KNOWN_EVENTS = {
    "thread.started",
    "turn.started",
    "turn.completed",
    "turn.failed",
    "item.started",
    "item.updated",
    "item.completed",
    "warning",
    "error",
}
KNOWN_ITEMS = {
    "agent_message",
    "command_execution",
    "file_change",
    "web_search",
    "mcp_tool_call",
    "reasoning",
    "todo_list",
    "plan",
    "collab_tool_call",
}


def parse_codex(trace: bytes, skill_path: Path) -> bool:
    events = parse_events(trace)
    target = str(skill_path)
    pending: set[str] = set()
    counts = {"thread.started": 0, "turn.started": 0, "turn.completed": 0}
    hit = False
    for event in events:
        if not isinstance(event, dict) or event.get("type") not in KNOWN_EVENTS:
            raise ValueError("unusable Codex trace")
        kind = event["type"]
        if kind in ("turn.failed", "error"):
            raise ValueError("unusable Codex trace")
        if kind == "thread.started" and isinstance(event.get("thread_id"), str):
            counts[kind] += 1
        if kind in ("turn.started", "turn.completed"):
            counts[kind] += 1
        if kind == "warning" and not isinstance(event.get("message"), str):
            raise ValueError("unusable Codex trace")
        if kind.startswith("item."):
            item = event.get("item")
            if (
                not isinstance(item, dict)
                or item.get("type") not in KNOWN_ITEMS
                or not isinstance(item.get("id"), str)
            ):
                raise ValueError("unusable Codex trace")
            if item["type"] == "agent_message" and (
                not isinstance(item.get("text"), str)
                or contains_auth_phrase(item["text"])
            ):
                raise ValueError("unusable Codex trace")
            if item["type"] != "command_execution":
                continue
            if not isinstance(item.get("command"), str):
                raise ValueError("unusable Codex trace")
            if kind == "item.started":
                if item.get("status") not in (None, "in_progress"):
                    raise ValueError("unusable Codex trace")
                pending.add(item["id"])
            if kind == "item.completed":
                if item.get("status") not in ("completed", "failed") or not isinstance(
                    item.get("exit_code"), int
                ):
                    raise ValueError("unusable Codex trace")
                pending.discard(item["id"])
                if target in item["command"]:
                    if item["status"] != "completed" or item["exit_code"] != 0:
                        raise ValueError("unusable Codex trace")
                    hit = True
    if (
        counts != {"thread.started": 1, "turn.started": 1, "turn.completed": 1}
        or pending
    ):
        raise ValueError("unusable Codex trace")
    return hit
