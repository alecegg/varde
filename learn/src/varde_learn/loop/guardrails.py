"""Load and report the registered Varde guardrails."""

from __future__ import annotations

import tomllib
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from typing import NotRequired, TypedDict, cast

from .calls import CallRow, parse_timestamp

KINDS = {"hook", "gate", "cli-check", "cli-step"}
REGISTRY_NAME = "guardrails.toml"


class Guardrail(TypedDict):
    id: str
    kind: str
    owner: str
    purpose: str
    command: NotRequired[str]


def load_registry(
    path: Path | None = None, *, repo_root: Path | None = None
) -> list[Guardrail]:
    """Load registry entries; validate owner files when a checkout is supplied."""
    source = path or Path(str(files("varde_learn.loop").joinpath(REGISTRY_NAME)))
    try:
        raw = tomllib.loads(source.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"invalid guardrail registry {source}: {error}") from error
    values = raw.get("guardrails")
    if not isinstance(values, list):
        raise ValueError(  # noqa: TRY004 - registry data errors use one public type.
            f"invalid guardrail registry {source}: expected [[guardrails]] entries"
        )
    entries = cast("list[Guardrail]", values)
    try:
        validate_registry(entries, repo_root)
    except ValueError as error:
        raise ValueError(f"invalid guardrail registry {source}: {error}") from error
    return entries


def validate_registry(entries: list[Guardrail], repo_root: Path | None = None) -> None:
    """Reject malformed entries, duplicate ids, and optionally missing owners."""
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError(  # noqa: TRY004 - registry data errors use one public type.
                "each guardrail entry must be a table"
            )
        identifier = entry.get("id")
        if not isinstance(identifier, str) or not identifier:
            raise ValueError("guardrail id must be a non-empty string")
        if identifier in seen:
            raise ValueError(f"duplicate guardrail id: {identifier}")
        seen.add(identifier)
        if entry.get("kind") not in KINDS:
            raise ValueError(f"invalid kind for guardrail {identifier}")
        if not all(
            isinstance(entry.get(key), str) and entry[key]
            for key in ("owner", "purpose")
        ):
            raise ValueError(f"guardrail {identifier} needs owner and purpose")
        command = entry.get("command")
        if command is not None and (not isinstance(command, str) or not command):
            raise ValueError(f"invalid command for guardrail {identifier}")
        if repo_root is not None and not _owner_exists(entry["owner"], repo_root):
            raise ValueError(
                f"owner file does not exist for guardrail {identifier}: "
                f"{entry['owner']}"
            )


def check_owners(entries: list[Guardrail], repo_root: Path) -> None:
    """Check that registry owners exist inside the supplied repository."""
    validate_registry(entries, repo_root)


def firings(entries: list[Guardrail], rows: list[CallRow]) -> dict[str, dict[str, int]]:
    """Count fired and blocked events; command entries match route-path prefixes."""
    counts = {entry["id"]: {"fired": 0, "blocked": 0} for entry in entries}
    for entry in entries:
        identifier = entry["id"]
        command = entry.get("command")
        for row in rows:
            explicit = row.get("guardrail") == identifier
            matched_command = command is not None and _matches(row["command"], command)
            if explicit or matched_command:
                blocked = row["status"] == "blocked" or (
                    row["status"] == "failure"
                    and entry["kind"] in {"gate", "cli-check"}
                )
                key = "blocked" if blocked else "fired"
                counts[identifier][key] += 1
    return counts


def dead(
    entries: list[Guardrail],
    rows: list[CallRow],
    window: timedelta,
    now: datetime,
) -> list[str]:
    """Return ids with no firing in the trailing time window."""
    cutoff = _utc(now) - window
    recent = [
        row
        for row in rows
        if (timestamp := parse_timestamp(row["ts"])) is not None and timestamp >= cutoff
    ]
    counts = firings(entries, recent)
    return [entry["id"] for entry in entries if not any(counts[entry["id"]].values())]


def _matches(command: str, prefix: str) -> bool:
    return command == prefix or (
        command.startswith(prefix) and command[len(prefix)].isspace()
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _owner_exists(owner: str, repo_root: Path) -> bool:
    path = Path(owner)
    if path.is_absolute():
        return False
    root = repo_root.resolve()
    target = (root / path).resolve()
    return target.is_relative_to(root) and target.is_file()
