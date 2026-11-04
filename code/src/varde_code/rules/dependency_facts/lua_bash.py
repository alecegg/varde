"""Lua module and Bash relative-file dependency facts."""

from __future__ import annotations

import stat
from pathlib import Path

from ...parse import language_for_path
from .types import (
    Fact,
    FactInput,
    FileRow,
    ImportRow,
    certified_fact,
    indexed_paths,
    metadata_if_exists,
    missing_fact,
    physical_targets,
    resolve_relative_path,
)


def facts(input: FactInput) -> list[Fact]:
    by_id = {file.id: file for file in input.files}
    indexed = indexed_paths(input.files)
    candidates = [
        file
        for file in input.files
        if not file.is_test
        and not file.is_tooling
        and language_for_path(file.path) == "lua"
    ]
    output: list[Fact] = []
    for source in input.files:
        language = language_for_path(source.path)
        if source.is_test or source.is_tooling or language not in {"lua", "bash"}:
            continue
        root = repository_root(source)
        for imp in imports_of(input, source):
            if language == "lua":
                fact = lua_fact(root, by_id, indexed, candidates, source, imp)
            else:
                fact = bash_fact(root, by_id, indexed, source, imp)
            if fact is not None:
                output.append(fact)
    return output


def repository_root(source: FileRow) -> Path:
    root = source.physical
    for _ in Path(source.relative).parts:
        root = root.parent
    return root


def imports_of(input: FactInput, source: FileRow) -> list[ImportRow]:
    return [
        imp for imp in input.imports if imp.file_id == source.id and not imp.type_only
    ]


def is_lua_module(module: str) -> bool:
    if not module or module.startswith("/") or module.endswith("/"):
        return False
    return all(
        segment
        and segment[0].isascii()
        and (segment[0].isalpha() or segment[0] == "_")
        and all(char.isascii() and (char.isalnum() or char in "_-") for char in segment)
        for segment in module.split("/")
    )


def lua_candidates(candidates: list[FileRow], module: str) -> list[str]:
    filenames = (f"{module}.lua", f"{module}/init.lua")
    found = {
        file.relative
        for file in candidates
        if any(
            file.relative == name or file.relative.endswith("/" + name)
            for name in filenames
        )
    }
    return sorted(found)


def lua_module_is_repository_owned(candidates: list[FileRow], module: str) -> bool:
    if "/" not in module:
        return False
    parent = module.rsplit("/", 1)[0]
    return any(
        file.relative.startswith(parent + "/")
        or file.relative.startswith("lua/" + parent + "/")
        for file in candidates
    )


def lua_fact(
    root: Path,
    by_id: dict[int, FileRow],
    indexed: dict[str, list[int]],
    candidates: list[FileRow],
    source: FileRow,
    imp: ImportRow,
) -> Fact | None:
    module = imp.specifier
    if not is_lua_module(module):
        return None
    matches = lua_candidates(candidates, module)
    if len(matches) > 1:
        return None
    if matches:
        physical = root / matches[0]
        metadata = metadata_if_exists(physical)
        if metadata is None or not stat.S_ISREG(metadata.st_mode):
            return None
        ids = indexed.get(matches[0], [])
        return certified_fact(by_id, source, imp, ids[0]) if len(ids) == 1 else None
    if lua_module_is_repository_owned(candidates, module):
        return missing_fact(source, imp)
    return None


def is_literal_relative_path(specifier: str) -> bool:
    if (
        not specifier.startswith(("./", "../"))
        or specifier.endswith("/")
        or "//" in specifier
    ):
        return False
    return all(
        char.isascii() and (char.isalnum() or char in "_-./+") for char in specifier
    )


def bash_fact(
    root: Path,
    by_id: dict[int, FileRow],
    indexed: dict[str, list[int]],
    source: FileRow,
    imp: ImportRow,
) -> Fact | None:
    specifier = imp.specifier
    if not is_literal_relative_path(specifier):
        return None
    base = resolve_relative_path(source.relative, specifier)
    if base is None:
        return None
    targets = physical_targets(root, [base])
    if len(targets.paths) == 1:
        ids = indexed.get(base, [])
        return certified_fact(by_id, source, imp, ids[0]) if len(ids) == 1 else None
    if not targets.paths and not targets.existing_path:
        return missing_fact(source, imp)
    return None
