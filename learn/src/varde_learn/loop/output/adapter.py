"""Harness command construction and raw response normalization."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from varde_learn.loop.redact import apply as redact_text


def args(
    harness: str, model: str | None, prompt: str, cwd: Path, judge: bool = False
) -> list[str]:
    if harness == "claude":
        result = [
            "-p",
            prompt,
            "--output-format",
            "json",
            "--disable-slash-commands",
            "--setting-sources",
            "local" if judge else "project,local",
        ]
        if model:
            result += ["--model", model]
        return result
    result = [
        "exec",
        "--json",
        "--ephemeral",
        "--ignore-user-config",
        "--skip-git-repo-check",
        "-c",
        "project_doc_max_bytes=0",
    ]
    if model:
        result += ["--model", model]
    result += ["--sandbox", "read-only"] if judge else ["--approve-for-me"]
    for feature in ("plugins", "hooks", "memories"):
        result += ["--disable", feature]
    result += [
        "-",
    ]
    return result


def normalize_codex(text: str) -> dict[str, Any]:
    started = completed = False
    result = ""
    content: list[dict[str, Any]] = []
    usage: Any = None
    for line in text.splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if completed:
            raise ValueError("Codex events appeared after terminal turn")
        kind = event.get("type")
        if kind in ("thread.started", "warning"):
            continue
        if kind == "turn.started" and not started:
            started = True
        elif kind in ("item.started", "item.updated", "item.completed") and started:
            item = event.get("item")
            if not isinstance(item, dict) or not isinstance(item.get("type"), str):
                raise ValueError("Missing Codex item")
            if item["type"] == "agent_message" and kind == "item.completed":
                if not isinstance(item.get("text"), str):
                    raise ValueError("Missing agent message text")
                result = item["text"]
            elif item["type"] in {
                "command_execution",
                "file_change",
                "mcp_tool_call",
                "collab_tool_call",
                "web_search",
            }:
                content.append(
                    {
                        "type": "tool_use",
                        "name": item["type"],
                        "event_type": kind,
                        "input": {"event_type": kind, "item": item},
                    }
                )
        elif kind == "turn.completed" and started:
            completed, usage = True, event.get("usage")
        elif kind in ("turn.failed", "error"):
            raise ValueError(f"Codex run failed: {event}")
        else:
            raise ValueError(f"Unexpected Codex event: {event}")
    if not completed:
        raise ValueError("Codex trace has no completed terminal turn")
    return {"result": result, "messages": [{"content": content}], "usage": usage}


def read_raw(
    harness: str, stream_path: Path, raw_path: Path
) -> tuple[dict[str, Any], None]:
    text = stream_path.read_text()
    if harness == "codex":
        value = normalize_codex(text)
        raw_path.write_text(json.dumps(value, indent=2))
        return value, None
    value = json.loads(text)
    if (
        not isinstance(value, dict)
        or value.get("type") != "result"
        or value.get("subtype") != "success"
        or value.get("is_error") is not False
        or not isinstance(value.get("result"), str)
    ):
        raise ValueError("Claude response is not a successful result")
    return value, None


def redact_file(path: Path) -> int:
    if not path.is_file():
        return 0
    result = redact_text(path.read_text())
    path.write_text(result.text)
    return result.count
