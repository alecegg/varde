from __future__ import annotations

import json
import os
import subprocess
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

GUARDED_NAMES = (
    "messages.jsonl",
    "addresses",
    "bindings",
    "deliveries.jsonl",
    "events.jsonl",
)
MATCH_FIELDS = {
    "from",
    "to",
    "id",
    "name",
    "notes",
    "address",
    "session_id",
    "plan_id",
}
KNOWN_TEST_MARKERS = ("pytest-of-", "workitem-", "1d-live-")
Entry = tuple[str, str]
Snapshot = dict[str, Counter[Entry]]


def resolve_real_inbox_root(env: dict[str, str] | None = None) -> Path:
    environment = os.environ if env is None else env
    override = environment.get("VARDE_TEST_REAL_INBOX")
    if override:
        return Path(override).resolve()
    result = subprocess.run(
        ["varde", "setup", "paths", "--json"],  # noqa: S607 - Test uses the installed Varde CLI from PATH.
        cwd=Path.cwd(),
        env=dict(environment),
        capture_output=True,
        check=True,
        text=True,
    )
    working = Path(json.loads(result.stdout)["data"]["working"]).resolve()
    return working / ".cache" / "inbox"


def _row_entries(data: Any, location: str) -> Iterator[Entry]:
    if isinstance(data, list):
        for index, row in enumerate(data):
            yield from _row_entries(row, f"{location}[{index}]")
        return
    if not isinstance(data, dict):
        return

    for container_name in ("bindings", "addresses"):
        container = data.get(container_name)
        if isinstance(container, (dict, list)):
            yield from _row_entries(container, f"{location}/{container_name}")
            return

    if MATCH_FIELDS.intersection(data):
        yield location, json.dumps(data, ensure_ascii=False, sort_keys=True)
        return

    nested = False
    for name, row in data.items():
        if isinstance(row, (dict, list)):
            nested = True
            yield from _row_entries(row, f"{location}/{name}")
    if not nested:
        yield location, json.dumps(data, ensure_ascii=False, sort_keys=True)


def _file_entries(path: Path, relative: str) -> Counter[Entry]:
    entries: Counter[Entry] = Counter()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError, UnicodeError:
        return entries

    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        for index, line in enumerate(text.splitlines()):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            entries.update(_row_entries(value, f"{relative}#{index}"))
        return entries
    entries.update(_row_entries(value, relative))
    return entries


def _read_category(path: Path) -> Counter[Entry]:
    if not path.exists():
        return Counter()
    if path.is_file():
        return _file_entries(path, path.name)

    entries: Counter[Entry] = Counter()
    pending = [(child, child.name, 0) for child in path.iterdir()]
    while pending:
        child, relative, depth = pending.pop()
        location = f"{path.name}/{relative}"
        entries[(location, "{}")] += 1
        if child.is_file():
            entries.update(_file_entries(child, location))
            continue
        if child.is_dir() and depth < 2 and not child.is_symlink():
            pending.extend(
                (grandchild, f"{relative}/{grandchild.name}", depth + 1)
                for grandchild in child.iterdir()
            )
    return entries


def snapshot_inbox(root: Path) -> Snapshot:
    return {name: _read_category(root / name) for name in GUARDED_NAMES}


def _is_test_entry(location: str, serialized_row: str, run_prefix: str) -> bool:
    try:
        row = json.loads(serialized_row)
    except json.JSONDecodeError:
        row = {}
    values = [location]
    if isinstance(row, dict):
        values.extend(str(row[field]) for field in MATCH_FIELDS if field in row)
    searchable = "\n".join(values)
    return bool(run_prefix and run_prefix in searchable) or any(
        marker in searchable for marker in KNOWN_TEST_MARKERS
    )


def assert_inbox_unchanged(
    root: Path, before: Snapshot, *, run_prefix: str = ""
) -> None:
    after = snapshot_inbox(root)
    leaked: list[str] = []
    for category in GUARDED_NAMES:
        added = after[category] - before.get(category, Counter())
        for (location, row), count in added.items():
            if _is_test_entry(location, row, run_prefix):
                leaked.append(f"{category}:{location} ({count} new)")
    assert not leaked, "test-attributed real inbox entries found: " + ", ".join(leaked)
