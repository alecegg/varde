"""Pure helpers for plan labels and groups."""

from __future__ import annotations

import re
from collections.abc import Iterable


def resolve_group(own: object, parent_resolved: str) -> str:
    """Resolve a plan's group from its own metadata or its parent."""
    return own.strip() if isinstance(own, str) and own.strip() else parent_resolved


def resolve_parent_group(ancestors_nearest_first: Iterable[object]) -> str:
    """Return the first usable resolved group among nearest-first ancestors."""
    for group in ancestors_nearest_first:
        resolved = resolve_group(group, "")
        if resolved:
            return resolved
    return ""


def suggest_label(title: object) -> str:
    """Suggest a concise label from a plan title."""
    if not isinstance(title, str):
        return ""
    words = title.split()
    fillers = {"a", "an", "the", "please", "kindly", "sure", "to"}
    while words and words[0].casefold() in fillers:
        if len(words) == 1:
            break
        words.pop(0)
    suggestion = " ".join(words[:5])
    while len(suggestion) > 36 and words:
        words.pop()
        suggestion = " ".join(words[:5])
    return suggestion


def label_findings(
    label: object,
    group: str,
    title: object = "",
    plan_id: str = "",
    other_open_labels: Iterable[str] = (),
) -> list[str]:
    """Return metadata warnings for a plan label and resolved group."""
    findings = []
    if not isinstance(label, str) or not label.strip():
        findings.append("missing label")
    else:
        normalized = " ".join(label.split()).casefold()
        suggestion = suggest_label(title)
        suffix = f'; suggest: "{suggestion}"' if len(suggestion.split()) >= 3 else ""
        if not 3 <= len(label.split()) <= 5:
            findings.append(f"label must be 3 to 5 words{suffix}")
        if len(label) > 36:
            findings.append(f"label must be at most 36 characters{suffix}")
        if re.search(r"\b\d{8}\b", label):
            findings.append(f"label must not contain an 8-digit date{suffix}")
        if re.search(r"\b\d{4}-\d{2}-\d{2}\b", label):
            findings.append(f"label must not contain an ISO date{suffix}")
        if re.search(r"\bv\d+\b", label, re.IGNORECASE):
            findings.append(f"label must not contain a vN version{suffix}")
        if plan_id and re.search(
            rf"(?<!\w){re.escape(plan_id)}(?!\w)", label, re.IGNORECASE
        ):
            findings.append(f"label must not contain the plan id{suffix}")
        if normalized in {
            " ".join(item.split()).casefold() for item in other_open_labels
        }:
            findings.append(f"label must be unique among open plans{suffix}")
    if not group.strip():
        findings.append("missing group")
    return findings
