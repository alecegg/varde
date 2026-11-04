"""Order-preserving edits to one event array in a hook configuration."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from varde_core.jsonio import dumps as _json_dumps


@dataclass
class _Node:
    value: Any
    start: int
    end: int


def _decode(text: str, pos: int = 0) -> tuple[_Node, int]:
    decoder = json.JSONDecoder()
    while pos < len(text) and text[pos].isspace():
        pos += 1
    start = pos
    if text[pos] == "{" or text[pos] == "[":
        opening = text[pos]
        closing = "}" if opening == "{" else "]"
        pos += 1
        result: dict[str, _Node] | list[_Node] = {} if opening == "{" else []
        while True:
            while text[pos].isspace() or text[pos] == ",":
                pos += 1
            if text[pos] == closing:
                pos += 1
                break
            if opening == "{":
                key, pos = decoder.raw_decode(text, pos)
                pos += 1
                while text[pos].isspace() or text[pos] == ":":
                    pos += 1
                child, pos = _decode(text, pos)
                assert isinstance(result, dict)  # noqa: S101 - Narrows the container selected by the opening token.
                result[key] = child
            else:
                child, pos = _decode(text, pos)
                assert isinstance(result, list)  # noqa: S101 - Narrows the container selected by the opening token.
                result.append(child)
        return _Node(result, start, pos), pos
    value, pos = decoder.raw_decode(text, pos)
    return _Node(value, start, pos), pos


def _dump(value: Any, indent: int = 2, level: int = 0) -> str:
    if isinstance(value, dict):
        if not value:
            return "{}"
        pad, child_pad = " " * (indent * level), " " * (indent * (level + 1))
        parts = [
            f"{child_pad}{json.dumps(k, ensure_ascii=False)}: "
            f"{_dump(v, indent, level + 1)}"
            for k, v in value.items()
        ]
        return "{\n" + ",\n".join(parts) + f"\n{pad}}}"
    if isinstance(value, list):
        if not value:
            return "[]"
        pad, child_pad = " " * (indent * level), " " * (indent * (level + 1))
        return (
            "[\n"
            + ",\n".join(f"{child_pad}{_dump(v, indent, level + 1)}" for v in value)
            + f"\n{pad}]"
        )
    if isinstance(value, float):
        return _json_dumps(value)
    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))


def _plain(value: Any) -> Any:
    if isinstance(value, _Node):
        return _plain(value.value)
    if isinstance(value, dict):
        return {key: _plain(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_plain(child) for child in value]
    return value


def _render(
    document: str, root: _Node, hooks: dict[str, list[str]], *, prune: bool
) -> str:
    fields: dict[str, str] = {}
    for key, node in root.value.items():
        if key == "hooks":
            hooks_node = node
            hooks_fields: dict[str, str] = {}
            for name, event_node in hooks_node.value.items():
                if name == _edited_event and name in hooks:
                    hooks_fields[name] = _event_text(hooks[name], 2)
                elif name != _edited_event:
                    hooks_fields[name] = document[event_node.start : event_node.end]
            for name, entries in hooks.items():
                if name not in hooks_fields:
                    hooks_fields[name] = _event_text(entries, 2)
            if not (prune and not hooks_fields):
                fields[key] = _dump_raw_object(hooks_fields, 1)
        else:
            fields[key] = document[node.start : node.end]
    if "hooks" not in fields and hooks:
        fields["hooks"] = _dump_raw_object(
            {k: _event_text(v, 2) for k, v in hooks.items()}, 1
        )
    return _dump_raw_object(fields, 0) + "\n"


def _dump_raw_object(fields: dict[str, str], level: int) -> str:
    if not fields:
        return "{}"
    pad, child = " " * (2 * level), " " * (2 * (level + 1))
    return (
        "{\n"
        + ",\n".join(
            f"{child}{json.dumps(k, ensure_ascii=False)}: {v}"
            for k, v in fields.items()
        )
        + f"\n{pad}}}"
    )


def _event_text(raw: list[str], level: int = 0) -> str:
    if not raw:
        return "[]"
    pad, child = " " * (2 * level), " " * (2 * (level + 1))
    return "[\n" + ",\n".join(child + item for item in raw) + "\n" + pad + "]"


def _command(value: Any) -> str | None:
    return (
        value.get("command")
        if isinstance(value, dict) and isinstance(value.get("command"), str)
        else None
    )


def _remove(
    value: Any, predicate: Callable[[str], bool], removed: list[str]
) -> tuple[Any, bool, bool]:
    command = _command(value)
    if command is not None and predicate(command):
        removed.append(command)
        return value, True, True
    if not isinstance(value, dict) or not isinstance(value.get("hooks"), list):
        return value, False, False
    kept = []
    changed = False
    for child in value["hooks"]:
        cmd = _command(child)
        if cmd is not None and predicate(cmd):
            removed.append(cmd)
            changed = True
        else:
            kept.append(child)
    if not changed:
        return value, False, False
    updated = dict(value)
    if kept:
        updated["hooks"] = kept
    else:
        return value, True, True
    return updated, True, False


@dataclass
class RemoveOptions:
    prune_empty_hooks: bool = False


def append_entry(document: str, event: str, entry: object) -> str:
    return _edit(
        document, event, lambda entries: entries + [_dump(entry, level=3)], create=True
    )


def remove_matching_commands(
    document: str, event: str, predicate: Callable[[str], bool]
) -> tuple[str, list[str]]:
    return remove_matching_commands_with_options(document, event, predicate)


def remove_matching_commands_with_options(
    document: str,
    event: str,
    predicate: Callable[[str], bool],
    options: RemoveOptions | None = None,
) -> tuple[str, list[str]]:
    options = options or RemoveOptions()
    removed: list[str] = []

    def edit(entries: list[str]) -> tuple[list[str], list[str]]:
        kept = []
        for raw in entries:
            node, _ = _decode(raw)
            result, changed, drop = _remove(_plain(node.value), predicate, removed)
            kept.append(
                _dump(result, level=3) if changed and not drop else raw
            ) if not drop else None
        return kept, removed

    return _edit(document, event, edit, prune=options.prune_empty_hooks, pair=True)


def replace_owned_entries(
    document: str,
    event: str,
    predicate: Callable[[str], bool],
    replacements: list[object],
) -> tuple[str, list[str]]:
    return _replace(
        document, event, predicate, [_dump(item, level=3) for item in replacements]
    )


def replace_owned_entries_from_json(
    document: str,
    event: str,
    predicate: Callable[[str], bool],
    replacements_json: str,
    replacements_event: str,
) -> tuple[str, list[str]]:
    _validate_json(replacements_json)
    root, _ = _decode(replacements_json)
    if not isinstance(root.value, dict):
        raise ValueError("replacement configuration must be a JSON object")
    hooks = root.value.get("hooks")
    if hooks is not None and not isinstance(hooks.value, dict):
        raise ValueError("hooks must be a JSON object")
    entries = hooks.value.get(replacements_event) if hooks else None
    if entries is not None and not isinstance(entries.value, list):
        raise ValueError("hook event must be a JSON array")
    replacements = (
        [_dump(_plain(node.value), level=3) for node in entries.value]
        if entries
        else []
    )
    return _replace(document, event, predicate, replacements)


def _replace(
    document: str, event: str, predicate: Callable[[str], bool], replacements: list[str]
) -> tuple[str, list[str]]:
    removed: list[str] = []

    def edit(entries: list[str]) -> tuple[list[str], list[str]]:
        kept = []
        for raw in entries:
            node, _ = _decode(raw)
            result, changed, drop = _remove(_plain(node.value), predicate, removed)
            if not drop:
                kept.append(_dump(result, level=3) if changed else raw)
        return kept + replacements, removed

    return _edit(document, event, edit, create=bool(replacements), pair=True)


def _edit(
    document: str,
    event: str,
    callback: Callable[[list[str]], Any],
    *,
    create: bool = False,
    prune: bool = False,
    pair: bool = False,
) -> Any:
    global _edited_event  # noqa: PLW0603 - updates event edit notification
    _edited_event = event
    source = document if document.strip() else "{}"
    _validate_json(source)
    root, _ = _decode(source)
    if not isinstance(root.value, dict):
        raise ValueError("hook configuration must be a JSON object")
    hooks_node = root.value.get("hooks")
    if hooks_node is not None and not isinstance(hooks_node.value, dict):
        raise ValueError("hooks must be a JSON object")
    hooks = hooks_node.value if hooks_node else {}
    event_node = hooks.get(event)
    if event_node is not None and not isinstance(event_node.value, list):
        raise ValueError("hook event must be a JSON array")
    if event_node is None and not create:
        return (document, []) if pair else document
    raw_entries = (
        [source[node.start : node.end] for node in event_node.value]
        if event_node
        else []
    )
    result = callback(raw_entries)
    entries, removed = result if pair else (result, [])
    if event_node is not None and entries == raw_entries and not removed:
        return (document, removed) if pair else document
    hooks_text = {
        key: [source[item.start : item.end] for item in value.value]
        if isinstance(value.value, list)
        else []
        for key, value in hooks.items()
    }
    hooks_text[event] = entries
    if not entries:
        hooks_text.pop(event, None)
    return (
        (_render(source, root, hooks_text, prune=prune), removed)
        if pair
        else _render(source, root, hooks_text, prune=False)
    )


def _validate_json(document: str) -> None:
    try:
        value = json.loads(
            document, parse_constant=_reject_constant, parse_float=_finite_float
        )
        _validate_unicode(value)
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ValueError(str(exc)) from exc


def _reject_constant(value: str) -> None:
    raise ValueError(f"invalid constant {value}")


def _finite_float(value: str) -> float:
    number = float(value)
    if number == float("inf") or number == float("-inf"):
        raise ValueError(f"number out of range: {value}")
    return number


def _validate_unicode(value: Any) -> None:
    if isinstance(value, str):
        value.encode("utf-8")
    elif isinstance(value, list):
        for item in value:
            _validate_unicode(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            _validate_unicode(key)
            _validate_unicode(item)
