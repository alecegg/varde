"""C++ include resolution for the quality call resolver."""

from __future__ import annotations

import posixpath
import re
from collections.abc import Mapping
from functools import lru_cache
from pathlib import PurePosixPath

_HEADER_SUFFIXES = {".h", ".hh", ".hpp", ".hxx", ".h++", ".inl", ".ipp", ".tcc"}
_SOURCE_SUFFIXES = {".c", ".cc", ".cpp", ".cxx", ".c++"}
_LOCAL_INCLUDE = re.compile(r'^\s*#\s*include\s*(?:"([^"\n]+)"|<([^>\n]+)>)\s*$')


@lru_cache(maxsize=1)
def _file_index(file_set: tuple[str, ...]):
    headers = set()
    suffixes: dict[str, list[str]] = {}
    basenames: dict[str, list[str]] = {}
    sources: dict[str, list[str]] = {}
    for path in file_set:
        parsed = PurePosixPath(path)
        suffix = parsed.suffix.lower()
        if suffix in _HEADER_SUFFIXES:
            headers.add(path)
            basenames.setdefault(parsed.name, []).append(path)
            parts = parsed.parts
            for start in range(len(parts)):
                suffixes.setdefault("/".join(parts[start:]), []).append(path)
        elif suffix in _SOURCE_SUFFIXES:
            sources.setdefault(parsed.stem, []).append(path)
    return (
        frozenset(headers),
        {key: tuple(paths) for key, paths in suffixes.items()},
        {key: tuple(paths) for key, paths in basenames.items()},
        {key: tuple(paths) for key, paths in sources.items()},
    )


def import_targets(
    spec: Mapping[str, object],
    importer_path: str,
    file_set: tuple[str, ...],
    context: Mapping[str, dict],
) -> list[str]:
    """Map a quoted or angled include to matching repository headers."""
    del context
    return _header_paths(spec, importer_path, file_set)


def import_bindings(
    spec: Mapping[str, object],
    importer_path: str,
    file_set: tuple[str, ...],
    context: Mapping[str, dict],
) -> list[dict]:
    """Bind included headers' functions, and unambiguous paired definitions."""
    headers = _header_paths(spec, importer_path, file_set)
    if not headers:
        return []

    bindings = []
    for header in headers:
        bindings.append({"path": header, "names": "*", "binding": None})
        qualifiers = {
            function.get("qualifier")
            for function in context.get(header, {}).get("functions", [])
            if isinstance(function.get("qualifier"), str) and function["qualifier"]
        }
        bindings.extend(
            {"path": header, "names": "*", "binding": qualifier}
            for qualifier in sorted(qualifiers)
        )
        bindings.extend(
            {"path": source, "names": "*", "binding": None}
            for source in _paired_sources(header, file_set, context)
        )
    return bindings


def _header_paths(
    spec: Mapping[str, object], importer_path: str, file_set: tuple[str, ...]
) -> list[str]:
    statement = spec.get("text")
    if not isinstance(statement, str):
        return []
    match = _LOCAL_INCLUDE.fullmatch(statement)
    if match is None:
        return []
    include = (match.group(1) or match.group(2)).strip()
    is_angled = match.group(2) is not None
    if not include or PurePosixPath(include).suffix.lower() not in _HEADER_SUFFIXES:
        return []

    normalized = posixpath.normpath(include)
    if normalized.startswith("/"):
        return []
    headers, suffixes, basenames, _ = _file_index(file_set)
    relative = posixpath.normpath(
        posixpath.join(posixpath.dirname(importer_path), normalized)
    )
    if not relative.startswith("../") and relative != ".." and relative in headers:
        return [relative]

    if normalized.startswith("../"):
        return []
    if is_angled and "/" not in normalized:
        return []
    candidates = basenames.get(normalized, ()) if "/" not in normalized else ()
    if not candidates:
        candidates = suffixes.get(normalized, ())
    return sorted(candidates)


def _paired_sources(
    header: str, file_set: tuple[str, ...], context: Mapping[str, dict]
) -> list[str]:
    header_path = PurePosixPath(header)
    sources = [
        path
        for path in _file_index(file_set)[3].get(header_path.stem, ())
        if context.get(path, {}).get("functions")
    ]
    nearby = [
        path for path in sources if PurePosixPath(path).parent == header_path.parent
    ]
    if nearby:
        return sorted(nearby)
    if len(sources) == 1:
        return sources
    return []
