"""Append-only comment log parsing, folding, and storage."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def parse_comments(text: str) -> list[dict[str, Any]]:
    rows = []
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError, TypeError:
            continue
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            rows.append(row)
    return fold_comments(rows)


def fold_comments(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    comments: dict[str, dict[str, Any]] = {}
    for row in rows:
        comment_id = row.get("id")
        if not isinstance(comment_id, str):
            continue
        if row.get("event") == "addressed":
            if comment_id in comments:
                comments[comment_id]["state"] = "addressed"
                if isinstance(row.get("note"), str):
                    comments[comment_id]["resolution_note"] = row["note"]
        elif row.get("state") in {"open", "resolved"} and comment_id in comments:
            comments[comment_id]["state"] = row["state"]
        elif row.get("state") in {"open", "addressed"} and isinstance(
            row.get("text"), str
        ):
            comments[comment_id] = {
                key: value
                for key, value in row.items()
                if key
                in {"id", "ts", "target", "text", "state", "kind", "actor", "sender"}
            }
    return list(comments.values())


def append_event(path: Path, row: dict[str, Any]) -> None:
    encoded = (
        json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        written = os.write(descriptor, encoded)
        if written != len(encoded):
            raise OSError("incomplete comment append")
    finally:
        os.close(descriptor)


def read_comments(path: Path) -> list[dict[str, Any]]:
    try:
        return parse_comments(path.read_text(encoding="utf-8"))
    except OSError, UnicodeError:
        return []
