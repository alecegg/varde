"""Resolve C# using directives to namespace or static-type files."""

from __future__ import annotations

import re
from collections.abc import Mapping
from functools import lru_cache

_USING = re.compile(
    r"^(?:global\s+)?using\s+(?:(static)\s+)?"
    r"(?:(\w+)\s*=\s*)?([\w.]+)\s*;$"
)


def import_bindings(
    spec: Mapping[str, object],
    importer_path: str,
    file_set: tuple[str, ...],
    context: Mapping[str, dict],
) -> list[dict]:
    """Map a C# using directive to its source files and imported names."""
    match = _USING.fullmatch(str(spec.get("text", "")).strip())
    if not match:
        return []
    is_static, alias, dotted_path = match.groups()
    parts = _parts(dotted_path)
    if not parts or "/".join(parts) != spec.get("module"):
        return []
    if is_static:
        if alias:
            return []
        targets = _type_files(file_set, parts, context)
        return [
            _binding(path, _static_names(path, context), None)
            for path in sorted(set(targets))
        ]

    if alias:
        type_files = _type_files(file_set, parts, context)
        targets = type_files or _directory_files(file_set, parts)
        aliases = {alias: parts[-1]} if type_files else {}
        return [
            _binding(
                path,
                [],
                alias,
                aliases,
                owner=parts[-1] if type_files else None,
            )
            for path in sorted(set(targets))
        ]

    targets = _directory_files(file_set, parts)
    return [
        _binding(
            path,
            [],
            (name := _type_name(path, context)),
            owner=name,
        )
        for path in sorted(set(targets))
        if _type_name(path, context)
    ]


def _type_name(path: str, context: Mapping[str, dict]) -> str | None:
    owners = {
        record.get("owner")
        for record in context.get(path, {}).get("functions", ())
        if record.get("owner")
    }
    if len(owners) == 1:
        return next(iter(owners))
    filename = path.rsplit("/", 1)[-1].removesuffix(".cs").split(".", 1)[0]
    return filename or None


def _static_names(path: str, context: Mapping[str, dict]) -> list[str]:
    return sorted(
        {
            record.get("name")
            for record in context.get(path, {}).get("functions", ())
            if record.get("name") and record.get("static") is True
        }
    )


def _parts(module: str) -> tuple[str, ...]:
    return tuple(part for part in module.replace(".", "/").split("/") if part)


@lru_cache(maxsize=1)
def _csharp_index(file_set: tuple[str, ...]):
    candidates = tuple(path for path in file_set if path.endswith((".cs", ".csx")))
    filenames: dict[str, list[str]] = {}
    directories: dict[tuple[str, ...], list[str]] = {}
    namespace_suffixes: dict[tuple[str, ...], list[str]] = {}
    for path in candidates:
        filename = path.rsplit("/", 1)[-1]
        filenames.setdefault(filename, []).append(path)
        parent = path.rsplit("/", 1)[0] if "/" in path else ""
        parent_parts = tuple(parent.split("/")) if parent else ()
        for start in range(len(parent_parts)):
            directories.setdefault(parent_parts[start:], []).append(path)
        namespace_parts = tuple(
            section for directory in parent_parts for section in directory.split(".")
        )
        for start in range(len(namespace_parts)):
            namespace_suffixes.setdefault(namespace_parts[start:], []).append(path)
    return (
        candidates,
        {key: tuple(paths) for key, paths in filenames.items()},
        {key: tuple(paths) for key, paths in directories.items()},
        {key: tuple(paths) for key, paths in namespace_suffixes.items()},
    )


def _directory_files(file_set: tuple[str, ...], parts: tuple[str, ...]) -> list[str]:
    if not parts:
        return []
    candidates, _, directories, namespace_suffixes = _csharp_index(file_set)
    exact = directories.get(parts, ())
    if exact:
        min_depth = min(path.rsplit("/", 1)[0].count("/") for path in exact)
        return [
            path for path in exact if path.rsplit("/", 1)[0].count("/") == min_depth
        ]
    if len(parts) < 2:
        return []
    return _best_namespace_files(candidates, parts, namespace_suffixes)


def _type_files(
    file_set: tuple[str, ...], parts: tuple[str, ...], context: Mapping[str, dict]
) -> list[str]:
    if len(parts) < 2:
        return []
    filename = f"{parts[-1]}.cs"
    namespace_parts = parts[:-1]
    candidates, filenames, _, namespace_suffixes = _csharp_index(file_set)
    exact = [
        path
        for path in filenames.get(filename, ())
        if _namespace_overlap(path, namespace_parts) >= min(2, len(namespace_parts))
    ]
    partial_candidates = [
        path
        for path in candidates
        if path in context
        and any(
            record.get("owner") == parts[-1]
            for record in context[path].get("functions", ())
        )
        and _namespace_overlap(path, namespace_parts) > 0
    ]
    return exact + _best_namespace_files(
        partial_candidates, namespace_parts, namespace_suffixes
    )


def _best_namespace_files(
    candidates: tuple[str, ...] | list[str],
    parts: tuple[str, ...],
    namespace_suffixes: Mapping[tuple[str, ...], tuple[str, ...]] | None = None,
) -> list[str]:
    if not candidates or not parts:
        return []
    if namespace_suffixes is not None:
        allowed = set(candidates)
        for overlap in range(len(parts), min(2, len(parts)) - 1, -1):
            matched = allowed.intersection(namespace_suffixes.get(parts[-overlap:], ()))
            if matched:
                return sorted(matched)
        return []
    overlaps = {path: _namespace_overlap(path, parts) for path in candidates}
    best = max(overlaps.values())
    if best < min(2, len(parts)):
        return []
    return sorted(path for path, overlap in overlaps.items() if overlap == best)


def _namespace_overlap(path: str, parts: tuple[str, ...]) -> int:
    directories = path.rsplit("/", 1)[0].split("/")
    directories = [
        section for directory in directories for section in directory.split(".")
    ]
    overlap = 0
    for imported, found in zip(reversed(parts), reversed(directories), strict=False):
        if imported != found:
            break
        overlap += 1
    return overlap


def _binding(
    path: str,
    names: list[str] | str,
    binding: str | None,
    aliases: dict[str, str] | None = None,
    *,
    owner: str | None = None,
) -> dict:
    result = {"path": path, "names": names, "binding": binding}
    if aliases:
        result["aliases"] = aliases
    if owner:
        result["owner"] = owner
    return result
