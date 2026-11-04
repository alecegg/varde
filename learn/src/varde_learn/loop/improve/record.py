"""Loop record: a proposal for a skill or agent change, under `<memory root>/loop/`.

A proposal is data. Its change is a unified diff file `<id>.diff` beside the
record `<id>.json`; nothing in a skill or agent file changes until it is accepted.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

LOOP_DIR = "loop"
STATES = ("proposed", "rejected", "applied")
DIRECTIONS = ("add", "trim", "reset")
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class RecordError(ValueError):
    """A loop record failed validation or could not be read."""


@dataclass(frozen=True)
class LoopRecord:
    id: str
    skill: str
    direction: str
    change: str
    created: str
    state: str = "proposed"
    trigger: tuple[str, ...] = ()
    token_delta: int = 0
    decision: str = ""
    later_demand: dict[str, int] = field(default_factory=dict)
    pre_hashes: dict[str, str] = field(default_factory=dict)

    @property
    def diff_path(self) -> str:
        return f"{self.id}.diff"


_REQUIRED = ("id", "skill", "direction", "change", "created", "state")


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def validate(record: LoopRecord) -> LoopRecord:
    for name in _REQUIRED:
        if not getattr(record, name):
            raise RecordError(f"missing field: {name}")
    if not _ID.match(record.id):
        raise RecordError(f"invalid id: {record.id}")
    if record.state not in STATES:
        raise RecordError(f"invalid state: {record.state}")
    if record.direction not in DIRECTIONS:
        raise RecordError(f"invalid direction: {record.direction}")
    if not isinstance(record.token_delta, int):
        raise RecordError("token_delta must be an integer")
    return record


def to_json(record: LoopRecord) -> str:
    data = asdict(validate(record))
    data["trigger"] = list(record.trigger)
    data["diff_path"] = record.diff_path
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def from_json(text: str) -> LoopRecord:
    try:
        data: Any = json.loads(text)
    except json.JSONDecodeError as error:
        raise RecordError(f"invalid JSON: {error}") from error
    if not isinstance(data, dict):
        raise RecordError("record must be a JSON object")
    data.pop("diff_path", None)
    missing = [name for name in _REQUIRED if not data.get(name)]
    if missing:
        raise RecordError(f"missing field: {missing[0]}")
    known = LoopRecord.__dataclass_fields__
    unknown = sorted(set(data) - set(known))
    if unknown:
        raise RecordError(f"unknown field: {unknown[0]}")
    data["trigger"] = tuple(data.get("trigger", ()))
    return validate(LoopRecord(**data))


def loop_dir(memory_root: Path) -> Path:
    return memory_root / LOOP_DIR


def read_raw(path: Path) -> str:
    """File text with line endings untouched (CRLF stays CRLF)."""
    return path.read_text(newline="")


def write_record(
    memory_root: Path, record: LoopRecord, diff: str | None = None
) -> Path:
    """Write the record (and its diff when given); return the record path."""
    text = to_json(record)
    base = loop_dir(memory_root)
    base.mkdir(parents=True, exist_ok=True)
    if diff is not None:
        (base / record.diff_path).write_text(diff, newline="")
    path = base / f"{record.id}.json"
    path.write_text(text)
    return path


def read_record(memory_root: Path, record_id: str) -> LoopRecord:
    if not _ID.match(record_id):
        raise RecordError(f"invalid id: {record_id!r}")
    path = loop_dir(memory_root) / f"{record_id}.json"
    try:
        return from_json(path.read_text())
    except OSError as error:
        raise RecordError(f"cannot read {path}: {error}") from error


def read_diff(memory_root: Path, record: LoopRecord) -> str:
    try:
        return read_raw(loop_dir(memory_root) / record.diff_path)
    except OSError:
        return ""


def scan_records(memory_root: Path) -> tuple[list[LoopRecord], list[str]]:
    """Valid records plus one message per unreadable or invalid `loop/*.json`."""
    base = loop_dir(memory_root)
    if not base.is_dir():
        return [], []
    records: list[LoopRecord] = []
    skipped: list[str] = []
    for path in sorted(base.glob("*.json")):
        try:
            records.append(read_record(memory_root, path.stem))
        except RecordError as error:
            skipped.append(f"skipped {path.name}: {error}")
    return records, skipped


def list_records(memory_root: Path) -> list[LoopRecord]:
    """Valid records only; callers that must show problems use `scan_records`."""
    return scan_records(memory_root)[0]
