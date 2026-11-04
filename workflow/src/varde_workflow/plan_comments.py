"""Read and print comments stored with workflow plans."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from varde_data.paths import plan_comments_path
from varde_learn.knowledge.memory import MemoryPaths


def comments_path(plan_path: Path) -> Path:
    return plan_comments_path(plan_path)


def read_comments(path: Path) -> list[dict[str, Any]]:
    """Fold comment state events while ignoring incomplete or invalid lines."""
    comments: dict[str, dict[str, Any]] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError, UnicodeError:
        return []
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            continue
        comment_id = row["id"]
        if row.get("event") == "addressed":
            if comment_id in comments:
                comments[comment_id]["state"] = "addressed"
                if isinstance(row.get("note"), str):
                    comments[comment_id]["resolution_note"] = row["note"]
            continue
        if row.get("state") in {"open", "resolved"} and comment_id in comments:
            comments[comment_id]["state"] = row["state"]
            continue
        if row.get("state") not in {"open", "addressed"}:
            continue
        if not isinstance(row.get("text"), str):
            continue
        comments[comment_id] = {
            key: value
            for key, value in row.items()
            if key in {"id", "ts", "target", "text", "state", "kind", "actor", "sender"}
        }
    return list(comments.values())


def open_comment_count(plan_path: Path) -> int:
    return sum(
        comment.get("state") == "open"
        for comment in read_comments(comments_path(plan_path))
    )


def run(args: Any) -> int:
    from varde_workflow.commands.now import resolve_plan

    cwd = Path.cwd()
    plans = MemoryPaths.resolve(cwd).working.path / "plans"
    try:
        plan_path = resolve_plan(args.plan, cwd, plans)
        comments = read_comments(comments_path(plan_path))
    except (OSError, ValueError) as exc:
        print(f"varde plan comments: {exc}")
        return 2
    if args.open:
        comments = [comment for comment in comments if comment.get("state") == "open"]
    if not comments:
        print("No comments.")
        return 0
    for comment in comments:
        delivery = (
            "delivered"
            if comment.get("kind") in ("sent", "delivered")
            else "saved for when work starts"
        )
        target = comment.get("target") or "plan"
        print(
            f"{comment['id']} [{comment.get('state', 'open')}] ({delivery}) "
            f"{target}: {comment['text']}"
        )
    return 0
