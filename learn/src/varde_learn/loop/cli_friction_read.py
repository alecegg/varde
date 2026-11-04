"""Read-only friction command entry points."""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Never

from varde_core.envelope import success, tool_error
from varde_data.records.friction import (
    ItemAdded,
    ItemTagsChanged,
    OccurrenceAppended,
    StatusChanged,
)

from varde_learn.loop.store import read
from varde_learn.loop.store.types import (
    FrictionExportItem,
    FrictionIncidentProvenance,
    FrictionListRequest,
    FrictionStatus,
    PageRequest,
)

from . import friction_repository
from .errors import StoreInvalid
from .store.paths import resolve_store_dir


def _raise(error: Exception) -> Never:
    raise error


def run_list(args: Mapping[str, Any], io: object | None = None) -> int | None:
    """List friction items using the existing store reader."""
    try:
        if args.get("global") and args.get("repository") is not None:
            _raise(StoreInvalid("--repository and --global cannot be combined"))
        status_value = args.get("status")
        status = None
        if status_value is not None:
            status = FrictionStatus.parse(str(status_value))
            if status is None:
                _raise(StoreInvalid(f"unknown friction status `{status_value}`"))
        page = PageRequest(
            offset=int(args.get("offset", 0)), limit=int(args.get("limit", 100))
        )
        request = FrictionListRequest(
            status=status,
            source=_optional_str(args, "source"),
            repo_root=Path(str(args["repository"]))
            if args.get("repository") is not None
            else None,
            global_=bool(args.get("global", False)),
            text=_optional_str(args, "text"),
            cwd=Path.cwd(),
            page=page,
            tag=_optional_str(args, "tag"),
        )
        result = friction_repository.with_repository(
            lambda repository: read.list_items(repository, request)
        )
        if args.get("json"):
            data = {"items": result.items}
            meta = {
                "total": result.total,
                "offset": result.offset,
                "limit": result.limit,
                "next_offset": result.next_offset,
                "truncated": result.truncated,
            }
            _write_json(io, success(_plain(data), meta))
        elif not result.items:
            _write(io, "No friction items found.\n")
        else:
            lines = [
                f"{item.id} {item.slug} [{item.status}] {item.title} ({item.source})"
                + (f" [{','.join(item.tags)}]" if item.tags else "")
                for item in result.items
            ]
            if result.truncated:
                next_offset = result.next_offset
                if next_offset is None:
                    next_offset = result.offset + result.limit
                lines.append(
                    (  # noqa: UP034 - keep the wrapped output explicitly grouped
                        f"Showing {result.offset + result.limit} of {result.total}; "
                        "continue with "
                        f"--offset {next_offset} "
                        f"--limit {result.limit}."
                    )
                )
            _write(io, "\n".join(lines) + "\n")
    except Exception as error:
        return _report_error(io, error, bool(args.get("json")))
    else:
        return 0


def run_show(args: Mapping[str, Any], io: object | None = None) -> int | None:
    """Show one friction item and its paged history."""
    try:
        page = PageRequest(
            offset=int(args.get("offset", 0)), limit=int(args.get("limit", 100))
        )
        identifiers = args.get("id", "")
        if isinstance(identifiers, (str, int)):
            identifiers = [identifiers]
        results = [
            friction_repository.with_repository(
                lambda repository, identifier=str(identifier): read.show_friction(
                    repository, identifier, page
                )
            )
            for identifier in identifiers
        ]
        if args.get("brief"):
            last_results = [
                friction_repository.with_repository(
                    lambda repository, result=result: read.show_friction(
                        repository,
                        str(result.item.id),
                        PageRequest(max(0, result.occurrences.total - 1), 1),
                    )
                )
                for result in results
            ]
            _write(io, _brief_show_lines(last_results))
            return 0
        if len(results) > 1 and args.get("json"):
            _write_multiple_show_json(results, io)
            return 0
        if len(results) > 1:
            _write_multiple_shows(results, page, io)
            return 0
        result = results[0]
        truncated = result.occurrences.truncated or result.status_changes.truncated
        next_offset = (
            result.occurrences.next_offset or result.status_changes.next_offset
        )
        if args.get("json"):
            data = {
                "item": result.item,
                "occurrences": [
                    {
                        key: value
                        for key, value in _plain(occurrence).items()
                        if key != "provenance"
                    }
                    for occurrence in result.occurrences.items
                ],
                "status_changes": result.status_changes.items,
            }
            meta = {
                "total": {
                    "occurrences": result.occurrences.total,
                    "status_changes": result.status_changes.total,
                },
                "offset": page.offset,
                "limit": page.limit,
                "next_offset": next_offset,
                "truncated": truncated,
            }
            _write_json(io, success(_plain(data), meta))
        else:
            lines = [
                (
                    f"{result.item.id} {result.item.slug} [{result.item.status}] "
                    f"{result.item.title} ({result.item.source})"
                )
            ]
            if result.item.target is not None:
                lines.append(f"Target: {result.item.target}")
            if result.item.tags:
                lines.append(f"Tags: {', '.join(result.item.tags)}")
            if result.item.repo_root is not None:
                lines.append(f"Repository: {result.item.repo_root}")
            else:
                lines.append("Repository: global")
            lines.append(f"Occurrences ({page.offset}/{result.occurrences.total})")
            for occurrence in result.occurrences.items:
                lines.append(
                    f"- {occurrence.id} at {occurrence.at}: {occurrence.evidence}"
                )
                if occurrence.provenance is not None:
                    lines.append(f"  Incident: {occurrence.provenance.incident_key}")
            lines.append(
                f"Status history ({page.offset}/{result.status_changes.total})"
            )
            lines.extend(
                f"- {change.id} {change.from_status} -> {change.to_status} "
                f"at {change.at}: {change.reason}"
                for change in result.status_changes.items
            )
            if truncated:
                offset = (
                    next_offset if next_offset is not None else page.offset + page.limit
                )
                lines.append(f"Continue with --offset {offset} --limit {page.limit}.")
            _write(io, "\n".join(lines) + "\n")
    except Exception as error:
        return _report_error(io, error, bool(args.get("json")))
    else:
        return 0


def _brief_show_lines(results: list[Any]) -> str:
    lines = []
    for result in results:
        item = result.item
        evidence = (
            result.occurrences.items[-1].evidence if result.occurrences.items else ""
        )
        suffix = "…" if len(evidence) > 200 else ""
        lines.append(
            (  # noqa: UP034 - keep the wrapped output explicitly grouped
                f"{item.id} [{item.status}] {item.title} | "
                f"{item.target or 'no target'} | {result.occurrences.total} "
                f"occurrences | {evidence[:200]}{suffix}"
            )
        )
    return "\n".join(lines) + ("\n" if lines else "")


def _write_multiple_shows(
    results: list[Any], page: PageRequest, io: object | None
) -> None:
    lines = []
    for result in results:
        item = result.item
        lines.append(
            f"{item.id} {item.slug} [{item.status}] {item.title} ({item.source})"
        )
        if item.target is not None:
            lines.append(f"Target: {item.target}")
        lines.append(f"Occurrences ({page.offset}/{result.occurrences.total})")
        lines.extend(
            f"- {entry.id} at {entry.at}: {entry.evidence}"
            for entry in result.occurrences.items
        )
        lines.append(f"Status history ({page.offset}/{result.status_changes.total})")
        lines.extend(
            (
                f"- {change.id} {change.from_status} -> {change.to_status} "
                f"at {change.at}: {change.reason}"
            )
            for change in result.status_changes.items
        )
    _write(io, "\n".join(lines) + "\n")


def _write_multiple_show_json(results: list[Any], io: object | None) -> None:
    data = [
        {
            "item": result.item,
            "occurrences": [
                {
                    key: value
                    for key, value in _plain(entry).items()
                    if key != "provenance"
                }
                for entry in result.occurrences.items
            ],
            "status_changes": result.status_changes.items,
        }
        for result in results
    ]
    truncated = any(
        result.occurrences.truncated or result.status_changes.truncated
        for result in results
    )
    _write_json(io, success(_plain({"items": data}), {"truncated": truncated}))


def run_export(args: Mapping[str, Any], io: object | None = None) -> int | None:
    """Export friction items as Markdown files without overwriting paths."""
    try:
        if args.get("md"):
            return _run_event_export(args, io)
        items = friction_repository.with_repository(read.export_items)
        directory = _prepare_export_directory(Path(str(args.get("directory", ""))))
        filenames = _preflight_export_paths(directory, items)
        for item, filename in zip(items, filenames, strict=True):
            with (directory / filename).open("x", encoding="utf-8") as file:
                file.write(_render_friction_markdown(item))
        if args.get("json"):
            _write_json(io, success({"exported": len(items)}, {"truncated": False}))
        else:
            _write(io, f"Exported {len(items)} friction items to {directory}.\n")
    except Exception as error:
        return _report_error(io, error, bool(args.get("json")))
    else:
        return 0


def _run_event_export(args: Mapping[str, Any], io: object | None) -> int:
    event_log = friction_repository.open_repository(resolve_store_dir()).event_log()
    state = event_log.state
    item_by_event = {item.event_id: item for item in state.items}
    status = {item.event_id: item.status for item in state.items}
    grouped: dict[str, dict[str, list[str]]] = {
        key: {} for key in ("open", "resolved", "promoted", "archived")
    }
    unattached_events = []
    sections = ["# Varde friction export", ""]
    for event, raw_line in zip(event_log.events, event_log.lines, strict=True):
        line = raw_line.rstrip("\r\n")
        if isinstance(event.body, ItemAdded):
            item_ids = [event.id]
        elif isinstance(
            event.body, (ItemTagsChanged, OccurrenceAppended, StatusChanged)
        ):
            item_ids = [event.body.item]
        else:
            item_ids = list(event.body.items)
        attached = False
        for item_id in item_ids:
            event_status = status.get(item_id)
            if item_id in item_by_event and event_status in grouped:
                grouped[event_status].setdefault(item_id, []).append(line)
                attached = True
        if not attached:
            unattached_events.append(line)
    for state_name, item_events in grouped.items():
        sections.extend((f"## {state_name}", ""))
        for item_id, event_lines in sorted(item_events.items()):
            item = item_by_event[item_id]
            title = " ".join(item.title.split())
            sections.extend(
                (f"### {title} ({item_id})", "```jsonl", *event_lines, "```", "")
            )
    if unattached_events:
        sections.extend(
            (
                "## open",
                "",
                "### Unattached events\n",
                "```jsonl",
                *unattached_events,
                "```",
                "",
            )
        )
    output = "\n".join(sections).rstrip() + "\n"
    destination = args.get("out")
    if destination:
        Path(str(destination)).write_text(output, encoding="utf-8")
    else:
        _write(io, output)
    return 0


def run_adopt_recurrence(
    args: Mapping[str, Any], io: object | None = None
) -> int | None:
    """List adopted friction items with later occurrences."""
    try:
        page = PageRequest(
            offset=int(args.get("offset", 0)), limit=int(args.get("limit", 100))
        )
        report = friction_repository.with_repository(
            lambda repository: read.list_recurrences(repository, page)
        )
        result = report.page
        if args.get("json"):
            data = {"items": result.items}
            meta = {
                "total": result.total,
                "offset": result.offset,
                "limit": result.limit,
                "next_offset": result.next_offset,
                "truncated": result.truncated,
                "skipped_invalid_timestamps": report.skipped_invalid_timestamps,
            }
            _write_json(io, success(_plain(data), meta))
        else:
            lines = []
            if not result.items:
                lines.append("No adoption recurrences found.")
            else:
                lines.extend(
                    (
                        f"{recurrence.item.id} {recurrence.item.title} "
                        f"recurred after adoption {recurrence.adoption_id} "
                        f"({recurrence.summary}) at {recurrence.occurrence.at}: "
                        f"{recurrence.occurrence.evidence}"
                    )
                    for recurrence in result.items
                )
                if result.truncated:
                    offset = (
                        result.next_offset
                        if result.next_offset is not None
                        else result.offset + result.limit
                    )
                    lines.append(
                        (  # noqa: UP034 - keep the wrapped output explicitly grouped
                            f"Showing {result.offset + result.limit} of "
                            f"{result.total}; continue with "
                            f"--offset {offset} --limit {result.limit}."
                        )
                    )
            if report.skipped_invalid_timestamps > 0:
                lines.append(
                    (  # noqa: UP034 - keep the wrapped output explicitly grouped
                        f"Skipped {report.skipped_invalid_timestamps} linked "
                        "timestamps SQLite could not parse."
                    )
                )
            _write(io, "\n".join(lines) + "\n")
    except Exception as error:
        return _report_error(io, error, bool(args.get("json")))
    else:
        return 0


def _prepare_export_directory(path: Path) -> Path:
    try:
        path.lstat()
    except FileNotFoundError:
        path.mkdir(parents=True, exist_ok=True)
    else:
        if path.is_symlink():
            raise StoreInvalid(
                f"refusing to export through symlinked directory `{path}`"
            )
        if not path.is_dir():
            raise StoreInvalid(f"export destination `{path}` is not a directory")
    return path.resolve(strict=True)


def _preflight_export_paths(
    directory: Path, items: list[FrictionExportItem]
) -> list[str]:
    filenames = []
    seen = set()
    for export in items:
        filename = f"{_safe_export_slug(export.item.slug, export.item.id)}.md"
        if filename in seen:
            raise StoreInvalid(
                f"multiple friction items map to export file `{filename}`"
            )
        seen.add(filename)
        destination = directory / filename
        try:
            destination.lstat()
        except FileNotFoundError:
            pass
        else:
            raise StoreInvalid(
                f"refusing to overwrite existing export path `{destination}`"
            )
        filenames.append(filename)
    return filenames


def _safe_export_slug(slug: str, item_id: int) -> str:
    encoded = slug.encode("utf-8")
    if encoded and all(
        byte in range(48, 58)
        or byte in range(65, 91)
        or byte in range(97, 123)
        or byte == 45
        for byte in encoded
    ):
        return slug
    output = []
    separator = False
    for byte in encoded:
        if byte in range(48, 58) or byte in range(65, 91) or byte in range(97, 123):
            if separator and output:
                output.append("-")
            output.append(chr(byte).lower())
            separator = False
        else:
            separator = True
    safe = "".join(output) or "friction"
    return f"{safe}-{item_id}"


def _render_friction_markdown(export: FrictionExportItem) -> str:
    item = export.item
    occurrences = export.occurrences
    changes = export.status_changes
    output = ['---\nformat: "varde-friction-item"\nversion: 1\n', f"id: {item.id}\n"]
    output.extend(
        _yaml_string(key, getattr(item, key)) for key in ("slug", "title", "source")
    )
    output.append(_yaml_optional_string("repo_root", item.repo_root))
    output.append(_yaml_string("status", item.status))
    output.append(_yaml_optional_string("target", item.target))
    output.append("tags: [" + ", ".join(json.dumps(tag) for tag in item.tags) + "]\n")
    output.append(_yaml_string("created_at", item.created_at))
    if not occurrences:
        output.append("occurrences: []\n")
    else:
        output.append("occurrences:\n")
        for occurrence in occurrences:
            output.append(
                f"  - id: {occurrence.id}\n    item_id: {occurrence.item_id}\n"
            )
            output.append(_yaml_string("at", occurrence.at, "    "))
            output.append(_yaml_string("cwd", occurrence.cwd, "    "))
            output.append(
                _yaml_optional_string("repo_root", occurrence.repo_root, "    ")
            )
            output.append(
                _yaml_optional_string("head_sha", occurrence.head_sha, "    ")
            )
            output.append(_yaml_string("evidence", occurrence.evidence, "    "))
            output.append(_yaml_optional_string("cost", occurrence.cost, "    "))
            if occurrence.provenance is not None:
                output.append(_render_incident_provenance(occurrence.provenance))
    if not changes:
        output.append("status_changes: []\n")
    else:
        output.append("status_changes:\n")
        for change in changes:
            output.append(f"  - id: {change.id}\n    item_id: {change.item_id}\n")
            output.append(_yaml_string("at", change.at, "    "))
            output.append(_yaml_string("from_status", change.from_status, "    "))
            output.append(_yaml_string("to_status", change.to_status, "    "))
            output.append(_yaml_string("reason", change.reason, "    "))
    output.extend(("---\n\n", f"# Friction item {item.id}\n\n", "## Title\n\n"))
    output.append(_markdown_text_block(item.title))
    output.append("## Occurrences\n\n")
    for occurrence in occurrences:
        output.extend(
            (f"### Occurrence {occurrence.id}\n\n", f"- Recorded: {occurrence.at}\n")
        )
        output.append(f"- Repository: {occurrence.repo_root or 'global'}\n")
        output.extend(("- Evidence:\n\n", _markdown_text_block(occurrence.evidence)))
    output.append("## Status history\n\n")
    for change in changes:
        output.extend(
            (
                (
                    f"### Change {change.id}: {change.from_status} → "
                    f"{change.to_status}\n\n"
                ),
                f"- Recorded: {change.at}\n- Reason:\n\n",
                _markdown_text_block(change.reason),
            )
        )
    return "".join(output)


def _yaml_string(key: str, value: str, indent: str = "") -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace(
        "\u0085", "\\u0085"
    )
    return f"{indent}{key}: {encoded}\n"


def _yaml_optional_string(key: str, value: str | None, indent: str = "") -> str:
    return (
        _yaml_string(key, value, indent)
        if value is not None
        else f"{indent}{key}: null\n"
    )


def _render_incident_provenance(provenance: FrictionIncidentProvenance) -> str:
    output = [
        "    provenance:\n",
        f"      identity_version: {provenance.identity_version}\n",
    ]
    output.extend(
        _yaml_string(key, getattr(provenance, key), "      ")
        for key in ("incident_key", "harness", "thread_id", "incident_kind")
    )
    output.append(_yaml_optional_string("witness_id", provenance.witness_id, "      "))
    output.append(_yaml_string("source_id", provenance.source_id, "      "))
    output.append(
        f"      record_index: {provenance.record_index}\n"
        f"      byte_start: {provenance.byte_start}\n"
        f"      byte_end: {provenance.byte_end}\n"
    )
    output.append(_yaml_string("record_digest", provenance.record_digest, "      "))
    output.append(_yaml_string("payload_digest", provenance.payload_digest, "      "))
    return "".join(output)


def _markdown_text_block(value: str) -> str:
    longest = 0
    current = 0
    for character in value:
        if character == "`":
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    fence = "`" * (max(longest, 2) + 1)
    body = value if value.endswith("\n") else value + "\n"
    return f"{fence}text\n{body}{fence}\n\n"


def _optional_str(args: Mapping[str, Any], key: str) -> str | None:
    value = args.get(key)
    return str(value) if value is not None else None


def _plain(value: object) -> Any:
    from dataclasses import fields, is_dataclass

    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _plain(getattr(value, field.name)) for field in fields(value)
        }
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    return value


def _write_json(io: object | None, value: object, *, error: bool = False) -> None:
    stream = _stream(io, error)
    stream.write(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    )


def _write(io: object | None, value: str, *, error: bool = False) -> None:
    _stream(io, error).write(value)


def _stream(io: object | None, error: bool):
    name = "stderr" if error else "stdout"
    stream = getattr(io, name, None) if io is not None else None
    return stream if stream is not None else getattr(sys, name)


def _report_error(io: object | None, error: Exception, json_requested: bool) -> int:
    code = getattr(error, "code", "store_error")
    if json_requested:
        _write_json(io, tool_error(code, str(error)), error=True)
    else:
        _write(io, f"error: {error}\n", error=True)
    return 2
