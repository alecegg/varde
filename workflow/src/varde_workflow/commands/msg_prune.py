"""Retire unused inbox addresses and stale mailman tokens."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from varde_data.config import load_data_config
from varde_data.open import Data, open_data

from varde_workflow.inbox import read_all

AGE_LIMIT = timedelta(hours=24)
RETURN_GRACE = timedelta(seconds=90)


def select_retirements(  # noqa: PLR0913
    address_times: dict[str, datetime],
    *,
    now: datetime,
    pending: set[str],
    live: set[str],
    concluded: set[str],
    tokens: set[str],
    current_token: str | None,
    relay_events: list[dict[str, Any]] | None = None,
    live_tokens: set[str] | None = None,
    retired: set[str] | None = None,
) -> dict[str, set[str]]:
    """Select stale addresses and non-current tokens without performing I/O."""
    retired_keys = retired or set()
    addresses = {
        address
        for address, since in address_times.items()
        if address not in retired_keys
        and address not in pending
        and address not in live
        and (address in concluded or since <= now - AGE_LIMIT)
    }
    latest_events: dict[str, dict[str, Any]] = {}
    for event in relay_events or []:
        token = event.get("token_id")
        if isinstance(token, str):
            latest_events[token] = event
    protected_tokens = set(live_tokens or ())
    if current_token:
        protected_tokens.add(current_token)
    for token, event in latest_events.items():
        if event.get("event") != "waiting":
            continue
        try:
            deadline = datetime.fromisoformat(
                str(event.get("expect_return_by") or event["at"])
            )
        except KeyError, ValueError:
            continue
        if deadline + RETURN_GRACE >= now:
            protected_tokens.add(token)
    return {
        "addresses": addresses,
        "tokens": tokens
        - protected_tokens
        - {
            key.removeprefix("mailman:")
            for key in retired_keys
            if key.startswith("mailman:")
        },
    }


def _address_times(data: Data, working: Path) -> dict[str, datetime]:
    addresses = {message.to for message in read_all(working)}
    addresses.update(data.messages.concluded_addresses())
    addresses.update(data.addresses.address_names())
    bindings: dict[str, datetime] = {}
    for binding in data.addresses.list_bindings():
        bindings[binding.address] = max(
            bindings.get(binding.address, datetime.min.replace(tzinfo=UTC)),
            binding.last_seen,
        )
    token_times = data.addresses.token_issue_times()
    result: dict[str, datetime] = {}
    for address in addresses:
        latest = max(token_times.get(address, ()), default=None)
        recent = max(
            (value for value in (bindings.get(address), latest) if value is not None),
            default=None,
        )
        result[address] = recent or datetime.min.replace(tzinfo=UTC)
    return result


def _candidates(working: Path, now: datetime) -> dict[str, set[str]]:
    data = open_data(working, load_data_config())
    repository = data.addresses
    addresses = _address_times(data, working)
    pending = _pending_addresses(working, set(addresses))
    live = set(repository.live_addresses(now))
    snapshot = repository.relay_snapshot()
    tokens = set(snapshot.mailman_started)
    live_tokens = {
        binding.token_id
        for binding in repository.list_bindings()
        if binding.address in live and binding.token_id
    }
    retired = repository.retired()
    return select_retirements(
        addresses,
        now=now,
        pending=pending,
        live=live,
        concluded=set(data.messages.concluded_addresses()),
        tokens=tokens,
        current_token=repository.current_token("mailman"),
        relay_events=[dict(event) for event in snapshot.events],
        live_tokens=live_tokens,
        retired=set(retired.addresses)
        | {f"mailman:{token}" for token in retired.tokens},
    )


def _pending_addresses(working: Path, addresses: set[str]) -> set[str]:
    messages = open_data(Path(working), load_data_config()).messages
    return {address for address in addresses if messages.peek_unread(address)}


def run(args, working: str | Path | None = None) -> int:
    """Print prune candidates and persist retirement records unless dry-run."""
    try:
        if working is None:
            from varde_workflow.commands.msg import _working_dir

            working = _working_dir()
        root = Path(working)
        now = datetime.now(UTC)
        selected = _candidates(root, now)
        result = {
            "addresses": sorted(selected["addresses"]),
            "tokens": sorted(selected["tokens"]),
        }
        if not args.dry_run and (result["addresses"] or result["tokens"]):
            from varde_workflow.retired import retire

            retire(root, selected["addresses"], selected["tokens"], now)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 70
    else:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
