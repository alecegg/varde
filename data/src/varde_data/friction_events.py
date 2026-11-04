"""Pure friction event encoding, replay, folding, and durable append."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from varde_data.errors import DataError, Invalid
from varde_data.learn_store_ignore import IGNORED_PATTERNS
from varde_data.locking import blocking_file_lock
from varde_data.records.friction import (
    AdoptionRecorded,
    Event,
    EventBody,
    FrictionEventLog,
    ItemAdded,
    ItemTagsChanged,
    LogAdoption,
    LogItem,
    LogOccurrence,
    LogReplay,
    LogState,
    LogStatusChange,
    OccurrenceAppended,
    StatusChanged,
)

LOG_FILE_NAME = "friction.jsonl"
FORMAT_VERSION = 1
ID_HEX_LENGTH = 16
_STATUSES = {"open", "resolved", "promoted", "archived"}


def _kind(body: EventBody) -> str:
    return {
        ItemAdded: "item_added",
        ItemTagsChanged: "item_tags_changed",
        OccurrenceAppended: "occurrence_appended",
        StatusChanged: "status_changed",
        AdoptionRecorded: "adoption_recorded",
    }[type(body)]


def _body_dict(body: EventBody) -> dict[str, Any]:
    fields = {
        ItemAdded: ("title", "source", "repo_root", "target", "tags"),
        ItemTagsChanged: ("item", "tags"),
        OccurrenceAppended: (
            "item",
            "at",
            "cwd",
            "repo_root",
            "head_sha",
            "evidence",
            "cost",
            "provenance",
        ),
        StatusChanged: ("item", "at", "from_", "to", "reason"),
        AdoptionRecorded: (
            "at",
            "summary",
            "files",
            "commit_sha",
            "eval_before",
            "eval_after",
            "items",
        ),
    }[type(body)]
    return {
        ("from" if name == "from_" else name): value
        for name in fields
        if (value := getattr(body, name)) is not None
    }


def event_id(
    ts: str,
    kind: str,
    body: EventBody,
    *,
    pid: int | None = None,
    counter: int | None = None,
) -> str:
    """Return the Rust-compatible truncated SHA-256 event identity."""
    if pid is None:
        pid = os.getpid()
    if counter is None:
        counter = _next_counter()
    wire_body = json.dumps(_body_dict(body), ensure_ascii=False, separators=(",", ":"))
    material = f"{ts}\n{pid}\n{counter}\n{kind}\n{wire_body}"
    return hashlib.sha256(material.encode()).hexdigest()[:ID_HEX_LENGTH]


def redact_text(text: str) -> tuple[str, int]:
    """Apply the shared built-in redactor and return text plus notice count."""
    from varde_core.redact import RedactConfig, Redactor

    result = Redactor(RedactConfig()).redact(text)
    return result.text, sum(notice.count for notice in result.notices)


_counter = 0


def _next_counter() -> int:
    global _counter  # noqa: PLW0603 - serialized identity counter
    current = _counter
    _counter += 1
    return current


def now_timestamp() -> str:
    return format_timestamp(time.time_ns() // 1_000_000)


def format_timestamp(milliseconds: int) -> str:
    try:
        value = datetime.fromtimestamp(milliseconds / 1000, tz=UTC)
    except OverflowError, OSError, ValueError:
        value = datetime(1970, 1, 1, tzinfo=UTC)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + f"{milliseconds % 1000:03d}Z"


def make_event(
    ts: str,
    repo: str | None,
    body: EventBody,
    *,
    pid: int | None = None,
    counter: int | None = None,
) -> Event:
    """Create an event with its kind and deterministic-format identifier."""
    kind = _kind(body)
    return Event(
        FORMAT_VERSION,
        event_id(ts, kind, body, pid=pid, counter=counter),
        ts,
        kind,
        body,
        repo,
    )


def new_event(repo: str | None, body: EventBody) -> Event:
    return make_event(now_timestamp(), repo, body)


def validate_event(event: Event) -> None:
    if type(event.v) is not int:
        raise ValueError("friction event version must be an integer")
    if event.v != FORMAT_VERSION:
        raise ValueError(
            f"unsupported friction log version {event.v} (expected {FORMAT_VERSION})"
        )
    if not isinstance(event.id, str) or not re.fullmatch(
        rf"[0-9a-f]{{{ID_HEX_LENGTH}}}", event.id
    ):
        raise ValueError(f"invalid friction event id `{event.id}`")
    if not isinstance(event.ts, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", event.ts
    ):
        raise ValueError("friction event timestamp must be RFC3339 with milliseconds")
    try:
        datetime.strptime(event.ts, "%Y-%m-%dT%H:%M:%S.%fZ")
    except ValueError as error:
        raise ValueError(f"invalid friction event timestamp `{event.ts}`") from error
    if event.repo is not None and not isinstance(event.repo, str):
        raise ValueError("friction event repo must be a string or null")
    if type(event.redacted) is not int or event.redacted < 0:
        raise ValueError("friction event redacted count must be a nonnegative integer")
    if event.kind != _kind(event.body):
        raise ValueError(f"kind `{event.kind}` does not match its body")
    _validate_body(event.body)
    if isinstance(event.body, StatusChanged):
        for value in (event.body.from_, event.body.to):
            if value.lower() not in _STATUSES:
                raise ValueError(f"unknown friction status `{value}`")


def _validate_event_provenance(event: Event) -> None:
    body = event.body
    if not isinstance(body, OccurrenceAppended) or body.provenance is None:
        return
    provenance = body.provenance
    required = {
        "incident_key",
        "identity_version",
        "harness",
        "thread_id",
        "incident_kind",
        "witness_id",
        "source_id",
        "record_index",
        "byte_start",
        "byte_end",
        "record_digest",
        "payload_digest",
    }
    if not required <= provenance.keys():
        raise Invalid("invalid friction event provenance")
    if type(provenance["identity_version"]) is not int:
        raise Invalid("invalid friction event provenance")
    if provenance["identity_version"] != 1:
        raise Invalid(
            f"unsupported incident identity version `{provenance['identity_version']}`"
        )
    string_fields = required - {
        "identity_version",
        "record_index",
        "byte_start",
        "byte_end",
        "witness_id",
    }
    if any(not isinstance(provenance[field], str) for field in string_fields):
        raise Invalid("invalid friction event provenance")
    if provenance["witness_id"] is not None and not isinstance(
        provenance["witness_id"], str
    ):
        raise Invalid("invalid friction event provenance")
    if any(
        type(provenance[field]) is not int
        for field in ("record_index", "byte_start", "byte_end")
    ):
        raise Invalid("invalid friction event provenance")
    for field in ("harness", "thread_id", "incident_kind", "source_id"):
        value = provenance[field]
        if not value.strip() or len(value.encode()) > 4_096 or _has_controls(value):
            raise Invalid(f"{field} exceeds its supported format")
    if provenance["harness"] not in {"codex", "claude", "opencode"}:
        raise Invalid("unsupported historical harness")
    if provenance["incident_kind"] not in {
        "failed-tool",
        "repeated-work",
        "workflow-deviation",
    }:
        raise Invalid("unsupported historical incident kind")
    witness_id = provenance["witness_id"]
    if witness_id is not None and (
        not witness_id.strip()
        or len(witness_id.encode()) > 4_096
        or _has_controls(witness_id)
    ):
        raise Invalid("witness ID exceeds its supported format")
    record_index = provenance["record_index"]
    byte_start = provenance["byte_start"]
    byte_end = provenance["byte_end"]
    record_digest = provenance["record_digest"]
    if (
        byte_end < byte_start
        or max(record_index, byte_start, byte_end) > (1 << 63) - 1
        or not _is_sha256_digest(record_digest)
    ):
        raise Invalid("historical source anchor is invalid")
    expected_key = _incident_key(provenance, legacy=False)
    legacy_key = _incident_key(provenance, legacy=True)
    if (
        provenance["incident_key"] != expected_key
        and (witness_id is not None or provenance["incident_key"] != legacy_key)
    ) or not _is_sha256_digest(provenance["payload_digest"]):
        raise Invalid("incident provenance key or payload digest is invalid")


def _has_controls(value: str) -> bool:
    return any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value)


def _is_sha256_digest(value: str) -> bool:
    digest = value[7:] if value.startswith("sha256:") else ""
    return len(digest) == 64 and all(
        char in "0123456789abcdefABCDEF" for char in digest
    )


def _incident_key(provenance: dict[str, Any], *, legacy: bool) -> str:
    witness_id = provenance["witness_id"]
    if witness_id is not None:
        event = {"native_id": witness_id}
    elif legacy:
        event = {
            "record_index": provenance["record_index"],
            "byte_start": provenance["byte_start"],
            "byte_end": provenance["byte_end"],
            "record_digest": provenance["record_digest"],
        }
    else:
        event = {
            "record_index": provenance["record_index"],
            "record_digest": provenance["record_digest"],
        }
    material = {
        "identity_version": 1,
        "harness": provenance["harness"],
        "thread_id": provenance["thread_id"],
        "incident_kind": provenance["incident_kind"],
        "event": event,
    }
    encoded = json.dumps(
        material, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return f"incident-v1:{hashlib.sha256(encoded).hexdigest()}"


def _validate_body(body: EventBody) -> None:
    strings: dict[type, tuple[str, ...]] = {
        ItemAdded: ("title", "source"),
        ItemTagsChanged: ("item",),
        OccurrenceAppended: ("item", "at", "cwd", "evidence"),
        StatusChanged: ("item", "at", "from_", "to", "reason"),
        AdoptionRecorded: ("at", "summary"),
    }
    optional_strings: dict[type, tuple[str, ...]] = {
        ItemAdded: ("repo_root", "target"),
        OccurrenceAppended: ("repo_root", "head_sha", "cost"),
        AdoptionRecorded: ("commit_sha", "eval_before", "eval_after"),
    }
    for name in strings[type(body)]:
        if not isinstance(getattr(body, name), str):
            raise TypeError(f"friction event body `{name}` must be a string")
    for name in optional_strings.get(type(body), ()):
        value = getattr(body, name)
        if value is not None and not isinstance(value, str):
            raise ValueError(f"friction event body `{name}` must be a string or null")
    if (
        isinstance(body, (ItemAdded, ItemTagsChanged))
        and body.tags is not None
        and (
            not isinstance(body.tags, list)
            or not all(isinstance(tag, str) for tag in body.tags)
        )
    ):
        raise ValueError("friction event body `tags` must be a list of strings")
    if (
        isinstance(body, OccurrenceAppended)
        and body.provenance is not None
        and not isinstance(body.provenance, dict)
    ):
        raise ValueError("friction event body `provenance` must be an object or null")
    if isinstance(body, AdoptionRecorded):
        for name in ("files", "items"):
            value = getattr(body, name)
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                raise ValueError(
                    f"friction event body `{name}` must be a list of strings"
                )


def event_to_dict(event: Event) -> dict[str, Any]:
    out: dict[str, Any] = {
        "v": event.v,
        "id": event.id,
        "ts": event.ts,
        "kind": event.kind,
    }
    if event.repo is not None:
        out["repo"] = event.repo
    out["body"] = _body_dict(event.body)
    if event.redacted:
        out["redacted"] = event.redacted
    return out


def event_from_dict(raw: dict[str, Any]) -> Event:
    kind = raw["kind"]
    body = raw["body"]
    allowed: dict[str, tuple[type, tuple[str, ...]]] = {
        "item_added": (ItemAdded, ("title", "source", "repo_root", "target", "tags")),
        "item_tags_changed": (ItemTagsChanged, ("item", "tags")),
        "occurrence_appended": (
            OccurrenceAppended,
            (
                "item",
                "at",
                "cwd",
                "evidence",
                "repo_root",
                "head_sha",
                "cost",
                "provenance",
            ),
        ),
        "status_changed": (StatusChanged, ("item", "at", "from", "to", "reason")),
        "adoption_recorded": (
            AdoptionRecorded,
            (
                "at",
                "summary",
                "files",
                "items",
                "commit_sha",
                "eval_before",
                "eval_after",
            ),
        ),
    }
    cls, names = allowed[kind]
    if set(body) - set(names):
        raise ValueError("unknown fields in friction event body")
    values = {
        ("from_" if name == "from" else name): body[name]
        for name in names
        if name in body
    }
    if set(raw) - {"v", "id", "ts", "kind", "repo", "body", "redacted"}:
        raise ValueError("unknown fields in friction event")
    return Event(
        raw["v"],
        raw["id"],
        raw["ts"],
        kind,
        cls(**values),
        raw.get("repo"),
        raw.get("redacted", 0),
    )


def split_torn_tail(text: str) -> tuple[str, str | None]:
    if not text or text.endswith("\n"):
        return text, None
    start = text.rfind("\n") + 1
    return text[:start], text[start:]


def replay(source: Path | Iterable[str]) -> LogReplay:
    """Replay complete JSONL lines; an unterminated final line is reported."""
    if isinstance(source, str):
        raise TypeError("replay expects a Path or iterable of text lines")
    if isinstance(source, Path):
        path = Path(source)
        if path.is_dir():
            path = path / LOG_FILE_NAME
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return LogReplay([])
        except (OSError, UnicodeError) as error:
            raise DataError(f"read friction log {path}: {error}") from error
    else:
        text = "".join(source)
    complete, torn = split_torn_tail(text)
    events: list[Event] = []
    lines: list[str] = []
    for index, original_line in enumerate(complete.splitlines(keepends=True), 1):
        line = original_line.removesuffix("\n")
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            if not isinstance(raw, dict):
                raise DataError(f"invalid friction log line {index}: expected object")
            event = event_from_dict(raw)
            validate_event(event)
            events.append(event)
            lines.append(original_line)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
            raise DataError(f"invalid friction log line {index}: {error}") from error
    return LogReplay(events, torn, tuple(lines))


def _redact_strings(value: Any, redact: Callable[[str], Any]) -> tuple[Any, int]:
    if isinstance(value, str):
        result = redact(value)
        if isinstance(result, tuple):
            return result[0], result[1]
        return result.text, result.count
    if isinstance(value, list):
        pairs = [_redact_strings(item, redact) for item in value]
        return [item for item, _ in pairs], sum(count for _, count in pairs)
    if isinstance(value, dict):
        pairs = {key: _redact_strings(item, redact) for key, item in value.items()}
        return {key: item for key, (item, _) in pairs.items()}, sum(
            count for _, count in pairs.values()
        )
    return value, 0


def append(directory: Path, event: Event, *, redact: Callable[[str], Any]) -> Event:
    """Validate, redact, and durably append an event under the canonical log lock."""
    return append_many(directory, [event], redact=redact)[0]


def append_many(
    directory: Path, events: Iterable[Event], *, redact: Callable[[str], Any]
) -> list[Event]:
    """Append a related event batch while holding one canonical log lock."""
    batch = list(events)
    lines: list[bytes] = []
    for event in batch:
        validate_event(event)
        body, count = _redact_strings(_body_dict(event.body), redact)
        persisted = event_to_dict(event)
        persisted["body"] = body
        redacted = event.redacted + count
        if redacted:
            persisted["redacted"] = redacted
        lines.append(
            json.dumps(persisted, ensure_ascii=False, separators=(",", ":")).encode()
        )
    if not lines:
        return []
    path = directory / LOG_FILE_NAME
    ensure_git_files(directory)
    with blocking_file_lock(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o666)
        try:
            size = os.lseek(descriptor, 0, os.SEEK_END)
            if size:
                os.lseek(descriptor, -1, os.SEEK_END)
                if os.read(descriptor, 1) != b"\n":
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    content = os.read(descriptor, size)
                    newline = content.rfind(b"\n")
                    os.ftruncate(descriptor, newline + 1 if newline >= 0 else 0)
            os.lseek(descriptor, 0, os.SEEK_END)
            payload = b"".join(line.rstrip(b"\n") + b"\n" for line in lines)
            if os.write(descriptor, payload) != len(payload):
                raise OSError("short write while appending friction event")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    return batch


def append_many_checked(
    directory: Path,
    prepare: Callable[[list[Event]], Iterable[Event]],
    *,
    redact: Callable[[str], Any],
) -> list[Event]:
    """Replay, choose additions, and append them under one canonical lock."""
    path = directory / LOG_FILE_NAME
    ensure_git_files(directory)
    with blocking_file_lock(path):
        return append_many_checked_under_lock(directory, prepare, redact=redact)


def append_many_checked_under_lock(
    directory: Path,
    prepare: Callable[[list[Event]], Iterable[Event]],
    *,
    redact: Callable[[str], Any],
) -> list[Event]:
    """Replay and append while the caller holds the canonical log lock."""
    path = directory / LOG_FILE_NAME
    ensure_git_files(directory)
    existing = replay(path).events
    additions = list(prepare(existing))
    lines: list[bytes] = []
    for event in additions:
        validate_event(event)
        body, count = _redact_strings(_body_dict(event.body), redact)
        persisted = event_to_dict(event)
        persisted["body"] = body
        if event.redacted + count:
            persisted["redacted"] = event.redacted + count
        lines.append(
            json.dumps(persisted, ensure_ascii=False, separators=(",", ":")).encode()
        )
    if lines:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            if size:
                stream.seek(-1, os.SEEK_END)
                if stream.read(1) != b"\n":
                    stream.seek(0)
                    content = stream.read()
                    newline = content.rfind(b"\n")
                    stream.truncate(newline + 1 if newline >= 0 else 0)
            stream.seek(0, os.SEEK_END)
            stream.write(b"".join(line + b"\n" for line in lines))
            stream.flush()
            os.fsync(stream.fileno())
    return additions


def ensure_git_files(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    gitignore = directory / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(
            "\n".join(("learn.db*", "learn.db.init.lock", *IGNORED_PATTERNS)) + "\n"
        )
    attributes = directory / ".gitattributes"
    existing = attributes.read_text() if attributes.exists() else ""
    marker = "friction.jsonl merge=union"
    if marker not in {line.strip() for line in existing.splitlines()}:
        if existing and not existing.endswith("\n"):
            existing += "\n"
        attributes.write_text(existing + marker + "\n")


def fold(events: Iterable[Event]) -> LogState:
    ordered = sorted(
        {event.id: event for event in events}.values(),
        key=lambda event: (event.ts, event.id),
    )
    items: list[LogItem] = []
    occurrences: list[LogOccurrence] = []
    status_changes: list[LogStatusChange] = []
    adoptions: list[LogAdoption] = []
    pending_occurrences: list[LogOccurrence] = []
    pending_status: list[LogStatusChange] = []
    pending_adoptions: list[LogAdoption] = []
    pending_tags: list[ItemTagsChanged] = []
    slugs: set[str] = set()
    for event in ordered:
        body = event.body
        if isinstance(body, ItemAdded):
            slug = unique_slug(slugs, safe_slug(body.title))
            slugs.add(slug)
            items.append(
                LogItem(
                    event.id,
                    slug,
                    body.title,
                    body.source,
                    body.repo_root,
                    body.target,
                    "open",
                    event.ts,
                    list(body.tags or []),
                )
            )
        elif isinstance(body, ItemTagsChanged):
            pending_tags.append(body)
        elif isinstance(body, OccurrenceAppended):
            pending_occurrences.append(
                LogOccurrence(
                    event.id,
                    body.item,
                    body.at,
                    body.cwd,
                    body.repo_root,
                    body.head_sha,
                    body.evidence,
                    body.cost,
                    body.provenance,
                )
            )
        elif isinstance(body, StatusChanged):
            pending_status.append(
                LogStatusChange(
                    event.id, body.item, body.at, body.from_, body.to, body.reason
                )
            )
        elif isinstance(body, AdoptionRecorded):
            pending_adoptions.append(
                LogAdoption(
                    event.id,
                    body.at,
                    body.summary,
                    body.files,
                    body.commit_sha,
                    body.eval_before,
                    body.eval_after,
                    body.items,
                )
            )
    index = {item.event_id: position for position, item in enumerate(items)}
    orphaned = 0
    for change in pending_status:
        position = index.get(change.item_event_id)
        if position is None:
            orphaned += 1
            continue
        item = items[position]
        items[position] = LogItem(
            item.event_id,
            item.slug,
            item.title,
            item.source,
            item.repo_root,
            item.target,
            change.to,
            item.created_at,
            item.tags,
        )
        status_changes.append(change)
    for occurrence in pending_occurrences:
        if occurrence.item_event_id in index:
            occurrences.append(occurrence)
        else:
            orphaned += 1
    for change in pending_tags:
        position = index.get(change.item)
        if position is None:
            orphaned += 1
            continue
        item = items[position]
        items[position] = LogItem(
            item.event_id,
            item.slug,
            item.title,
            item.source,
            item.repo_root,
            item.target,
            item.status,
            item.created_at,
            sorted(set(item.tags) | set(change.tags)),
        )
    for adoption in pending_adoptions:
        if all(item in index for item in adoption.item_event_ids):
            adoptions.append(adoption)
        else:
            orphaned += 1
    return LogState(items, occurrences, status_changes, adoptions, orphaned)


def fold_store(source: Path | str) -> tuple[LogState, dict[str, list[LogOccurrence]]]:
    """Fold a store log and group occurrences by their friction item event id."""
    state = fold(replay(source).events)
    grouped: dict[str, list[LogOccurrence]] = {}
    for occurrence in state.occurrences:
        grouped.setdefault(occurrence.item_event_id, []).append(occurrence)
    return state, grouped


def event_log(source: Path | str) -> FrictionEventLog:
    """Return the canonical event stream and its folded read model."""
    replayed = replay(Path(source))
    state = fold(replayed.events)
    mutable: dict[str, list[LogOccurrence]] = {}
    for occurrence in state.occurrences:
        mutable.setdefault(occurrence.item_event_id, []).append(occurrence)
    return FrictionEventLog(
        tuple(replayed.events),
        replayed.lines,
        replayed.torn_line or "",
        state,
        {key: tuple(value) for key, value in mutable.items()},
    )


def safe_slug(title: str) -> str:
    slug = ""
    separator = False
    for char in title:
        if char.isascii() and char.isalnum():
            if separator and slug:
                slug += "-"
            slug += char.lower()
            separator = False
        else:
            separator = True
        if len(slug) >= 80:
            break
    slug = slug.rstrip("-")
    if not slug:
        return "friction"
    return f"friction-{slug}" if slug.isdigit() else slug


def unique_slug(taken: set[str], base: str) -> str:
    if base not in taken:
        return base
    suffix = 2
    while f"{base}-{suffix}" in taken:
        suffix += 1
    return f"{base}-{suffix}"
