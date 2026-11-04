"""Strict request and frozen-evidence validation for historical capture."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Never

MAX_CAPTURE_BYTES = 64 * 1024
MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024


def _raise(error: Exception) -> Never:
    raise error


@dataclass
class CaptureError(ValueError):
    code: str
    message: str

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class CaptureFlags:
    snapshot_path: Path
    source_id: str
    record_index: int
    native_id: str | None
    kind: str
    item_id: int | None
    item_source: str | None
    item_title: str | None
    item_target: str | None
    evidence: str


def capture(
    path: Path, *, persist: Callable[[dict[str, Any]], dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Read one strict capture request, verify its frozen record, then persist it."""
    try:
        metadata = path.lstat()
    except OSError as error:
        raise CaptureError(
            "diagnose_capture_invalid", f"cannot stat capture request: {error}"
        ) from error
    if path.is_symlink() or not path.is_file():
        raise CaptureError(
            "diagnose_capture_invalid", "capture request must be a regular file"
        )
    if metadata.st_size > MAX_CAPTURE_BYTES:
        raise CaptureError(
            "diagnose_capture_limit", "capture request exceeds the 64 KiB limit"
        )
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise CaptureError(
            "diagnose_capture_invalid", f"cannot read capture request: {error}"
        ) from error
    if len(raw) > MAX_CAPTURE_BYTES:
        raise CaptureError(
            "diagnose_capture_limit", "capture request exceeds the 64 KiB limit"
        )
    try:
        request = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        reason = _rust_json_error(raw, error)
        raise CaptureError(
            "diagnose_capture_invalid", f"invalid strict capture request JSON: {reason}"
        ) from error
    if not isinstance(request, dict) or set(request) != {
        "snapshot_path",
        "snapshot_digest",
        "session_id",
        "anchor",
        "incident_kind",
        "item",
        "evidence",
    }:
        raise CaptureError(
            "diagnose_capture_invalid",
            "invalid strict capture request JSON: missing or unknown fields",
        )
    _validate_kind(request.get("incident_kind"))
    _validate_item(request.get("item"))
    _validate_anchor(request.get("anchor"))
    if not isinstance(request.get("snapshot_path"), str) or not isinstance(
        request.get("snapshot_digest"), str
    ):
        raise CaptureError(
            "diagnose_capture_invalid",
            "invalid strict capture request JSON: invalid snapshot identity",
        )
    return _capture_request(request, persist)


def capture_from_flags(
    flags: CaptureFlags,
    *,
    persist: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a strict capture request by selecting one record from a snapshot."""
    _validate_kind(flags.kind)
    item = _item_from_flags(flags)
    snapshot = load_snapshot(flags.snapshot_path)
    matches = [
        record
        for record in snapshot["records"]
        if record.get("anchor", {}).get("source_id") == flags.source_id
        and record.get("anchor", {}).get("record_index") == flags.record_index
        and (
            flags.native_id is None
            or record.get("anchor", {}).get("native_id") == flags.native_id
        )
    ]
    if not matches:
        raise CaptureError(
            "diagnose_record_not_found",
            (
                "no record in the frozen evidence matches --source-id, "
                "--record-index, and --native-id"
            ),
        )
    if len(matches) != 1:
        raise CaptureError(
            "diagnose_record_ambiguous",
            "more than one record matches; pass --native-id to select one",
        )
    return _capture_request(
        {
            "snapshot_path": str(flags.snapshot_path),
            "snapshot_digest": snapshot["digest"],
            "session_id": snapshot["session"]["thread_id"],
            "anchor": matches[0]["anchor"],
            "incident_kind": flags.kind,
            "item": item,
            "evidence": flags.evidence,
        },
        persist,
        snapshot=snapshot,
    )


def load_snapshot(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise CaptureError(
            "diagnose_snapshot_invalid", f"cannot stat snapshot: {error}"
        ) from error
    if len(raw) > MAX_SNAPSHOT_BYTES:
        raise CaptureError(
            "diagnose_snapshot_limit", "snapshot file exceeds the supported byte limit"
        )
    try:
        snapshot = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CaptureError(
            "diagnose_snapshot_invalid",
            f"invalid snapshot JSON: {_rust_json_error(raw, error)}",
        ) from error
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") not in {1, 2}:
        raise CaptureError(
            "diagnose_snapshot_version", "unsupported snapshot schema version"
        )
    digest = snapshot.get("digest")
    if not isinstance(digest, str):
        raise CaptureError(
            "diagnose_snapshot_invalid", "snapshot digest does not match its contents"
        )
    unsigned = dict(snapshot)
    unsigned["digest"] = ""
    encoded = json.dumps(unsigned, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    if "sha256:" + hashlib.sha256(encoded).hexdigest() != digest:
        raise CaptureError(
            "diagnose_snapshot_invalid", "snapshot digest does not match its contents"
        )
    records, sources = snapshot.get("records"), snapshot.get("sources")
    if not isinstance(records, list) or not isinstance(sources, list):
        raise CaptureError(
            "diagnose_snapshot_invalid", "snapshot is missing its source identity"
        )
    for record in records:
        if isinstance(record, dict):
            record.setdefault("tool_output_length_bytes", None)
            observations = record.get("tool_observations")
            if isinstance(observations, list):
                for observation in observations:
                    if isinstance(observation, dict):
                        observation.setdefault("output_length_bytes", None)
    return snapshot


def _capture_request(request: dict[str, Any], persist, *, snapshot=None):
    session_id = request.get("session_id")
    evidence = request.get("evidence")
    if (
        not isinstance(session_id, str)
        or not session_id.strip()
        or not isinstance(evidence, str)
        or not evidence.strip()
    ):
        raise CaptureError(
            "diagnose_capture_invalid",
            "session ID and observed evidence must not be blank",
        )
    if len(evidence.encode("utf-8")) > 8 * 1024:
        raise CaptureError(
            "diagnose_capture_limit", "observed evidence exceeds the 8 KiB limit"
        )
    if snapshot is None:
        snapshot = load_snapshot(Path(request["snapshot_path"]))
    if snapshot.get("digest") != request.get("snapshot_digest"):
        raise CaptureError(
            "diagnose_snapshot_invalid",
            "capture request snapshot digest does not match the frozen evidence",
        )
    if snapshot.get("session", {}).get("thread_id") != session_id:
        raise CaptureError(
            "diagnose_capture_invalid",
            "capture session ID does not match the frozen evidence session",
        )
    if snapshot.get("overlap") in {"current", "unknown"} and not snapshot.get(
        "coverage", {}
    ).get("cutoff_verified"):
        raise CaptureError(
            "diagnose_capture_incomplete",
            (
                "current or unknown session overlap requires a verified "
                "pre-orchestration cutoff"
            ),
        )
    anchor = request.get("anchor")
    if not isinstance(anchor, dict):
        raise CaptureError(
            "diagnose_capture_invalid",
            "selected record anchor is not present in the frozen evidence",
        )
    records = [
        record for record in snapshot["records"] if record.get("anchor") == anchor
    ]
    if len(records) != 1:
        reason = (
            "selected record anchor is ambiguous in the frozen evidence"
            if len(records) > 1
            else "selected record anchor is not present in the frozen evidence"
        )
        raise CaptureError("diagnose_capture_invalid", reason)
    record = records[0]
    if not record.get("session_thread_id", "").strip():
        raise CaptureError(
            "diagnose_capture_uncertain",
            "selected event has no verified native session identity",
        )
    source_rows = [
        source
        for source in snapshot["sources"]
        if source.get("source_id") == anchor.get("source_id")
    ]
    if len(source_rows) != 1 or source_rows[0].get("harness") != snapshot.get(
        "session", {}
    ).get("harness"):
        raise CaptureError(
            "diagnose_capture_invalid",
            "selected source harness does not match the frozen session identity",
        )
    _revalidate_record_anchor(source_rows[0], anchor)
    _validate_tool_projection(source_rows[0], anchor, record)
    timestamp, cwd = record.get("timestamp"), record.get("cwd")
    if cwd is None and source_rows[0].get("format") == "opencode-sqlite-2.0.12":
        cwd = _opencode_session_directory(
            source_rows[0]["canonical_path"], anchor.get("session_id")
        )
    if not isinstance(timestamp, str) or not timestamp.strip():
        raise CaptureError(
            "diagnose_capture_uncertain",
            "selected event has no verified native timestamp",
        )
    if not isinstance(cwd, str) or not cwd.strip():
        raise CaptureError(
            "diagnose_capture_uncertain",
            "selected event has no verified historical working directory",
        )
    if request["incident_kind"] == "failed-tool" and not (
        record.get("tool_output_excerpt")
        or record.get("tool_error")
        or record.get("tool_observations")
    ):
        raise CaptureError(
            "diagnose_capture_kind_invalid",
            (
                "failed-tool capture requires verified native tool output for "
                "analyst review"
            ),
        )
    item = request["item"]
    if item["mode"] == "existing" and item["id"] <= 0:
        raise CaptureError(
            "diagnose_capture_invalid", "existing friction item ID must be positive"
        )
    if item["mode"] == "new" and any(
        not isinstance(item.get(key), str) or not item[key].strip()
        for key in ("source", "title")
    ):
        raise CaptureError(
            "diagnose_capture_invalid",
            "new friction item source, title, and optional target must not be blank",
        )
    if (
        item["mode"] == "new"
        and item.get("target") is not None
        and not item["target"].strip()
    ):
        raise CaptureError(
            "diagnose_capture_invalid",
            "new friction item source, title, and optional target must not be blank",
        )
    if persist is None:
        raise CaptureError(
            "diagnose_capture_store_unavailable",
            "historical capture store interface is not available",
        )
    request["record"] = record
    record["cwd"] = cwd
    request["source"] = source_rows[0]
    return persist(request)


def _validate_tool_projection(
    source: dict[str, Any], anchor: dict[str, Any], frozen: dict[str, Any]
) -> None:
    path = Path(source["canonical_path"])
    harness = source["harness"]
    if harness == "codex":
        from .codex import parse_source

        native_records = parse_source(path).records
    elif harness == "claude":
        from .claude import inspect_path

        native_records = inspect_path(path.parent.parent, path).records
    elif harness == "opencode":
        from .opencode import inspect_path

        native_records = inspect_path(path, anchor.get("session_id")).records
    else:
        raise CaptureError(
            "diagnose_capture_uncertain",
            "selected evidence has an unsupported harness identity",
        )
    record_anchor = frozen["anchor"]
    native = next(
        (
            item
            for item in native_records
            if item.anchor.source_id == anchor.get("source_id")
            and item.anchor.record_index == anchor.get("record_index")
            and item.anchor.record_digest == anchor.get("record_digest")
        ),
        None,
    )
    if native is None:
        raise CaptureError(
            "diagnose_snapshot_invalid",
            "frozen record anchor does not identify a native event",
        )
    fields = (
        "kind",
        "tool_use_id",
        "tool_name",
        "tool_input_excerpt",
        "tool_output_excerpt",
        "tool_output_length_bytes",
        "tool_status",
        "tool_error",
        "failure_reason",
    )
    native_value = asdict(native)
    projection_mismatch = (
        any(
            _projection_value(native_value.get(name))
            != _projection_value(frozen.get(name))
            for name in fields
            if name != "tool_output_length_bytes"
        )
        or (
            frozen.get("tool_output_length_bytes") is not None
            and native_value.get("tool_output_length_bytes")
            != frozen.get("tool_output_length_bytes")
        )
        or not _tool_observations_match(
            frozen.get("tool_observations", []),
            native_value.get("tool_observations", []),
        )
    )
    if projection_mismatch or native.anchor.native_id != record_anchor.get("native_id"):
        raise CaptureError(
            "diagnose_snapshot_invalid",
            "frozen tool evidence does not match the revalidated native record",
        )


def _tool_observations_match(frozen: Any, native: Any) -> bool:
    if not isinstance(frozen, list) or not isinstance(native, list):
        return frozen is None and native == [] or frozen == native
    if len(frozen) != len(native):
        return False
    for frozen_observation, native_observation in zip(frozen, native, strict=True):
        if not isinstance(frozen_observation, dict) or not isinstance(
            native_observation, dict
        ):
            if frozen_observation != native_observation:
                return False
            continue
        frozen_length = frozen_observation.get("output_length_bytes")
        native_length = native_observation.get("output_length_bytes")
        if frozen_length is not None and frozen_length != native_length:
            return False
        frozen_fields = {
            key: value
            for key, value in frozen_observation.items()
            if key != "output_length_bytes"
        }
        native_fields = {
            key: value
            for key, value in native_observation.items()
            if key != "output_length_bytes"
        }
        if _projection_value(frozen_fields) != _projection_value(native_fields):
            return False
    return True


def _projection_value(value: Any) -> Any:
    """Normalize one projection field; `_plain` omits an empty tool observation list."""
    normalized = _without_none(value)
    return None if normalized == [] else normalized


def _without_none(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_none(item)
            for key, item in value.items()
            if item is not None and item != []
        }
    if isinstance(value, list):
        return [_without_none(item) for item in value]
    return value


def _opencode_session_directory(path: str, session_id: Any) -> str | None:
    if not isinstance(session_id, str) or not session_id:
        return None
    import sqlite3

    try:
        connection = sqlite3.connect(
            f"file:{Path(path)}?mode=ro", uri=True, timeout=0.25
        )
        try:
            row = connection.execute(
                "SELECT directory FROM session_v2 WHERE id=?", (session_id,)
            ).fetchone()
            return (
                row[0] if row and isinstance(row[0], str) and row[0].strip() else None
            )
        finally:
            connection.close()
    except sqlite3.Error:
        return None


def _revalidate_record_anchor(source: dict[str, Any], anchor: dict[str, Any]) -> None:
    path = Path(source.get("canonical_path", ""))
    try:
        info = path.lstat()
        if path.is_symlink() or not path.is_file():
            _raise(OSError("source is not a regular file"))
        if (
            source.get("device") is not None
            and info.st_dev != source.get("device")
            or source.get("inode") is not None
            and info.st_ino != source.get("inode")
        ):
            _raise(OSError("source identity changed"))
        captured_length = source.get("captured_length", source.get("initial_length"))
        if (
            not isinstance(captured_length, int)
            or captured_length < 0
            or info.st_size < captured_length
        ):
            _raise(OSError("source prefix is shorter than the captured snapshot"))
        with path.open("rb") as stream:
            prefix = stream.read(captured_length)
            start, end = anchor.get("byte_start"), anchor.get("byte_end")
            if source.get("format") == "opencode-sqlite-2.0.12":
                raw_record = None
            else:
                if (
                    not isinstance(start, int)
                    or not isinstance(end, int)
                    or start < 0
                    or end <= start
                    or end > len(prefix)
                ):
                    _raise(
                        OSError("record anchor is outside the captured source prefix")
                    )
                raw_record = prefix[start:end]
        if source.get("format") == "opencode-sqlite-2.0.12":
            _revalidate_companions(source.get("companions", []))
    except OSError as error:
        raise CaptureError(
            "diagnose_source_changed", f"cannot revalidate captured source: {error}"
        ) from error
    if "sha256:" + hashlib.sha256(prefix).hexdigest() != source.get("prefix_digest"):
        raise CaptureError(
            "diagnose_source_changed", "source prefix changed after inspection"
        )
    if raw_record is not None and "sha256:" + hashlib.sha256(
        raw_record
    ).hexdigest() != anchor.get("record_digest"):
        raise CaptureError(
            "diagnose_anchor_invalid",
            "record anchor no longer matches the native source bytes",
        )


def _revalidate_companions(companions: list[dict[str, Any]]) -> None:
    for companion in companions:
        path = Path(companion.get("path", ""))
        try:
            info = path.lstat()
        except FileNotFoundError:
            if companion.get("present"):
                raise CaptureError(
                    "diagnose_source_changed",
                    "OpenCode database companion disappeared after inspection",
                ) from None
            continue
        except OSError as error:
            raise CaptureError(
                "diagnose_source_changed",
                f"cannot revalidate OpenCode database companion: {error}",
            ) from error
        if path.is_symlink() or not path.is_file() or not companion.get("present"):
            raise CaptureError(
                "diagnose_source_changed",
                "OpenCode database companion changed after inspection",
            )
        data = path.read_bytes()
        identity = (
            info.st_dev,
            info.st_ino,
            len(data),
            info.st_mtime_ns,
            "sha256:" + hashlib.sha256(data).hexdigest(),
        )
        expected = (
            companion.get("device"),
            companion.get("inode"),
            companion.get("length"),
            companion.get("modified_ns"),
            companion.get("digest"),
        )
        if identity != expected:
            raise CaptureError(
                "diagnose_source_changed",
                "OpenCode database companion changed after inspection",
            )


def _item_from_flags(flags: CaptureFlags) -> dict[str, Any]:
    if flags.item_id is not None and all(
        value is None
        for value in (flags.item_source, flags.item_title, flags.item_target)
    ):
        item = {"mode": "existing", "id": flags.item_id}
        _validate_item(item)
        return item
    if (
        flags.item_id is None
        and flags.item_source is not None
        and flags.item_title is not None
    ):
        item = {"mode": "new", "source": flags.item_source, "title": flags.item_title}
        if flags.item_target is not None:
            item["target"] = flags.item_target
        _validate_item(item)
        return item
    raise CaptureError(
        "diagnose_capture_invalid", "pass --item-id, or --item-source with --item-title"
    )


def _validate_kind(value: Any) -> None:
    if not isinstance(value, str) or value not in {
        "failed-tool",
        "repeated-work",
        "workflow-deviation",
    }:
        raise CaptureError(
            "diagnose_capture_invalid", f"unknown incident kind `{value}`"
        )


def _validate_item(value: Any) -> None:
    if not isinstance(value, dict) or value.get("mode") not in {"existing", "new"}:
        raise CaptureError(
            "diagnose_capture_invalid",
            "invalid strict capture request JSON: invalid item mode",
        )
    if value["mode"] == "existing":
        if set(value) != {"mode", "id"} or type(value.get("id")) is not int:
            raise CaptureError(
                "diagnose_capture_invalid",
                "invalid strict capture request JSON: invalid existing item",
            )
        return
    if not {"mode", "source", "title"} <= set(value) or set(value) - {
        "mode",
        "source",
        "title",
        "target",
    }:
        raise CaptureError(
            "diagnose_capture_invalid",
            "invalid strict capture request JSON: invalid new item",
        )


def _validate_anchor(value: Any) -> None:
    required = {
        "source_id",
        "record_index",
        "byte_start",
        "byte_end",
        "record_digest",
        "native_id",
    }
    optional = {"session_id", "storage_sequence", "context_digest"}
    if (
        not isinstance(value, dict)
        or not required <= set(value)
        or set(value) - required - optional
    ):
        raise CaptureError(
            "diagnose_capture_invalid",
            "invalid strict capture request JSON: invalid record anchor",
        )
    if (
        not isinstance(value["source_id"], str)
        or type(value["record_index"]) is not int
        or type(value["byte_start"]) is not int
        or type(value["byte_end"]) is not int
    ):
        raise CaptureError(
            "diagnose_capture_invalid",
            "invalid strict capture request JSON: invalid record anchor",
        )


def _rust_json_error(raw: bytes, error: Exception) -> str:
    if raw.strip() == b"{":
        return "EOF while parsing an object at line 1 column 1"
    if raw.strip() == b"[":
        return "EOF while parsing a list at line 1 column 1"
    return str(error)
