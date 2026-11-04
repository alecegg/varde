"""Preserve user-selected agent model settings across agent updates."""

from __future__ import annotations

from dataclasses import dataclass

from varde.setup.sync.harness import HarnessId


@dataclass(frozen=True)
class _FoundKey:
    index: int
    raw_value: str


@dataclass(frozen=True)
class _Change:
    key_index: int
    replacement: str | None


def _kind(harness: HarnessId) -> str:
    return "toml" if harness == HarnessId.CODEX else "markdown"


def _keys(kind: str) -> tuple[str, ...]:
    return ("model", "model_reasoning_effort") if kind == "toml" else ("model",)


def _lines(text: str) -> list[str]:
    return text.replace("\r\n", "\n").replace("\r", "\n").splitlines(keepends=True)


def _without_newline(line: str) -> str:
    return line.rstrip("\n")


def _header_indexes(lines: list[str], kind: str) -> list[int]:
    if kind == "markdown":
        if not lines or _without_newline(lines[0]) != "---":
            return []
        indexes = []
        for index, line in enumerate(lines[1:], 1):
            if _without_newline(line) == "---":
                break
            indexes.append(index)
        return indexes
    indexes = []
    for index, line in enumerate(lines):
        if line.startswith(("developer_instructions", "[")):
            break
        indexes.append(index)
    return indexes


def _value_for_key(line: str, key: str, kind: str) -> str | None:
    line = _without_newline(line)
    if kind == "markdown":
        if not line.startswith(key) or not line[len(key) :].startswith(":"):
            return None
        remainder = line[len(key) + 1 :]
    else:
        if not line.startswith(key):
            return None
        remainder = line[len(key) :].lstrip()
        if not remainder.startswith("="):
            return None
        remainder = remainder[1:]
    return remainder.strip()


def _find_keys(lines: list[str], kind: str) -> list[_FoundKey | None]:
    found: list[_FoundKey | None] = [None] * len(_keys(kind))
    for index in _header_indexes(lines, kind):
        for key_index, key in enumerate(_keys(kind)):
            if found[key_index] is None:
                value = _value_for_key(lines[index], key, kind)
                if value is not None:
                    found[key_index] = _FoundKey(index, value)
    return found


def _record_value(line: str, kind: str) -> str | None:
    line = _without_newline(line)
    if kind == "markdown":
        return (
            line.removeprefix("<!-- varde-default: ").removesuffix(" -->")
            if line.startswith("<!-- varde-default: ") and line.endswith(" -->")
            else None
        )
    return (
        line.removeprefix("# varde-default: ")
        if line.startswith("# varde-default: ")
        else None
    )


def _unquote(raw: str) -> str:
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] in "\"'" and raw[-1] == raw[0]:
        return raw[1:-1]
    return raw


def _recorded_defaults(lines: list[str], kind: str) -> list[str | None]:
    records: list[str | None] = [None] * len(_keys(kind))
    for line in lines:
        record = _record_value(line, kind)
        if record is None:
            continue
        for index, key in enumerate(_keys(kind)):
            value = _value_for_key(record, key, kind)
            if value is not None:
                records[index] = _unquote(value)
    return records


def _history(harness: HarnessId, agent: str, key: str) -> tuple[str, ...]:
    values = {
        (HarnessId.CLAUDE, "varde-reviewer", "model"): ("haiku",),
        (HarnessId.CLAUDE, "varde-explorer", "model"): ("sonnet",),
        (HarnessId.CODEX, "varde-explorer", "model"): ("gpt-5.6-luna",),
        (HarnessId.CODEX, "varde-builder", "model"): ("gpt-5.6-luna",),
        (HarnessId.CODEX, "varde-planner", "model"): ("gpt-5.6-terra",),
        (HarnessId.CODEX, "varde-reviewer", "model"): ("gpt-5.6-sol",),
        (HarnessId.PI, "varde-builder", "model"): ("deepseek/deepseek-v4-flash",),
        (HarnessId.PI, "varde-explorer", "model"): ("deepseek/deepseek-v4-flash",),
        (HarnessId.PI, "varde-planner", "model"): ("deepseek/deepseek-v4-flash",),
        (HarnessId.PI, "varde-reviewer", "model"): ("deepseek/deepseek-v4-flash",),
    }
    return values.get((harness, agent, key), ())


def _is_default(
    index: int,
    value: str,
    shipped: str | None,
    records: list[str | None],
    harness: HarnessId,
    agent: str,
    key: str,
) -> bool:
    if records[index] is not None:
        return value == records[index]
    return value == shipped or value in _history(harness, agent, key)


def _plan(
    harness: HarnessId, agent: str, kind: str, staged: list[str], installed: list[str]
) -> tuple[list[_Change], list[_FoundKey | None]]:
    names = _keys(kind)
    shipped = _find_keys(staged, kind)
    present = _find_keys(installed, kind)
    records = _recorded_defaults(installed, kind)
    changes = []
    for index, key in enumerate(names):
        if shipped[index] is not None:
            if present[index] is not None:
                present_key = present[index]
                shipped_key = shipped[index]
                assert present_key is not None and shipped_key is not None  # noqa: S101 - The enclosing checks narrow both keys.
                current = _unquote(present_key.raw_value)
                default = _unquote(shipped_key.raw_value)
                if not _is_default(
                    index, current, default, records, harness, agent, key
                ):
                    changes.append(_Change(index, installed[present_key.index]))
            elif records[index] is not None:
                changes.append(_Change(index, None))
        elif kind == "markdown" and present[index] is not None:
            present_key = present[index]
            assert present_key is not None  # noqa: S101 - The enclosing condition narrows this key.
            current = _unquote(present_key.raw_value)
            if (
                records[index] is not None or _history(harness, agent, key)
            ) and not _is_default(index, current, None, records, harness, agent, key):
                changes.append(_Change(index, installed[present_key.index]))
    return changes, shipped


def _insert_at(lines: list[str]) -> int:
    header = _header_indexes(lines, "markdown")
    for index in header:
        if lines[index].startswith("description:"):
            return index + 1
    return header[-1] + 1 if header else len(lines)


def _rewrite(
    kind: str,
    staged: list[str],
    changes: list[_Change],
    shipped: list[_FoundKey | None],
) -> str:
    output = staged.copy()
    deleted = []
    insertions = []
    for change in changes:
        key = shipped[change.key_index]
        if key is not None:
            if change.replacement is None:
                deleted.append(key.index)
            else:
                output[key.index] = change.replacement
        elif change.replacement is not None:
            insertions.append(change.replacement)
    if deleted:
        output = [line for index, line in enumerate(output) if index not in deleted]
    for insertion in insertions:
        output.insert(
            _insert_at(output),
            insertion if insertion.endswith("\n") else insertion + "\n",
        )
    if output and not output[-1].endswith("\n"):
        output[-1] += "\n"
    for index, _ in enumerate(_keys(kind)):
        key = shipped[index]
        if key is not None:
            original = _without_newline(staged[key.index])
            output.append(
                f"<!-- varde-default: {original} -->\n"
                if kind == "markdown"
                else f"# varde-default: {original}\n"
            )
    return "".join(output)


def _preserved_keys(changes: list[_Change], kind: str) -> list[str]:
    return [_keys(kind)[change.key_index] for change in changes]


def preserve_models(
    harness: HarnessId, agent: str, staged: str, installed: str | None
) -> tuple[str, list[str]]:
    kind = _kind(harness)
    staged_lines = _lines(staged)
    if installed is None:
        changes, shipped = [], _find_keys(staged_lines, kind)
    else:
        changes, shipped = _plan(harness, agent, kind, staged_lines, _lines(installed))
    return _rewrite(kind, staged_lines, changes, shipped), _preserved_keys(
        changes, kind
    )


def dry_run(
    harness: HarnessId, agent: str, staged: str, installed: str | None
) -> list[str]:
    if installed is None:
        return []
    kind = _kind(harness)
    changes, _ = _plan(harness, agent, kind, _lines(staged), _lines(installed))
    return _preserved_keys(changes, kind)
