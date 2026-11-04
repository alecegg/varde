"""CLI adapter for one-shot and blocking relay operations."""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from varde_workflow.relay_state import confirm, end, record, renew
from varde_workflow.relay_wait import _current_token, _stamp, once, wait

_mailman_token = _current_token


def _now(value: str | None) -> datetime:
    return datetime.fromisoformat(value) if value else datetime.now(UTC)


def _print(value: dict[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":")))


def run(args, working: str | Path, *, wall_clock=None, poll=None) -> int:  # noqa: PLR0911
    try:
        now = _now(args.now)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 64
    try:
        if args.relay_action == "confirm":
            result = confirm(
                working,
                args.action_id,
                args.result,
                now,
                session=args.by or "",
                harness=args.harness,
                reason=args.evidence,
            )
            if args.evidence:
                record(
                    working,
                    "confirmation-evidence",
                    now=now,
                    action_id=args.action_id,
                    evidence=args.evidence,
                )
            _print({"schema": "varde-relay/1", "now": _stamp(now), **result})
            return 0
        if args.relay_action == "renew":
            renewed = renew(working, args.action_id, now)
            _print(
                {
                    "schema": "varde-relay/1",
                    "now": _stamp(now),
                    "status": "renewed" if renewed else "expired",
                }
            )
            return 0
        if args.relay_action == "end":
            if args.as_id != _current_token(working):
                print(
                    "error: --as must match the current mailman token", file=sys.stderr
                )
                return 64
            end(working, args.as_id, now)
            _print({"schema": "varde-relay/1", "now": _stamp(now), "status": "ended"})
            return 0
        if not args.once and not args.wait:
            print("error: choose --once or --wait", file=sys.stderr)
            return 64
        if args.context_tokens is not None and args.context_tokens < 0:
            print("error: --context-tokens must not be negative", file=sys.stderr)
            return 64
        if not args.as_id or args.as_id != _current_token(working):
            print("error: --as must match the current mailman token", file=sys.stderr)
            return 64
        if args.wait:
            start_time = _now(args.now)

            def default_wall_clock() -> datetime:
                return datetime.now(UTC)

            read_wall_clock = wall_clock or default_wall_clock
            offset = start_time - read_wall_clock()

            def clock() -> datetime:
                return read_wall_clock() + offset

            result = wait(
                working,
                args.as_id,
                args.timeout,
                now=clock,
                **({"poll": poll} if poll is not None else {}),
                context_tokens=args.context_tokens,
            )
        else:
            result = once(working, args.as_id, now, args.context_tokens)
        _print(result)
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 70
    else:
        return 0
