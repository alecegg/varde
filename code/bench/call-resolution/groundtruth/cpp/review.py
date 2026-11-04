"""Create and reconcile two-reviewer hand-verification stubs."""

from __future__ import annotations

from collections.abc import Mapping


def stub(record: Mapping[str, object]) -> dict[str, object]:
    """Create blank independent reviewer fields for an unresolved call site."""
    return {
        "repo": record["repo"],
        "file": record["file"],
        "line": record["line"],
        "call_name": record["call_name"],
        "call_class": record["call_class"],
        "reviewer_1": {"target": None, "reason": None},
        "reviewer_2": {"target": None, "reason": None},
        "agreement": None,
    }
