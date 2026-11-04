"""CLI adapter for message status reporting."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from varde_data.config import load_data_config
from varde_data.messages import read_stray_messages
from varde_data.open import open_data

from varde_workflow.msg_status import filter_retired, find_stray_stores, load_report


def status_messages(inbox: Path) -> list[dict[str, Any]]:
    from varde_workflow.msg_status import status_messages as read_status_messages

    return read_status_messages(inbox)


def run(args, working: str | Path) -> int:
    try:
        now = datetime.fromisoformat(args.now) if args.now else datetime.now(UTC)
        report = load_report(str(working), now)
        retired = open_data(
            Path(working), load_data_config()
        ).addresses.retired_records()
        report = filter_retired(report, retired)
        from varde_learn.knowledge.memory import find_root

        root = find_root(Path.cwd())
        for path in find_stray_stores(root, Path(working)):
            messages, _skipped = read_stray_messages(path)
            if messages:
                print(f"Warning: stray message store found at {path}", file=sys.stderr)
        print(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)
            if args.json
            else _text(report)
        )
        return int(report["exit_code"])
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 70


def _text(report: dict[str, Any]) -> str:
    lines = [f"runner relay: {report['runner_relay']}"]
    lines.extend(
        f"{row['address']}: {row['total']} total, {row['unread']} unread, "
        f"{row['delivered_not_acked']} delivered-not-acked, "
        f"{_format_age(row['oldest_undelivered_age_seconds'])} oldest undelivered"
        for row in report["addresses"]
    )
    suspect = sum(item.get("suspect", 0) for item in report["messages"])
    misdelivered = sum(item.get("misdelivered", 0) for item in report["messages"])
    lines.append(f"suspect: {suspect}, misdelivered: {misdelivered}")
    for item in report["stopped_reading"]:
        suffix = (
            f"; newer binding {item['newer_binding']}" if item["newer_binding"] else ""
        )
        lines.append(f"{item['address']}: stopped reading{suffix}")
    return "\n".join(lines) if lines else "No messages."


def _format_age(seconds: float | None) -> str:
    if seconds is None:
        return "none"
    return f"{int(seconds)}s"
