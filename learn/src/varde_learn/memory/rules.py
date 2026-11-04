"""Pure entry lint rules: one validator for memory entries and knowledge concepts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from varde_learn.memory.entry import (
    KNOWN_TYPES,
    Entry,
    EntryError,
    find_secret,
    is_slug,
    summary_of,
    validate_key,
)

SURFACE_SUMMARY_MAX = 80
SUMMARY_WARN_MAX = 120
BODY_WARN_MAX = 8000

ERROR = "error"
WARNING = "warning"


@dataclass(frozen=True)
class Issue:
    severity: str
    code: str
    message: str
    path: str = ""


def lint_entry(entry: Entry, previous: Entry | None) -> list[Issue]:
    """Lint one entry. `previous` is the stored entry, or None for a new one."""
    issues = _error_issues(entry)
    issues += _summary_issues(entry, previous)
    if len(entry.text) > BODY_WARN_MAX:
        issues.append(_warn("body-long", f"body over {BODY_WARN_MAX} characters"))
    if entry.type not in KNOWN_TYPES:
        issues.append(_warn("type-unknown", f"unknown type: {entry.type!r}"))
    return issues


def _error_issues(entry: Entry) -> list[Issue]:
    issues: list[Issue] = []
    if not is_slug(entry.id):
        issues.append(_err("slug-bad", f"invalid id: {entry.id!r}"))
    try:
        validate_key(entry.scope, entry.scope_key)
    except EntryError as error:
        issues.append(_err("scope-key-bad", str(error)))
    if not entry.text.strip():
        issues.append(_err("body-empty", "text must not be empty"))
    if find_secret(entry.text) is not None:
        issues.append(_err("secret", "text looks like a secret"))
    if entry.valid_until and not _is_date(entry.valid_until):
        issues.append(
            _err("valid-until-bad", f"bad valid_until: {entry.valid_until!r}")
        )
    return issues


def _summary_issues(entry: Entry, previous: Entry | None) -> list[Issue]:
    summary = summary_of(entry)
    issues: list[Issue] = []
    if len(summary) > SUMMARY_WARN_MAX:
        issues.append(
            _warn("summary-long", f"summary over {SUMMARY_WARN_MAX} characters")
        )
    if not entry.surface or len(summary) <= SURFACE_SUMMARY_MAX:
        return issues
    message = f"surfaced summary over {SURFACE_SUMMARY_MAX} characters"
    grandfathered = previous is not None and summary_of(previous) == summary
    issues.append(
        _warn("summary-surface", message)
        if grandfathered
        else _err("summary-surface", message)
    )
    return issues


def _is_date(value: str) -> bool:
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _err(code: str, message: str) -> Issue:
    return Issue(ERROR, code, message)


def _warn(code: str, message: str) -> Issue:
    return Issue(WARNING, code, message)
