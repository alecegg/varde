"""Go import path to source package mapping for quality call resolution."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import PurePosixPath


def import_targets(
    spec: Mapping[str, object],
    importer_path: str,
    file_set: tuple[str, ...],
    context: Mapping[str, dict],
) -> list[str]:
    """Map a Go import path to the most specific matching package directory.

    Go's module path is not available through the language hook context, so
    paths are matched by their longest exact directory suffix. Ties are kept
    as multiple candidates for the core resolver to classify as ambiguous.
    Single-component imports are left to the default matcher to avoid binding
    standard-library names to unrelated repository directories.
    """
    del importer_path, context
    module = spec.get("module")
    if not isinstance(module, str):
        return []
    segments = _path_segments(module)
    if len(segments) < 2:
        return []

    directories = _go_directories(file_set)
    matches = []
    for length in range(
        2, min(len(segments), max(map(len, directories), default=0)) + 1
    ):
        suffix = segments[-length:]
        if length == len(segments) and "." not in segments[0]:
            continue
        matches.extend(directories.get(suffix, ()))
    if matches:
        best = max(
            _suffix_length(PurePosixPath(path).parent.parts, segments)
            for path in matches
        )
        return sorted(
            path
            for path in matches
            if _suffix_length(PurePosixPath(path).parent.parts, segments) == best
        )
    if "." not in segments[0]:
        return []
    return sorted(
        path
        for directory, paths in directories.items()
        if len(directory) >= len(segments) and directory[-len(segments) :] == segments
        for path in paths
    )


def import_bindings(
    spec: Mapping[str, object],
    importer_path: str,
    file_set: tuple[str, ...],
    context: Mapping[str, dict],
) -> list[dict]:
    """Bind imported Go package files to their package name or alias."""
    imported = _import_spec(spec)
    paths = import_targets(spec, importer_path, file_set, context)
    if not paths:
        return []
    if imported is None:
        return _opaque_bindings(paths)
    module, alias = imported
    if module != spec.get("module"):
        return _opaque_bindings(paths)
    if alias == ".":
        return [{"path": path, "names": "*", "binding": None} for path in paths]
    if alias == "_":
        return _opaque_bindings(paths)
    return [
        {
            "path": path,
            "names": [],
            "binding": alias
            or context.get(path, {}).get("package")
            or PurePosixPath(path).parent.name,
        }
        for path in paths
    ]


def _opaque_bindings(paths: Sequence[str]) -> list[dict]:
    return [{"path": path, "names": [], "binding": None} for path in paths]


def _import_spec(spec: Mapping[str, object]) -> tuple[str, str | None] | None:
    text = spec.get("text")
    if not isinstance(text, str):
        return None
    match = re.fullmatch(
        r'\s*(?:(\.|_|[A-Za-z_]\w*)\s+)?(?:"([^"]+)"|`([^`]+)`)\s*',
        text,
    )
    if match is None:
        return None
    module = match.group(2) or match.group(3)
    if not module or any(part in {".", ".."} for part in module.split("/")):
        return None
    return module, match.group(1)


def _path_segments(value: str) -> tuple[str, ...]:
    parts = tuple(part for part in value.replace("\\", "/").split("/") if part)
    if any(part in {".", ".."} for part in parts):
        return ()
    return parts


def _suffix_length(path: Sequence[str], module: Sequence[str]) -> int:
    matched = 0
    for path_part, module_part in zip(reversed(path), reversed(module), strict=False):
        if path_part != module_part:
            break
        matched += 1
    return matched


@lru_cache(maxsize=1)
def _go_directories(
    file_set: tuple[str, ...],
) -> dict[tuple[str, ...], tuple[str, ...]]:
    directories: dict[tuple[str, ...], list[str]] = {}
    for path in file_set:
        source = PurePosixPath(path)
        if source.suffix == ".go" and not path.endswith("_test.go"):
            directories.setdefault(source.parent.parts, []).append(path)
    return {key: tuple(sorted(paths)) for key, paths in directories.items()}
