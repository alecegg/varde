"""Watchers: each scan returns (kind, subject, data) tuples for new changes."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from varde_learn.docs.pages.comments import ANSWER_KINDS, fold, read_rows
from varde_learn.knowledge.frontmatter import parse

from varde_serve.events.buffer import EventBuffer
from varde_serve.files import files_with_suffix

Change = tuple[str, str, dict[str, Any]]
Watcher = Callable[[], list[Change]]


def doc_comment_watcher(root: Path) -> Watcher:
    """Emit doc.comment and doc.decision for comments that appear after start."""
    seen: set[str] = set()
    primed = False

    def scan() -> list[Change]:
        nonlocal primed
        changes: list[Change] = []
        for log in files_with_suffix(root, ".comments.jsonl"):
            doc = log.with_name(log.name.removesuffix(".comments.jsonl"))
            subject = doc.relative_to(root).as_posix()
            for comment in fold(read_rows(doc)):
                key = f"{subject}#{comment['id']}"
                if key in seen:
                    continue
                seen.add(key)
                if primed:
                    kind = (
                        "doc.decision"
                        if comment.get("kind") in ANSWER_KINDS
                        else "doc.comment"
                    )
                    changes.append((kind, subject, comment))
        primed = True
        return changes

    return scan


def _plan_snapshot(root: Path) -> dict[str, dict[str, str]]:
    states: dict[str, dict[str, str]] = {}
    for plan_file in sorted((root / "plans").rglob("plan.md")):
        try:
            fields, _ = parse(plan_file.read_bytes())
        except OSError, ValueError:
            continue
        states[plan_file.parent.name] = {"status": str(fields.get("status", ""))}
        for task in sorted((plan_file.parent / "tasks").glob("*.md")):
            with contextlib.suppress(OSError, ValueError):
                task_fields, _ = parse(task.read_bytes())
                states[plan_file.parent.name][task.stem] = str(
                    task_fields.get("status", "")
                )
    return states


def plan_state_watcher(root: Path) -> Watcher:
    """Emit plan.state when a plan's or task's status changes."""
    previous: dict[str, dict[str, str]] | None = None

    def scan() -> list[Change]:
        nonlocal previous
        current = _plan_snapshot(root)
        changed = (
            []
            if previous is None
            else [
                ("plan.state", plan_id, {"states": state})
                for plan_id, state in current.items()
                if previous.get(plan_id) != state
            ]
        )
        previous = current
        return changed

    return scan


def run_watchers(buffer: EventBuffer, watchers: list[Watcher]) -> int:
    """Run every watcher once and publish what it found; return the count."""
    count = 0
    for watcher in watchers:
        for kind, subject, data in watcher():
            buffer.publish(kind, subject, data)
            count += 1
    return count


async def poll_loop(
    buffer: EventBuffer, watchers: list[Watcher], seconds: float
) -> None:
    """Scan on a thread every `seconds`; a failing watcher never kills the loop."""
    while True:
        with contextlib.suppress(Exception):
            await asyncio.to_thread(run_watchers, buffer, watchers)
        await asyncio.sleep(seconds)
