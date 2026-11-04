"""Create an approval listing, archive and retire eligible backlog, or restore it."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from varde_data.config import load_data_config
from varde_data.open import open_data
from varde_data.role_inbox import role_key_for_selector
from varde_data.views.message_receipts import message_receipts

from varde_workflow.inbox import read_all
from varde_workflow.retired import retire

DEFAULT_MIN_AGE_DAYS = 30
AGE_LIMIT = timedelta(days=DEFAULT_MIN_AGE_DAYS)
ALLOWLIST_PREFIXES = ("python-port-", "zero-test-failures-")
TERMINAL = {"done", "completed", "concluded", "finished", "archived", "cancelled"}


def terminal_plan_ids(working: Path) -> set[str]:
    """Read terminal plan front matter; active and missing plans are ineligible."""
    result: set[str] = set()
    plans = working / "plans"
    if not plans.is_dir():
        return result
    for path in plans.glob("*/plan.md"):
        try:
            head = path.read_text(encoding="utf-8").split("---", 2)[1]
        except OSError, IndexError:
            continue
        values = dict(line.split(":", 1) for line in head.splitlines() if ":" in line)
        if values.get("status", "").strip().lower() in TERMINAL:
            result.add(path.parent.name)
    return result


def plan_ids(working: Path) -> set[str]:
    plans = working / "plans"
    return (
        {path.parent.name for path in plans.glob("*/plan.md")}
        if plans.is_dir()
        else set()
    )


def address_plan_id(address: str, plan_ids: set[str]) -> str | None:
    matches = sorted(
        (plan for plan in plan_ids if address.startswith(plan + "-")),
        key=len,
        reverse=True,
    )
    return matches[0] if matches else None


def eligible_address(
    address: str,
    live: set[str],
    terminal_ids: set[str],
    known_plan_ids: set[str] | None = None,
) -> bool:
    if address == "main" or address in live or role_key_for_selector(address):
        return False
    matched_plan = address_plan_id(address, known_plan_ids or terminal_ids)
    if matched_plan is not None:
        return matched_plan in terminal_ids
    return address.startswith(ALLOWLIST_PREFIXES)


def _stamp(message: dict[str, Any]) -> datetime | None:
    try:
        return datetime.fromisoformat(str(message["ts"]))
    except KeyError, ValueError:
        return None


def _age_limit(min_age_days: int) -> timedelta:
    if (
        not isinstance(min_age_days, int)
        or isinstance(min_age_days, bool)
        or min_age_days < 1
    ):
        raise ValueError("min_age_days must be at least 1")
    return timedelta(days=min_age_days)


def build_dry_run(
    working: Path,
    now: datetime | None = None,
    *,
    min_age_days: int = DEFAULT_MIN_AGE_DAYS,
) -> dict[str, Any]:
    age_limit = _age_limit(min_age_days)
    now = now or datetime.now(UTC)
    data = open_data(working, load_data_config())
    live = set(data.addresses.live_addresses(now))
    terminal = terminal_plan_ids(working)
    known_plans = plan_ids(working)
    rows = [message.to_dict() for message in read_all(working)]
    receipts = message_receipts(
        rows, [asdict(event) for event in data.messages.deliveries()], now
    )
    eligible = {
        str(row["to"])
        for row in rows
        if isinstance(row.get("to"), str)
        and eligible_address(str(row["to"]), live, terminal, known_plans)
    }
    recent = {
        str(row["to"])
        for row in rows
        if row.get("to") in eligible
        and (timestamp := _stamp(row)) is not None
        and now - timestamp < age_limit
        and receipts.get(str(row.get("id")), {})
        .get("recipients", {})
        .get(row.get("to"), {})
        .get("state")
        in {"queued", "pushed"}
    }
    eligible.difference_update(recent)
    messages = []
    for row in rows:
        message_id, address = row.get("id"), row.get("to")
        timestamp = _stamp(row)
        if not isinstance(message_id, str) or address not in eligible:
            continue
        if timestamp is None or now - timestamp < age_limit:
            continue
        state = (
            receipts.get(message_id, {})
            .get("recipients", {})
            .get(address, {})
            .get("state")
        )
        if state in {"queued", "pushed"}:
            messages.append(row)
    counts = Counter(str(row["to"]) for row in messages)
    addresses = sorted(counts)
    return {
        "kind": "varde-mail-retirement-dry-run",
        "created_at": now.isoformat(),
        "min_age_days": min_age_days,
        "addresses": addresses,
        "counts_by_address": dict(sorted(counts.items())),
        "message_count": len(messages),
        "messages": messages,
    }


def write_dry_run(
    working: Path,
    audit_dir: Path,
    min_age_days: int = DEFAULT_MIN_AGE_DAYS,
) -> Path:
    payload = build_dry_run(working, min_age_days=min_age_days)
    audit_dir.mkdir(parents=True, exist_ok=True)
    path = audit_dir / "retire-dry-run.json"
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)
    print(
        json.dumps(
            {
                key: payload[key]
                for key in (
                    "min_age_days",
                    "addresses",
                    "counts_by_address",
                    "message_count",
                )
            },
            indent=2,
        )
    )
    print(path)
    return path


def apply_dry_run(working: Path, path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("kind") != "varde-mail-retirement-dry-run":
        raise ValueError("--apply requires a retirement dry-run file")
    min_age_days = payload.get("min_age_days")
    if not isinstance(min_age_days, int) or isinstance(min_age_days, bool):
        raise TypeError("dry-run file must record min_age_days as an integer")
    _age_limit(min_age_days)
    approved_digest = _digest(payload)
    audit = path.with_name(path.stem.removesuffix("-dry-run") + "-audit.json")
    if audit.exists():
        existing = json.loads(audit.read_text(encoding="utf-8"))
        if existing.get("dry_run_digest") == _digest(payload):
            addresses = set(existing.get("addresses", []))
            retire(working, addresses, set(), datetime.now(UTC))
            return {
                "audit": str(audit),
                "addresses": existing.get("addresses", []),
                "message_count": existing.get("message_count", 0),
            }
        raise ValueError(f"audit already exists with different contents: {audit}")
    current = build_dry_run(working, min_age_days=min_age_days)
    if current["addresses"] != payload.get("addresses") or {
        row["id"] for row in current["messages"]
    } != {row["id"] for row in payload.get("messages", [])}:
        raise ValueError(
            "mail changed after dry run; generate and review a new listing"
        )
    payload = current
    data = open_data(working, load_data_config())
    live = set(data.addresses.live_addresses(datetime.now(UTC)))
    terminal = terminal_plan_ids(working)
    known_plans = plan_ids(working)
    addresses = set(payload["addresses"])
    if any(
        not eligible_address(address, live, terminal, known_plans)
        for address in addresses
    ):
        raise ValueError("dry-run contains a live, role, main, or in-flight address")
    active = {
        address
        for address in addresses
        if address not in data.addresses.retired_records()
    }
    result = {
        **payload,
        "kind": "varde-mail-retirement-audit",
        "dry_run_digest": approved_digest,
        "applied_at": datetime.now(UTC).isoformat(),
        "already_retired": sorted(set(payload["addresses"]) - active),
    }
    audit.parent.mkdir(parents=True, exist_ok=True)
    tmp = audit.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(audit)
    if active:
        retire(working, active, set(), datetime.now(UTC))
    return {
        "audit": str(audit),
        "addresses": sorted(active),
        "message_count": len(payload["messages"]),
    }


def restore(working: Path, path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("kind") != "varde-mail-retirement-audit":
        raise ValueError("--restore requires a retirement audit file")
    repository = open_data(working, load_data_config()).addresses
    selected = set(payload.get("addresses", []))
    repository.unretire(selected)
    return {
        "restored_addresses": sorted(selected),
        "messages_retained": len(payload.get("messages", [])),
    }


def _digest(value: dict[str, Any]) -> str:
    import hashlib

    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
