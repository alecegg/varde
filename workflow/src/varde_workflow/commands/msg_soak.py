"""Gather inbox and plan records for the mail reliability soak report."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from varde_data.config import load_data_config
from varde_data.messages import mirror_parity
from varde_data.open import open_data
from varde_learn.knowledge.frontmatter import parse

from varde_workflow.commands.msg_status import status_messages
from varde_workflow.execution_wave_tools import git
from varde_workflow.inbox import delivery_events
from varde_workflow.merge_state import branch_exists, is_merged
from varde_workflow.msg_status import filter_retired, load_report, parse_time
from varde_workflow.nudges import load as load_nudges
from varde_workflow.relay_state import load as load_relay
from varde_workflow.slots import is_orchestrator_slot
from varde_workflow.soak import evaluate


def _repository_root(cwd: Path) -> Path:
    result = git(cwd, ["rev-parse", "--show-toplevel"])
    return Path(result[1].strip()) if result and result[1].strip() else cwd


def _approved_merges(working: Path, repository: Path) -> list[dict[str, Any]]:
    results = []
    plans = working / "plans"
    paths = sorted(plans.rglob("plan.md")) if plans.is_dir() else []
    for path in paths:
        try:
            metadata, _ = parse(path.read_bytes())
        except OSError, ValueError:
            continue
        approved_at = metadata.get("merge_approved_at")
        if not approved_at:
            continue
        branch = metadata.get("branch")
        if not isinstance(branch, str) or not branch:
            branch = f"worktree/{metadata.get('id', path.parent.name)}"
        # A deleted branch is unknown to watch and must not keep the guard
        # failing forever.
        merged = not branch_exists(repository, branch) or is_merged(repository, branch)
        results.append(
            {
                "plan": str(path.parent.relative_to(plans)),
                "approved_at": approved_at,
                "merged": merged,
            }
        )
    return results


def _resolve_readers(
    messages: list[dict[str, Any]], deliveries: list[dict[str, Any]], working: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    addresses = open_data(working, load_data_config()).addresses
    resolved_messages = []
    for message in messages:
        resolved = dict(message)
        for key in ("to", "from"):
            if isinstance(resolved.get(key), str):
                resolved[key] = addresses.resolve_alias(resolved[key])
        resolved_messages.append(resolved)
    resolved_deliveries = []
    for delivery in deliveries:
        resolved = dict(delivery)
        reader = resolved.get("reader")
        if isinstance(reader, str):
            resolved["reader"] = addresses.resolve_alias(reader)
        resolved_deliveries.append(resolved)
    return resolved_messages, resolved_deliveries


def _open_requests(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item
        for item in messages
        if item.get("to") == "main"
        and item.get("kind") in {"blocked", "needs-user"}
        and not item.get("_below_watermark")
    ]


def _prior_days(working: Path, today: str) -> list[dict[str, Any]]:
    directory = working / "metrics" / "mail-soak"
    result = []
    if not directory.is_dir():
        return result
    for path in sorted(directory.glob("*.json")):
        if path.stem >= today:
            continue
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except OSError, ValueError:
            continue
        if isinstance(report, dict) and isinstance(report.get("all_ok"), bool):
            result.append({"date": path.stem, "all_ok": report["all_ok"]})
    return result


def _ordered_relay_events(
    deliveries: list[dict[str, Any]], sleeps: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    indexed = [(index, item) for index, item in enumerate([*deliveries, *sleeps])]

    def order(entry: tuple[int, dict[str, Any]]) -> tuple[bool, datetime, int]:
        index, item = entry
        try:
            timestamp = parse_time(str(item.get("at", ""))).astimezone(UTC)
        except ValueError:
            return True, datetime.max.replace(tzinfo=UTC), index
        return False, timestamp, index

    return [item for _, item in sorted(indexed, key=order)]


def _active_orchestrators(
    messages: list[dict[str, Any]],
    deliveries: list[dict[str, Any]],
    live_addresses: set[str],
    today: datetime,
) -> int:
    active = set()
    for message in messages:
        timestamp = _timestamp(message.get("ts"))
        if timestamp is None or timestamp.date() != today.date():
            continue
        for key in ("to", "from"):
            address = message.get(key)
            if isinstance(address, str) and is_orchestrator_slot(address):
                active.add(address)
    for event in deliveries:
        timestamp = _timestamp(event.get("at"))
        address = event.get("reader")
        if (
            timestamp is not None
            and timestamp.date() == today.date()
            and isinstance(address, str)
            and is_orchestrator_slot(address)
        ):
            active.add(address)
    active.update(
        address
        for address in live_addresses
        if address != "main" and is_orchestrator_slot(address)
    )
    return len(active)


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return parse_time(value).astimezone(UTC)
    except ValueError:
        return None


def load_retired(working: str | Path) -> dict[str, str]:
    """Return retired address timestamps from the shared address repository."""
    return dict(
        open_data(Path(working), load_data_config()).addresses.retired_records()
    )


def gather(
    working: str | Path,
    now: datetime,
    repository: Path,
    *,
    window_days: int = 7,
) -> dict[str, Any]:
    """Read plain records without changing inbox or plan state."""
    root = Path(working)
    inbox = root / ".cache" / "inbox"
    messages = status_messages(inbox)
    deliveries = delivery_events(root)
    messages, deliveries = _resolve_readers(messages, deliveries, root)
    relay = load_relay(root)
    sleeps = [
        item
        for item in relay.get("events", [])
        if isinstance(item, dict) and item.get("event") == "slept"
    ]
    relay_events = _ordered_relay_events(deliveries, sleeps)
    relay_events.extend(
        item
        for item in relay.get("events", [])
        if isinstance(item, dict) and item.get("event") == "send-liveness"
    )
    status = load_report(str(root), now)
    status = filter_retired(status, load_retired(root))
    live_addresses = open_data(root, load_data_config()).addresses.live_addresses(now)
    parity = mirror_parity(
        root,
        load_data_config().backends.get("messages", "files"),
        window=window_days,
    )
    return {
        **({"parity": parity} if parity is not None else {}),
        "messages": messages,
        "deliveries": deliveries,
        "relay_events": relay_events,
        "live_addresses": live_addresses,
        "nudges": load_nudges(root),
        "status": {"exit_code": status.get("exit_code", 1)},
        "approved_merges": _approved_merges(root, repository),
        "open_requests": _open_requests(messages),
        "active_orchestrators_today": _active_orchestrators(
            messages, deliveries, live_addresses, now.astimezone(UTC)
        ),
        "prior_days": _prior_days(root, now.astimezone(UTC).date().isoformat()),
    }


def _render(report: dict[str, Any]) -> str:
    return json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2)


def _write_report(working: Path, report: dict[str, Any]) -> None:
    path = working / "metrics" / "mail-soak" / f"{report['date']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(_render(report) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def run(
    args: argparse.Namespace,
    working: str | Path,
    *,
    now: datetime | None = None,
    repository: Path | None = None,
) -> int:
    try:
        current = now or datetime.now(UTC)
        data = gather(
            working,
            current,
            repository or _repository_root(Path.cwd()),
            window_days=args.window_days,
        )
        thresholds = dict(getattr(args, "threshold", []))
        report = evaluate(data, args.window_days, current, thresholds)
        if args.write:
            _write_report(Path(working), report)
        print(_render(report) if args.json else _text(report))
        return 0 if report["all_ok"] else 1
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 70


def _text(report: dict[str, Any]) -> str:
    lines = [f"Mail soak {report['date']}: {'PASS' if report['all_ok'] else 'FAIL'}"]
    lines.extend(
        f"{item['id']}: {item['value']} (threshold {item['threshold']}) "
        f"{'PASS' if item['ok'] else 'FAIL'}"
        for item in report["criteria"]
    )
    lines.append(
        f"active orchestrators: {report['active_orchestrators']}; "
        f"passing day streak: {report['days_ok_streak']}"
    )
    lines.append(
        "gate metrics: "
        f"wakes={report['wakes']}, missed={report['missed']}, "
        f"distinct_recipients={report['distinct_recipients']}, "
        f"max_delivered_latency_s={report['max_delivered_latency_s']}"
    )
    return "\n".join(lines)
