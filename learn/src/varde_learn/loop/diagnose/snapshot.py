"""Frozen inspection snapshots and verified cutoff handling."""

from __future__ import annotations

import json
import re
from datetime import UTC
from pathlib import Path
from typing import Any, Never

from .model import SNAPSHOT_SCHEMA_VERSION

_RFC3339_NANOS = re.compile(r"^(.*?)(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})$")


def _raise(error: Exception) -> Never:
    raise error


def snapshot_document(value: dict[str, Any]) -> dict[str, Any]:
    snapshot = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "digest": "",
        "session": value["session"],
        "children": value["children"],
        "sources": value["sources"],
        "records": value["records"],
        "overlap": value["overlap"],
        "coverage": value["coverage"],
        "redacted": 0,
    }
    encoded = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode()
    snapshot["digest"] = "sha256:" + __import__("hashlib").sha256(encoded).hexdigest()
    return snapshot


def write_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    from .capture import CaptureError
    from .model import MAX_SNAPSHOT_BYTES

    try:
        if path.is_symlink() or (path.exists() and not path.is_file()):
            _raise(OSError("snapshot destination must be a regular file"))
        raw = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode()
        if len(raw) > MAX_SNAPSHOT_BYTES:
            raise CaptureError(
                "diagnose_snapshot_limit",
                "normalized snapshot exceeds the supported byte limit",
            )
        path.write_bytes(raw)
    except OSError as error:
        raise CaptureError(
            "diagnose_snapshot_invalid", f"cannot write snapshot: {error}"
        ) from error


def apply_cutoff(snapshot: dict[str, Any], path: Path) -> None:
    from .capture import CaptureError, _revalidate_record_anchor

    try:
        raw = path.read_bytes()
        if len(raw) > 64 * 1024:
            _raise(ValueError("cutoff anchor exceeds 64 KiB"))
        cutoff = json.loads(raw)
        if not isinstance(cutoff, dict) or set(cutoff) != {
            "source_path",
            "record_anchor",
        }:
            _raise(ValueError("invalid cutoff anchor JSON"))
        source_path = Path(cutoff["source_path"]).resolve(strict=True)
    except (
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        TypeError,
    ) as error:
        raise CaptureError(
            "diagnose_cutoff_invalid", f"invalid cutoff anchor: {error}"
        ) from error
    anchor = cutoff["record_anchor"]
    sources = snapshot["sources"]
    source = next(
        (item for item in sources if item["source_id"] == str(source_path)), None
    )
    if source is None:
        raise CaptureError(
            "diagnose_cutoff_invalid", "cutoff anchor belongs to a different source"
        )
    records = snapshot["records"]
    selected = next((item for item in records if item["anchor"] == anchor), None)
    if selected is None:
        raise CaptureError(
            "diagnose_cutoff_invalid", "cutoff record is not in the inspected evidence"
        )
    try:
        _revalidate_record_anchor(source, anchor)
    except CaptureError as error:
        raise CaptureError(
            "diagnose_cutoff_invalid",
            "cutoff source changed after the anchor was inspected",
        ) from error
    instant = _timestamp_nanoseconds(selected.get("timestamp"))
    session_id = snapshot["session"]["thread_id"]
    source_id = source["source_id"]
    cutoff_sequence = (
        anchor.get("storage_sequence")
        if source.get("format") == "opencode-sqlite-2.0.12"
        else None
    )
    eligible_children = set()
    kept_children = []
    unknown_child_time = False
    for child in snapshot["children"]:
        try:
            started = _timestamp_nanoseconds(child["started_at"])
            if started is None:
                unknown_child_time = True
                continue
        except AttributeError, KeyError, ValueError:
            unknown_child_time = True
            continue
        if instant is not None and started <= instant:
            kept_children.append(child)
            eligible_children.add(child["thread_id"])
    kept_records = []
    for record in records:
        if record["session_thread_id"] == session_id:
            record_anchor = record["anchor"]
            before = (
                (record_anchor.get("storage_sequence", -1) <= cutoff_sequence)
                if cutoff_sequence is not None
                else (
                    record_anchor["source_id"] == source_id
                    and record_anchor["record_index"] <= anchor["record_index"]
                )
            )
            if before:
                kept_records.append(record)
        elif record["session_thread_id"] in eligible_children:
            try:
                happened = _timestamp_nanoseconds(record["timestamp"])
                if happened is None:
                    unknown_child_time = True
                    continue
            except AttributeError, TypeError, ValueError:
                unknown_child_time = True
                continue
            if instant is not None and happened <= instant:
                kept_records.append(record)
    removed = len(records) - len(kept_records)
    snapshot["children"] = kept_children
    retained_sources = {source_id, *(child["source_id"] for child in kept_children)}
    snapshot["sources"] = [
        item for item in sources if item["source_id"] in retained_sources
    ]
    snapshot["records"] = kept_records
    coverage = snapshot["coverage"]
    coverage["omitted_records"] += removed
    coverage["record_count"] = len(kept_records)
    coverage["cutoff_verified"] = True
    coverage["cutoff_anchor"] = anchor
    if removed:
        coverage["warnings"].append(
            "records after the verified cutoff were excluded from the frozen evidence"
        )
    if unknown_child_time:
        coverage["source_complete"] = coverage["complete"] = coverage[
            "analysis_ready"
        ] = False
        coverage["warnings"].append(
            "some linked-child records could not be placed before the cutoff because "
            "their event time was unknown"
        )
    elif coverage["source_complete"]:
        coverage["complete"] = coverage["analysis_ready"] = True
    coverage["warnings"] = [
        warning
        for warning in coverage["warnings"]
        if "no verified pre-orchestration cutoff" not in warning
    ]
    snapshot["snapshot"]["digest"] = snapshot_document(snapshot)["digest"]


def _timestamp_nanoseconds(value: object) -> int | None:
    from datetime import datetime

    if not isinstance(value, str):
        return None
    match = _RFC3339_NANOS.fullmatch(value)
    if match is None:
        return None
    whole, fraction, zone = match.groups()
    if fraction is not None and len(fraction) > 9:
        return None
    try:
        parsed = datetime.fromisoformat(whole + zone.replace("Z", "+00:00"))
    except ValueError:
        return None
    utc = parsed.astimezone(UTC)
    seconds = int(utc.timestamp())
    nanoseconds = int((fraction or "")[:9].ljust(9, "0"))
    return seconds * 1_000_000_000 + nanoseconds
