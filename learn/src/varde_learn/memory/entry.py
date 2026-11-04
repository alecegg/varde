"""Memory entry model and validation (pure logic, no I/O)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from varde_learn.knowledge.concept import Concept

SCOPES = ("agent", "skill", "project", "global")
STATUSES = ("active", "retired", "archived")
KEYED_SCOPES = ("agent", "skill", "project")
PROJECT_FIELD_SCOPES = ("agent", "skill")
KNOWN_TYPES = ("decision", "pattern", "definition", "reference", "lesson")
DEFAULT_TYPE = "lesson"

_SLUG = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_PROJECT_KEY = re.compile(r"^[^/\\]+-[0-9a-f]{16}$")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")

_SECRET_PATTERNS = tuple(
    re.compile(pattern)
    for pattern in (
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
        r"AKIA[0-9A-Z]{16}",
        r"gh[pousr]_[A-Za-z0-9]{20,}",
        r"github_pat_",
        r"sk-[A-Za-z0-9]{20,}",
        r"xox[abprs]-",
        r"Authorization: Bearer",
        r"(?i:password|passwd|secret|api[_-]?key|token)\s*[:=]\s*\S{8,}",
    )
)


class EntryError(ValueError):
    """An entry or one of its keys failed validation."""


@dataclass(frozen=True)
class Entry:
    id: str
    scope: str
    scope_key: str
    text: str
    source: str
    created: str
    status: str = "active"
    tags: tuple[str, ...] = ()
    project: str = ""
    model: str = ""
    harness_version: str = ""
    type: str = DEFAULT_TYPE
    topic: str = ""
    valid_until: str = ""
    surface: bool = True
    updated: str = ""
    title: str = ""
    aliases: tuple[str, ...] = ()
    description: str = ""
    extra: dict[str, Any] = field(default_factory=dict, compare=False)


def is_slug(value: str) -> bool:
    return bool(_SLUG.match(value)) and value not in (".", "..")


def is_project_key(value: str) -> bool:
    if _CONTROL.search(value) or not _PROJECT_KEY.match(value):
        return False
    return value.rsplit("-", 1)[0] not in (".", "..")


def find_secret(text: str) -> str | None:
    """Return the pattern a text matches, or None (best-effort filter)."""
    for pattern in _SECRET_PATTERNS:
        if pattern.search(text):
            return pattern.pattern
    return None


def validate_key(scope: str, key: str) -> None:
    if scope == "global":
        if key:
            raise EntryError("global scope takes no scope_key")
        return
    if not key:
        raise EntryError(f"scope {scope} requires a scope_key")
    valid = is_project_key(key) if scope == "project" else is_slug(key)
    if not valid:
        raise EntryError(f"invalid {scope} scope_key: {key!r}")


def validate(entry: Entry) -> None:
    if entry.scope not in SCOPES:
        raise EntryError(f"unknown scope: {entry.scope!r}")
    if entry.status not in STATUSES:
        raise EntryError(f"unknown status: {entry.status!r}")
    if not is_slug(entry.id):
        raise EntryError(f"invalid id: {entry.id!r}")
    validate_key(entry.scope, entry.scope_key)
    _validate_project_field(entry)
    _validate_agent_fields(entry)
    if not entry.text.strip():
        raise EntryError("text must not be empty")
    if find_secret(entry.text) is not None:
        raise EntryError("text looks like a secret")


def _validate_project_field(entry: Entry) -> None:
    if not entry.project:
        return
    if entry.scope not in PROJECT_FIELD_SCOPES:
        raise EntryError("project is allowed only on agent and skill entries")
    if not is_project_key(entry.project):
        raise EntryError(f"invalid project key: {entry.project!r}")


def _validate_agent_fields(entry: Entry) -> None:
    if entry.scope != "agent":
        return
    if not entry.model or not entry.harness_version:
        raise EntryError("agent entries require model and harness_version")


def summary_of(entry: Entry) -> str:
    """The surfaced summary: the description, else the first non-heading line."""
    if entry.description.strip():
        return entry.description.strip()
    for line in entry.text.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            return stripped
    return ""


_CONCEPT_MAPPED_KEYS = frozenset(
    {
        "status",
        "date",
        "created",
        "type",
        "description",
        "summary",
        "aliases",
        "tags",
        "title",
    }
)
_CONCEPT_STATUS = {
    "current": "active",
    "retired": "retired",
    "archived": "archived",
    "active": "active",
}


def entry_from_concept(
    concept: Concept, *, scope_key: str, source: str, mtime_date: str = ""
) -> tuple[Entry, list[str]]:
    """Read a knowledge Concept as a project Entry; return it with warnings.

    Slug `/` becomes `-`. Knowledge concepts are not surfaced.
    """
    front = concept.frontmatter
    warnings: list[str] = []
    status = _concept_status(front.get("status"), warnings)
    kind = str(front["type"]) if front.get("type") else "reference"
    if kind not in KNOWN_TYPES:
        warnings.append(f"unknown type: {kind!r}")
    description = str(front.get("description") or front.get("summary") or "").strip()
    entry = Entry(
        id=concept.slug.replace("/", "-"),
        scope="project",
        scope_key=scope_key,
        text=concept.body.strip("\n"),
        source=source,
        created=str(front.get("date") or front.get("created") or mtime_date),
        status=status,
        tags=_string_tuple(front.get("tags")),
        type=kind,
        surface=False,
        title=str(front.get("title") or ""),
        aliases=_string_tuple(front.get("aliases")),
        description=description or _first_heading(concept.body),
        extra={k: v for k, v in front.items() if k not in _CONCEPT_MAPPED_KEYS},
    )
    return entry, warnings


def _concept_status(value: object, warnings: list[str]) -> str:
    if value is None:
        return "active"
    status = _CONCEPT_STATUS.get(str(value))
    if status is None:
        warnings.append(f"unknown status: {value!r}, using active")
        return "active"
    return status


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list | tuple):
        return ()
    return tuple(str(item) for item in value)


def _first_heading(body: str) -> str:
    for line in body.splitlines():
        if line.lstrip().startswith("#"):
            return line.lstrip("# ").strip()
    return ""
