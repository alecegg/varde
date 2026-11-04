"""Resolve Java imports to source files and bound names."""

from __future__ import annotations

import re
from collections.abc import Mapping
from functools import lru_cache

_IMPORT = re.compile(r"^import\s+(static\s+)?([\w.$]+)(\.\*)?\s*;$")


def import_bindings(
    spec: Mapping[str, object],
    importer_path: str,
    file_set: tuple[str, ...],
    context: Mapping[str, dict],
) -> list[dict]:
    """Map a Java import to its type, static member, or package files."""
    match = _IMPORT.fullmatch(str(spec.get("text", "")).strip())
    if not match:
        return []
    is_static, dotted_path, wildcard = match.groups()
    parts = _parts(dotted_path)
    if not parts or "/".join(parts) != spec.get("module"):
        return []
    if is_static:
        if wildcard:
            targets = _matching_file(file_set, parts)
            return [
                _binding(path, _static_names(path, context), None) for path in targets
            ]
        if len(parts) < 2:
            return []
        targets = _matching_file(file_set, parts[:-1])
        return [_binding(path, [parts[-1]], None) for path in targets]

    if wildcard:
        return [
            _binding(
                path,
                [],
                (name := path.rsplit("/", 1)[-1].removesuffix(".java")),
                owner=name,
            )
            for path in _package_files(file_set, parts)
        ]

    targets = _matching_file(file_set, parts)
    name = parts[-1]
    return [_binding(path, [name], name, owner=name) for path in targets]


def _parts(module: str) -> tuple[str, ...]:
    return tuple(part for part in module.replace(".", "/").split("/") if part)


@lru_cache(maxsize=1)
def _java_index(file_set: tuple[str, ...]):
    files = tuple(path for path in file_set if path.endswith(".java"))
    suffixes: dict[tuple[str, ...], list[str]] = {}
    packages: dict[tuple[str, ...], list[str]] = {}
    for path in files:
        parts = tuple(path.split("/"))
        for start in range(len(parts)):
            suffixes.setdefault(parts[start:], []).append(path)
        for start in range(len(parts)):
            packages.setdefault(parts[start:-1], []).append(path)
    return (
        files,
        {key: tuple(paths) for key, paths in suffixes.items()},
        {key: tuple(paths) for key, paths in packages.items()},
    )


def _matching_file(file_set: tuple[str, ...], parts: tuple[str, ...]) -> list[str]:
    if not parts:
        return []
    return list(_java_index(file_set)[1].get((*parts[:-1], parts[-1] + ".java"), ()))


def _package_files(file_set: tuple[str, ...], parts: tuple[str, ...]) -> list[str]:
    if not parts:
        return []
    return list(_java_index(file_set)[2].get(parts, ()))


def _static_names(path: str, context: Mapping[str, dict]) -> list[str]:
    return sorted(
        {
            record.get("name")
            for record in context.get(path, {}).get("functions", ())
            if record.get("name") and record.get("static") is True
        }
    )


def _binding(
    path: str,
    names: list[str] | str,
    binding: str | None,
    *,
    owner: str | None = None,
) -> dict:
    result = {"path": path, "names": names, "binding": binding}
    if owner:
        result["owner"] = owner
    return result
