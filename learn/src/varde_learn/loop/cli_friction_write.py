"""Write commands for the friction store."""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Never

from varde_core.envelope import success
from varde_data.friction_events import event_from_dict
from varde_data.friction_events import fold as fold_friction_events
from varde_data.records.friction import Event
from varde_data.repos.friction import FrictionRepository

from varde_learn.loop.store.types import (
    AdoptionRecordRequest,
    FrictionAddMode,
    FrictionAddRequest,
    FrictionItem,
    FrictionListRequest,
    FrictionStatus,
    HistoricalCaptureRequest,
    HistoricalItemMode,
    HistoricalOccurrenceRequest,
    HistoricalWitness,
    PageRequest,
    validate_tag,
)

from . import cli_friction_read as read
from . import friction_repository
from .errors import StoreInvalid, StoreIo
from .store import historical
from .store import read as store_read
from .store import write as store_write
from .store.paths import resolve_store_dir

MAX_PAGE_LIMIT = 1_000
SIMILAR_ITEM_LIMIT = 3
MAX_PORTABLE_EVENT_BYTES = 1_048_576


def _raise(error: Exception) -> Never:
    raise error


@dataclass(frozen=True)
class PortableEvent:
    event: Event
    line: str


def parse_portable_event_markdown(text: str) -> list[PortableEvent]:
    """Parse, validate, deduplicate, and fold a portable event export."""
    parsed: dict[str, PortableEvent] = {}
    for block in re.findall(r"```jsonl\s*\n(.*?)\n```", text, re.DOTALL):
        for line in block.split("\n"):
            if not line.strip():
                continue
            if len(line.encode("utf-8")) > MAX_PORTABLE_EVENT_BYTES:
                raise StoreInvalid(
                    f"friction event exceeds {MAX_PORTABLE_EVENT_BYTES} bytes"
                )
            try:
                raw = json.loads(line)
                if not isinstance(raw, dict):
                    _raise(StoreInvalid("each JSONL event must be an object"))
                event = event_from_dict(raw)
                event.validate()
            except StoreInvalid:
                raise
            except (ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
                raise StoreInvalid(f"invalid friction event: {error}") from error
            previous = parsed.get(event.id)
            if previous is not None and previous.event.to_dict() != event.to_dict():
                raise StoreInvalid(
                    f"conflicting payload for friction event `{event.id}`"
                )
            parsed[event.id] = PortableEvent(event, line)
    events = [candidate.event for candidate in parsed.values()]
    fold_friction_events(events)
    return list(parsed.values())


def run_add_command(args: Mapping[str, Any], io: object | None = None) -> int:
    try:
        mode = _add_mode(args)
        evidence = args.get("text")
        if evidence is None:
            evidence = _stream(io, False).read()
        if not isinstance(evidence, str) or not evidence.strip():
            _raise(StoreInvalid("evidence from --text or stdin must not be blank"))
        cwd = Path.cwd()
        creating = mode.kind == "create"
        item = _with_write_store(
            lambda repository: store_write.add_friction(
                repository,
                FrictionAddRequest(mode, evidence, cwd, _tags(args.get("tag", []))),
            )
        )
        similar = (
            _with_write_store(
                lambda repository: similar_open_items(
                    repository, item.title, item.id, cwd
                )
            )
            if creating
            else []
        )
        if args.get("json"):
            _write_json(
                io,
                success(
                    read._plain({"id": item.id, "slug": item.slug, "similar": similar}),
                    {"truncated": False},
                ),
            )
        else:
            action = "Added" if creating else "Recorded occurrence for"
            _write(io, f"{action} friction item {item.id}.\n")
            for match in similar:
                _write(io, f"Similar open item {match.id}: {match.title}\n")
    except Exception as error:
        return read._report_error(io, error, bool(args.get("json")))
    else:
        return 0


def _report_import_error(
    io: object | None, error: Exception, directory: str, json_requested: bool
) -> int:
    if (
        isinstance(error, StoreIo)
        and error.operation == "inspect import directory"
        and isinstance(error.source, FileNotFoundError)
    ):
        message = (
            f"could not inspect import directory friction store at {directory}: "
            "No such file or directory (os error 2)"
        )
        if json_requested:
            from varde_core.envelope import tool_error

            read._write_json(io, tool_error(error.code, message), error=True)
        else:
            read._write(io, f"error: {message}\n", error=True)
        return 2
    return read._report_error(io, error, json_requested)


def _add_mode(args: Mapping[str, Any]) -> FrictionAddMode:
    item_id = args.get("item")
    if item_id is not None:
        if any(
            args.get(key) is not None for key in ("source", "title", "target")
        ) or args.get("global"):
            raise StoreInvalid(
                (  # noqa: UP034 - keep the wrapped message explicitly grouped
                    "--item cannot be combined with --source, --title, --target, "
                    "or --global"
                )
            )
        if int(item_id) <= 0:
            raise StoreInvalid("item ID must be a positive integer")
        return FrictionAddMode.append(int(item_id))
    source, title = args.get("source"), args.get("title")
    if source is None or title is None:
        raise StoreInvalid("provide --item, or both --source and --title")
    for name, value in (("source", source), ("title", title)):
        if not str(value).strip():
            raise StoreInvalid(f"{name} must not be blank")
    target = args.get("target")
    if target is not None and not str(target).strip():
        raise StoreInvalid("target must not be blank")
    return FrictionAddMode.create(
        str(source),
        str(title),
        None if target is None else str(target),
        bool(args.get("global")),
    )


def _tags(value: Any) -> list[str]:
    return sorted({validate_tag(str(tag)) for tag in value})


def title_tokens(title: str) -> set[str]:
    return {token.lower() for token in _split_title(title) if len(token) >= 3}


def similar_open_items(
    repository: FrictionRepository, title: str, exclude_id: int, cwd: Path
) -> list[FrictionItem]:
    wanted = title_tokens(title)
    if not wanted:
        return []
    page = store_read.list_items(
        repository,
        FrictionListRequest(
            FrictionStatus.OPEN,
            None,
            None,
            False,
            None,
            cwd,
            PageRequest(0, MAX_PAGE_LIMIT),
        ),
    )
    scored = [
        (len(wanted & title_tokens(item.title)), item)
        for item in page.items
        if item.id != exclude_id and wanted & title_tokens(item.title)
    ]
    scored.sort(key=lambda row: (-row[0], row[1].id))
    return [item for _, item in scored[:SIMILAR_ITEM_LIMIT]]


def _split_title(title: str) -> list[str]:
    import re

    return re.findall(r"[^\W_]+", title, flags=re.UNICODE)


def run_set_status_command(args: Mapping[str, Any], io: object | None = None) -> int:
    try:
        status_value = str(args.get("status", ""))
        status = FrictionStatus.parse(status_value)
        if status is None:
            _raise(StoreInvalid(f"unknown friction status `{status_value}`"))
        identifiers = args.get("id", [])
        if isinstance(identifiers, int):
            identifiers = [identifiers]

        def apply(repository):
            [store_read._get_item(repository, int(item_id)) for item_id in identifiers]
            return [
                store_write.set_friction_status(
                    repository,
                    int(item_id),
                    status,
                    str(args.get("reason", "")),
                )
                for item_id in identifiers
            ]

        items = _with_write_store(apply)
        if args.get("json"):
            data = [{"id": item.id, "status": item.status} for item in items]
            _write_json(
                io,
                success(
                    data[0] if len(data) == 1 else {"items": data}, {"truncated": False}
                ),
            )
        else:
            _write(io, "".join(f"{item.id} [{item.status}]\n" for item in items))
    except Exception as error:
        return read._report_error(io, error, bool(args.get("json")))
    else:
        return 0


def run_import_command(args: Mapping[str, Any], io: object | None = None) -> int:
    try:
        offset, limit = int(args.get("offset", 0)), int(args.get("limit", 100))
        if limit < 1 or limit > MAX_PAGE_LIMIT:
            _raise(StoreInvalid(f"page limit must be between 1 and {MAX_PAGE_LIMIT}"))
        dry_run = bool(args.get("dry_run"))
        if dry_run:
            from .store.paths import validate_global_path

            validate_global_path()
        from . import importer

        directory = Path(str(args["directory"]))
        repository = Path(str(args["repository"]))
        files = importer.read_import_files(directory, repository)
        results = []
        summary = importer.FrictionImportSummary(total=len(files))
        for file in files:
            if file.entry is None:
                summary.skipped += 1
                results.append(_import_result(file.file, "skipped", reason=file.reason))
                continue
            entry = file.entry
            if dry_run:
                summary.would_import += 1
                results.append(
                    _import_result(
                        file.file,
                        "would_import",
                        id=entry.id,
                        slug=entry.slug,
                        title=entry.title,
                        source=entry.source,
                        status=entry.status.as_str(),
                    )
                )
                continue
            item = _with_write_store(
                lambda repository, entry=entry: store_write.import_friction(
                    repository, entry
                )
            )
            if item is None:
                summary.skipped += 1
                results.append(
                    _import_result(
                        file.file,
                        "skipped",
                        reason="slug already exists",
                        slug=entry.slug,
                        title=entry.title,
                        source=entry.source,
                        status=entry.status.as_str(),
                    )
                )
            else:
                summary.imported += 1
                results.append(
                    _import_result(
                        file.file,
                        "imported",
                        id=item.id,
                        slug=item.slug,
                        title=item.title,
                        source=item.source,
                        status=item.status,
                    )
                )
        start = min(max(offset, 0), len(results))
        end = min(start + limit, len(results))
        next_offset = end if end < len(results) else None
        page = results[start:end]
        meta = {
            "total": len(results),
            "offset": offset,
            "limit": limit,
            "next_offset": next_offset,
            "truncated": next_offset is not None,
        }
        if args.get("json"):
            _write_json(
                io, success({"summary": asdict(summary), "results": page}, meta)
            )
        else:
            lines = [
                f"{result['outcome']}: {result['file']}"
                + (
                    f" ({result['reason']})"
                    if result.get("reason")
                    else f" - {result['title']}"
                    if result.get("title")
                    else ""
                )
                for result in page
            ]
            lines.append(
                (  # noqa: UP034 - keep the wrapped output explicitly grouped
                    f"Import report: {summary.total} total, "
                    f"{summary.imported} imported, "
                    f"{summary.would_import} would import, "
                    f"{summary.skipped} skipped."
                )
            )
            if next_offset is not None:
                lines.append(
                    f"Continue the report with --offset {next_offset} --limit {limit}."
                )
            _write(io, "\n".join(lines) + "\n")
    except Exception as error:
        return _report_import_error(
            io, error, str(args.get("directory", "")), bool(args.get("json"))
        )
    else:
        return 0


def _import_result(file: str, outcome: str, **values: Any) -> dict[str, Any]:
    result = {
        "file": file,
        "outcome": outcome,
        "reason": None,
        "id": None,
        "slug": None,
        "title": None,
        "source": None,
        "status": None,
    }
    result.update(values)
    return result


def run_adopt_record_command(args: Mapping[str, Any], io: object | None = None) -> int:
    try:
        item_ids = list(args.get("items", []))
        if not item_ids:
            _raise(StoreInvalid("at least one item ID is required"))
        seen: set[int] = set()
        for item_id in item_ids:
            if int(item_id) <= 0:
                _raise(StoreInvalid("item IDs must be positive integers"))
            if int(item_id) in seen:
                _raise(StoreInvalid("item IDs must not contain duplicates"))
            seen.add(int(item_id))
        summary = str(args.get("summary", ""))
        if not summary.strip():
            _raise(StoreInvalid("summary must not be blank"))
        files = list(args.get("files", []))
        if not files:
            _raise(StoreInvalid("at least one file path is required"))
        if any(not str(path).strip() for path in files):
            _raise(StoreInvalid("file paths must not be blank"))
        commit = args.get("commit")
        if commit is not None and not str(commit).strip():
            _raise(StoreInvalid("commit SHA must not be blank"))
        eval_before = read_benchmark_json(args.get("eval_before"), "--eval-before")
        eval_after = read_benchmark_json(args.get("eval_after"), "--eval-after")
        adoption = _with_write_store(
            lambda repository: store_write.record_adoption(
                repository,
                AdoptionRecordRequest(
                    item_ids, summary, files, commit, eval_before, eval_after
                ),
            )
        )
        data = {"adoption_id": adoption.id, "items": adoption.item_ids}
        if args.get("json"):
            _write_json(io, success(data, {"truncated": False}))
        else:
            _write(
                io,
                (
                    f"Recorded adoption {adoption.id} for "
                    f"{len(adoption.item_ids)} friction items.\n"
                ),
            )
    except Exception as error:
        return read._report_error(io, error, bool(args.get("json")))
    else:
        return 0


def run_event_import_command(args: Mapping[str, Any], io: object | None = None) -> int:
    """Union raw event blocks from a portable Markdown export."""
    try:
        path = Path(str(args["file"]))
        candidates = parse_portable_event_markdown(path.read_text(encoding="utf-8"))
        result = friction_repository.with_repository(
            lambda repository: repository.import_events(
                (candidate.event for candidate in candidates),
                dry_run=bool(args.get("dry_run")),
            ),
            resolve_store_dir(),
        )
        added = len(candidates) - result.present if result.dry_run else result.imported
        action = "Would import" if result.dry_run else "Imported"
        read._write(
            io,
            f"{action} {added} new friction events; "
            f"{result.present} already present.\n",
        )
    except Exception as error:
        return read._report_error(io, error, False)
    else:
        return 0


def read_benchmark_json(path: str | Path | None, option: str) -> str | None:
    if path is None:
        return None
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise StoreInvalid(f"could not read {option} file {path}: {error}") from error
    try:
        json.loads(raw)
    except json.JSONDecodeError as error:
        raise StoreInvalid(f"{option} file must contain valid JSON: {error}") from error
    return raw


def record_historical_capture(request: dict[str, Any]) -> dict[str, Any]:
    record = request["record"]
    source = request["source"]
    anchor = request["anchor"]
    item = request["item"]
    mode = (
        HistoricalItemMode.append(int(item["id"]))
        if item.get("mode") == "existing"
        else HistoricalItemMode.create(
            item["source"], item["title"], item.get("target"), None
        )
    )
    witness = HistoricalWitness(
        source["harness"],
        request["session_id"],
        request["incident_kind"],
        anchor.get("native_id"),
        anchor["source_id"],
        int(anchor["record_index"]),
        int(anchor["byte_start"]),
        int(anchor["byte_end"]),
        anchor["record_digest"],
    )
    occurrence = HistoricalOccurrenceRequest(
        record["timestamp"],
        record["cwd"],
        None,
        None,
        request["evidence"],
        {
            "event": record.get("native_facts", {}),
            "context": {
                "cwd": record["cwd"],
                "session_location": record.get("session_location"),
                "location_provenance": record.get("location_provenance"),
            },
        },
        witness,
    )
    result = _with_write_store(
        lambda repository: historical.record_historical_occurrence(
            repository,
            HistoricalCaptureRequest(mode, occurrence),
        )
    )
    return {
        "disposition": "created" if result.created else "already-recorded",
        "item_id": result.item.id,
        "occurrence_id": result.occurrence.id,
        "at": result.occurrence.at,
        "cwd": result.occurrence.cwd,
        "repo_root": result.occurrence.repo_root,
        "head_sha": result.occurrence.head_sha,
    }


def _with_write_store[T](
    operation: Callable[[FrictionRepository], T], store_dir: Path | None = None
) -> T:
    root = store_dir or resolve_store_dir()
    return friction_repository.with_repository(operation, root)


def _stream(io: object | None, error: bool):
    name = "stderr" if error else "stdin"
    stream = getattr(io, name, None) if io is not None else None
    return stream if stream is not None else getattr(sys, name)


def _write(io: object | None, value: str) -> None:
    stream = getattr(io, "stdout", None) if io is not None else None
    if stream is None:
        stream = sys.stdout
    stream.write(value)


def _write_json(
    io: object | None, value: dict[str, Any], *, error: bool = False
) -> None:
    import json

    name = "stderr" if error else "stdout"
    stream = getattr(io, name, None) if io is not None else None
    if stream is None:
        stream = getattr(sys, name)
    stream.write(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    )
