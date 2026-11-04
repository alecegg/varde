"""Show one message and its derived delivery receipt."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from varde_workflow.inbox import read_all


def message_details(
    working: str | Path, message_id: str, now: datetime
) -> dict[str, Any]:
    from varde_data.views.message_receipts import message_receipts

    from varde_workflow.inbox import delivery_events

    messages = [message.to_dict() for message in read_all(working)]
    message = next((item for item in messages if item.get("id") == message_id), None)
    if message is None:
        raise ValueError(f"message `{message_id}` does not exist")
    receipt = message_receipts(messages, delivery_events(working), now)[message_id]
    return {**message, **receipt}


def run(args, working: str | Path) -> int:
    try:
        details = message_details(working, args.id, datetime.now(UTC))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(details, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    print(
        f"{details['id']} {details['from']} -> {details['to']} "
        f"[{details['state']}] {details['text']}"
    )
    for state, at in details["timestamps"].items():
        if at is not None:
            print(f"{state}: {at}")
    if details["last_reason"] is not None:
        print(f"last reason: {details['last_reason']}")
    if details.get("delivered_as") is not None:
        print(f"delivered-as: {details['delivered_as']}")
    for recipient, row in details["recipients"].items():
        age = row["undelivered_age_seconds"]
        if age is not None:
            print(f"{recipient}: undelivered {int(age)}s")
    return 0
