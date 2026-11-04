"""TOML formatting helpers used by knowledge."""

from __future__ import annotations

import re
from typing import Any

from varde_core.yamlio import YamlSyntaxError, dump_yaml, load_yaml

__all__ = ["YamlSyntaxError", "dump_yaml", "edit_toml", "load_yaml"]


def edit_toml(existing: str, fresh: str) -> str:
    """Update TOML values while retaining comments and unchanged formatting."""
    import tomlkit

    try:
        old = tomlkit.parse(existing)
        new = tomlkit.parse(fresh)
    except tomlkit.exceptions.ParseError, TypeError:  # pyright: ignore[reportAttributeAccessIssue]  # tomlkit exports exceptions dynamically at runtime.
        return fresh
    old_keys = set(old)
    new_keys = set(new)
    removed_decor = _default_removed_decor(existing, old, new)
    _merge_tables(old, new, keep_empty=False)
    rendered = tomlkit.dumps(old)
    rendered = _remove_lines(rendered, removed_decor)
    if "project" in new_keys and "project" not in old_keys:
        if _table_position(fresh, "project") < _table_position(fresh, "hooks"):
            rendered = _move_project_before_hooks(rendered)
        rendered = re.sub(r"\n{2,}(?=\[)", "\n", rendered)
    return rendered.rstrip("\n") + "\n" if rendered else rendered


def _table_comments(text: str, name: str) -> list[str]:
    lines = text.splitlines(keepends=True)
    start = next(
        (index for index, line in enumerate(lines) if line.strip() == f"[{name}]"), None
    )
    if start is None:
        return []
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].lstrip().startswith("[")
        ),
        len(lines),
    )
    return [line for line in lines[start + 1 : end] if line.lstrip().startswith("#")]


def _default_removed_decor(existing: str, old: Any, new: Any) -> list[str]:
    previous = old.get("default")
    current = new.get("default")
    if previous is None:
        return []
    if current is None:
        return _leading_table_comments(existing, "default") + _table_comments(
            existing, "default"
        )

    removed = set(previous) - set(current)
    if not removed:
        return []
    lines = existing.splitlines(keepends=True)
    start = next(
        (index for index, line in enumerate(lines) if line.strip() == "[default]"), None
    )
    if start is None:
        return []
    end = next(
        (
            index
            for index in range(start + 1, len(lines))
            if lines[index].lstrip().startswith("[")
        ),
        len(lines),
    )
    pending: list[str] = []
    decor: list[str] = []
    for line in lines[start + 1 : end]:
        if line.lstrip().startswith("#"):
            pending.append(line)
            continue
        key = line.partition("=")[0].strip()
        if "=" in line:
            if key in removed:
                decor.extend(pending)
            pending = []
        elif line.strip():
            pending = []
    return decor


def _leading_table_comments(text: str, name: str) -> list[str]:
    lines = text.splitlines(keepends=True)
    start = next(
        (index for index, line in enumerate(lines) if line.strip() == f"[{name}]"), None
    )
    if start is None:
        return []
    comments: list[str] = []
    for line in reversed(lines[:start]):
        if line.lstrip().startswith("#"):
            comments.append(line)
            continue
        if not line.strip():
            break
        break
    return list(reversed(comments))


def _remove_lines(text: str, lines_to_remove: list[str]) -> str:
    remaining = list(lines_to_remove)
    result: list[str] = []
    for line in text.splitlines(keepends=True):
        if line in remaining:
            remaining.remove(line)
            continue
        result.append(line)
    return "".join(result)


def _move_project_before_hooks(text: str) -> str:
    lines = text.splitlines(keepends=True)
    starts = [
        index for index, line in enumerate(lines) if line.lstrip().startswith("[")
    ]
    if not starts:
        return text
    blocks = [
        lines[start : starts[i + 1] if i + 1 < len(starts) else len(lines)]
        for i, start in enumerate(starts)
    ]
    project = next(
        (
            index
            for index, block in enumerate(blocks)
            if block[0].lstrip().startswith("[project.")
        ),
        None,
    )
    hooks = next(
        (
            index
            for index, block in enumerate(blocks)
            if block[0].lstrip().startswith("[hooks")
        ),
        None,
    )
    if project is None or hooks is None or project < hooks:
        return text
    block = blocks.pop(project)
    blocks.insert(hooks, block)
    prefix = lines[: starts[0]]
    return "".join(prefix + [line for table in blocks for line in table])


def _table_position(text: str, name: str) -> int:
    for index, line in enumerate(text.splitlines()):
        if line.strip() == f"[{name}]" or line.strip().startswith(f"[{name}."):
            return index
    return len(text.splitlines())


def _merge_tables(old: Any, new: Any, *, keep_empty: bool) -> None:
    for key in list(old):
        if key not in new and not (
            (keep_empty or key == "hooks") and _is_empty_tables(old[key])
        ):
            del old[key]

    for key, new_item in new.items():
        if key not in old:
            old.add(key, new_item) if key == "project" else old.__setitem__(
                key, new_item
            )
            continue
        old_item = old[key]
        import tomlkit

        if isinstance(old_item, tomlkit.items.Table) and isinstance(  # pyright: ignore[reportAttributeAccessIssue]  # tomlkit exposes items through a runtime module attribute.
            new_item,
            tomlkit.items.Table,  # pyright: ignore[reportAttributeAccessIssue]  # tomlkit exposes items through a runtime module attribute.
        ):
            _merge_tables(old_item, new_item, keep_empty=keep_empty or key == "hooks")
        elif _item_text(old_item) != _item_text(new_item):
            old_trivia = getattr(old_item, "trivia", None)
            replacement = new_item
            new_trivia = getattr(replacement, "trivia", None)
            if old_trivia is not None and new_trivia is not None:
                new_trivia.indent = old_trivia.indent
                new_trivia.comment_ws = old_trivia.comment_ws
                new_trivia.comment = old_trivia.comment
                new_trivia.trail = old_trivia.trail
            old[key] = replacement


def _is_empty_tables(item: Any) -> bool:
    import tomlkit

    return isinstance(item, tomlkit.items.Table) and all(  # pyright: ignore[reportAttributeAccessIssue]  # tomlkit exposes items through a runtime module attribute.
        _is_empty_tables(child) for child in item.values()
    )


def _item_text(item: Any) -> str:
    return str(item)
