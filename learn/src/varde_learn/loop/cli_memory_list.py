"""`memory list` report pieces: scope counts, scope warning, expired report.

Plain functions; `cli_memory` wires them to the parser after approval.
"""

from __future__ import annotations

from collections import Counter
from datetime import date

from varde_learn.memory.entry import SCOPES, Entry
from varde_learn.memory.expiry import expired_report


def scope_counts(entries: list[Entry]) -> dict[str, int]:
    """Active entries per scope, in scope order, zero counts included."""
    counted = Counter(e.scope for e in entries if e.status == "active")
    return {scope: counted[scope] for scope in SCOPES}


def scope_warnings(counts: dict[str, int], limit: int) -> list[str]:
    return [
        f"warning: scope {scope} has {count} entries (limit {limit})"
        for scope, count in counts.items()
        if count > limit
    ]


def counts_lines(counts: dict[str, int], limit: int) -> list[str]:
    lines = [f"{scope}: {count}" for scope, count in counts.items()]
    return lines + scope_warnings(counts, limit)


def expired_lines(entries: list[Entry], today: date) -> list[str]:
    """One line per expired entry; the cleanup report for `list --expired`."""
    return [
        f"{e.id} | {e.scope} | expired {e.valid_until}"
        for e in expired_report(entries, today)
    ]
