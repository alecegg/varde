"""Indexed call-edge resolution for extracted entities."""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from varde_code.model import EdgeKind, EntityKind, SymbolKind
from varde_code.parse import language_for_path

from .aux import integer_value

_CALLABLE_KINDS = {EntityKind.FUNCTION, EntityKind.CLASS, EntityKind.INTERFACE}
_REPO_WIDE_LANGUAGES = {"csharp", "java", "kotlin", "scala", "swift"}
_OBJECT_METHODS = {
    "ToString",
    "Equals",
    "GetHashCode",
    "GetType",
    "Clone",
    "CompareTo",
    "Dispose",
    "DisposeAsync",
    "Finalize",
    "MemberwiseClone",
    "toString",
    "equals",
    "hashCode",
    "clone",
    "compareTo",
    "finalize",
    "close",
    "hash",
    "encode",
    "==",
    "!=",
    "<",
    "<=",
    ">",
    ">=",
}


def resolve_calls(
    entities: Sequence[Mapping[str, Any]],
    imports: Sequence[Mapping[str, Any]],
    files: Sequence[str],
    symbols: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, object]]:
    """Resolve calls with local, imported, receiver, repo-wide, and type passes."""
    callables, exports = _build_name_indexes(entities)
    imported_files = _build_import_targets(imports)
    module_bindings = _build_module_bindings(entities, symbols, files)
    stem_files = _build_stem_index(files)
    file_ids_by_parent = _build_parent_index(files)
    test_files = [_is_test_path(path) for path in files]
    repo_wide = _build_repo_wide_index(entities, test_files)
    type_context = _TypeContext(entities)
    edges = []

    for entity_id, entity in enumerate(entities):
        if entity["kind"] != EntityKind.CALL:
            continue
        file_id = int(entity["file_id"])
        target = _resolve_target(
            entity,
            file_id,
            files,
            callables,
            exports,
            imported_files,
            module_bindings,
            stem_files,
            file_ids_by_parent,
            repo_wide,
            type_context,
        )
        if target is not None and not (
            test_files[file_id] or not test_files[int(entities[target]["file_id"])]
        ):
            target = None
        edges.append(_call_edge(file_id, entity_id, target))
    return edges


def _build_name_indexes(entities: Sequence[Mapping[str, Any]]):
    callables_exact: dict[int, dict[str, list[int]]] = defaultdict(
        lambda: defaultdict(list)
    )
    callables_normalized: dict[int, dict[str, list[int]]] = defaultdict(
        lambda: defaultdict(list)
    )
    exports_exact: dict[int, dict[str, int]] = defaultdict(dict)
    exports_normalized: dict[int, dict[str, list[int]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for entity_id, entity in enumerate(entities):
        kind = entity["kind"]
        if kind not in _CALLABLE_KINDS and kind != EntityKind.EXPORT:
            continue
        file_id = int(entity["file_id"])
        name = str(entity["name"])
        normalized = _callee_key(name)
        if kind in _CALLABLE_KINDS:
            callables_exact[file_id][name].append(entity_id)
            callables_normalized[file_id][normalized].append(entity_id)
        exports_exact[file_id].setdefault(name, entity_id)
        exports_normalized[file_id][normalized].append(exports_exact[file_id][name])
    return (callables_exact, callables_normalized), (exports_exact, exports_normalized)


def _build_import_targets(
    imports: Sequence[Mapping[str, Any]],
) -> dict[int, list[int]]:
    targets: dict[int, list[int]] = defaultdict(list)
    for edge in imports:
        if edge["resolved"] and edge["kind"] == EdgeKind.IMPORT.as_str():
            targets[int(edge["from"])].append(int(edge["to"]["id"]))
    return targets


def _build_module_bindings(
    entities: Sequence[Mapping[str, Any]],
    symbols: Sequence[Mapping[str, Any]],
    files: Sequence[str],
) -> dict[int, set[str]]:
    bindings: dict[int, set[str]] = defaultdict(set)
    symbols_by_file: dict[int, list[Mapping[str, object]]] = defaultdict(list)
    for symbol in symbols:
        if symbol["kind"] in {SymbolKind.BINDING, SymbolKind.REFERENCE}:
            symbols_by_file[integer_value(symbol["file_id"])].append(symbol)
    for entity in entities:
        if entity["kind"] != EntityKind.IMPORT:
            continue
        raw = entity.get("owner_type")
        if isinstance(raw, str):
            bindings[int(entity["file_id"])].update(
                name.strip() for name in raw.split(",") if name.strip()
            )
        file_id = int(entity["file_id"])
        if language_for_path(files[file_id]) != "python":
            continue
        start = int(entity.get("start_byte", -1))
        end = int(entity.get("end_byte", -1))
        if start < 0 or end < start:
            continue
        bindings[file_id].update(
            str(symbol["name"])
            for symbol in symbols_by_file.get(file_id, ())
            if start <= integer_value(symbol.get("start_byte", -1))
            and integer_value(symbol.get("end_byte", -1)) <= end
        )
    return bindings


def _build_stem_index(files: Sequence[str]) -> dict[str, list[int]]:
    result: dict[str, list[int]] = defaultdict(list)
    for file_id, path in enumerate(files):
        stem = Path(path).stem
        if stem:
            result[stem].append(file_id)
    return result


def _build_parent_index(files: Sequence[str]) -> dict[Path, list[int]]:
    result: dict[Path, list[int]] = defaultdict(list)
    for file_id, path in enumerate(files):
        result[Path(path).parent].append(file_id)
    return result


def _build_repo_wide_index(
    entities: Sequence[Mapping[str, Any]], test_files: Sequence[bool]
) -> dict[str, int | None]:
    result: dict[str, int | None] = {}
    for entity_id, entity in enumerate(entities):
        file_id = int(entity["file_id"])
        if test_files[file_id] or entity["kind"] not in _CALLABLE_KINDS:
            continue
        name = str(entity["name"])
        if entity["kind"] == EntityKind.FUNCTION and entity.get("owner_type") == name:
            continue
        if name in _OBJECT_METHODS:
            continue
        key = _callee_key(name)
        if key in result:
            result[key] = None
        else:
            result[key] = entity_id
    return result


class _TypeContext:
    def __init__(self, entities: Sequence[Mapping[str, Any]]) -> None:
        self.var_types: dict[tuple[int, str], str] = {}
        self.subtypes: dict[str, list[str]] = defaultdict(list)
        self.method_index: dict[tuple[str, str], list[int]] = defaultdict(list)
        self.type_names: set[str] = set()
        interfaces: set[str] = set()

        for entity in entities:
            kind = entity["kind"]
            name = str(entity["name"])
            if kind == EntityKind.TYPE_REF and isinstance(
                entity.get("enclosing_function"), str
            ):
                self.var_types[
                    (int(entity["file_id"]), str(entity["enclosing_function"]))
                ] = name
            elif kind in {EntityKind.EXTENDS, EntityKind.IMPLEMENTS}:
                owner = entity.get("enclosing_function")
                if isinstance(owner, str):
                    self.subtypes[name].append(owner)
            elif kind in {EntityKind.CLASS, EntityKind.INTERFACE}:
                self.type_names.add(name)
                if kind == EntityKind.INTERFACE:
                    interfaces.add(name)

        for entity_id, entity in enumerate(entities):
            owner = entity.get("owner_type")
            if (
                entity["kind"] == EntityKind.FUNCTION
                and isinstance(owner, str)
                and owner not in interfaces
            ):
                self.method_index[(owner, _callee_key(str(entity["name"])))].append(
                    entity_id
                )

    def resolve(self, file_id: int, call_name: str) -> int | None:
        receiver = _call_receiver(call_name)
        if receiver is None:
            return None
        owners = []
        variable_type = self.var_types.get((file_id, receiver))
        if variable_type is not None:
            owners.append(variable_type)
            owners.extend(self.subtypes.get(variable_type, ()))
        if receiver in self.type_names:
            owners.append(receiver)
            owners.extend(self.subtypes.get(receiver, ()))
        return _one_candidate(
            entity_id
            for owner in owners
            for entity_id in self.method_index.get((owner, _callee_key(call_name)), ())
        )

    def receiver_is_external(self, file_id: int, call_name: str) -> bool:
        receiver = _call_receiver(call_name)
        if receiver is None:
            return False
        type_name = self.var_types.get((file_id, receiver))
        return type_name is not None and type_name not in self.type_names


def _resolve_target(
    entity: Mapping[str, object],
    file_id: int,
    files: Sequence[str],
    callables: tuple[
        Mapping[int, Mapping[str, Sequence[int]]],
        Mapping[int, Mapping[str, Sequence[int]]],
    ],
    exports: tuple[
        Mapping[int, Mapping[str, int]], Mapping[int, Mapping[str, Sequence[int]]]
    ],
    imported_files: Mapping[int, Sequence[int]],
    module_bindings: Mapping[int, set[str]],
    stem_files: Mapping[str, Sequence[int]],
    file_ids_by_parent: Mapping[Path, Sequence[int]],
    repo_wide: Mapping[str, int | None],
    type_context: _TypeContext,
) -> int | None:
    name = str(entity["name"])
    key = _callee_key(name)
    local = _one_candidate(callables[0].get(file_id, {}).get(key, ()))
    if local is None:
        local = _one_candidate(callables[1].get(file_id, {}).get(key, ()))
    if local is not None:
        return local

    cross = _cross_file_target(imported_files, exports, file_id, key)
    if cross is not None:
        return cross

    receiver = _receiver_module_target(
        name,
        file_id,
        files,
        imported_files,
        module_bindings,
        stem_files,
        file_ids_by_parent,
        exports[1],
    )
    if receiver is not None:
        return receiver

    language = language_for_path(files[file_id])
    namespace = language in _REPO_WIDE_LANGUAGES
    if namespace and not type_context.receiver_is_external(file_id, name):
        repo_target = repo_wide.get(key)
        if repo_target is not None:
            return repo_target
    if namespace or language == "swift":
        return type_context.resolve(file_id, name)
    return None


def _cross_file_target(imported_files, exports, file_id: int, key: str) -> int | None:
    exact, normalized = exports
    candidates = []
    for target_file in imported_files.get(file_id, ()):
        exact_target = exact.get(target_file, {}).get(key)
        if exact_target is not None:
            candidates.append(exact_target)
        candidates.extend(normalized.get(target_file, {}).get(key, ()))
    return _one_candidate(candidates)


def _receiver_module_target(
    name,
    file_id,
    files,
    imported_files,
    bindings,
    stem_files,
    file_ids_by_parent,
    exports,
):
    trimmed = name.strip().removesuffix("()").strip()
    if "." not in trimmed:
        return None
    receiver_path, method = trimmed.rsplit(".", 1)
    receiver = re.split(r"[.:]", receiver_path)[-1].strip()
    if not receiver or not method or receiver not in bindings.get(file_id, set()):
        return None
    python_imports = _python_import_targets(
        file_id, files, imported_files, file_ids_by_parent
    )
    candidates = (
        target
        for target_file in stem_files.get(receiver, ())
        if not python_imports or target_file in python_imports
        for target in exports.get(target_file, {}).get(_callee_key(method), ())
    )
    return _one_candidate(candidates)


def _python_import_targets(file_id, files, imported_files, file_ids_by_parent):
    if language_for_path(files[file_id]) != "python":
        return set()
    package_directories = {
        Path(files[target_file]).parent
        for target_file in imported_files.get(file_id, ())
        if Path(files[target_file]).name == "__init__.py"
    }
    if not package_directories:
        return None
    return {
        target_file
        for directory in package_directories
        for target_file in file_ids_by_parent.get(directory, ())
    }


def _call_receiver(name: str) -> str | None:
    trimmed = name.strip().removesuffix("()").strip()
    if "." not in trimmed:
        return None
    receiver = trimmed.rsplit(".", 1)[0].rstrip()
    receiver = re.split(r"[. ()]", receiver)[-1].strip()
    return receiver or None


def _one_candidate(values) -> int | None:
    found = None
    for value in values:
        if found is not None and found != value:
            return None
        found = value
    return found


def _is_test_path(path: str) -> bool:
    if any(
        marker in path
        for marker in (
            "/test/",
            "/tests/",
            "/__tests__/",
            "/spec/",
            "/specs/",
            "/fixture/",
            "/fixtures/",
            ".test.",
            ".spec.",
        )
    ) or path.startswith(("test/", "tests/")):
        return True
    suffixes = (
        "_test.go",
        "_test.py",
        "Test.java",
        "Tests.java",
        "Test.kt",
        "Tests.kt",
        "Test.cs",
        "Tests.cs",
        "_test.cc",
        "_test.cpp",
        "_test.cxx",
        ".t.sol",
        ".bats",
        "_spec.rb",
        "_test.rb",
        "/test.rs",
        "/tests.rs",
    )
    python_prefix = path.endswith(".py") and (
        "/test_" in path or path.startswith("test_")
    )
    dotnet_test = any(
        segment in path
        for segment in (
            ".Test/",
            ".Tests/",
            ".UnitTests/",
            ".IntegrationTests/",
            ".FunctionalTests/",
            ".AcceptanceTests/",
        )
    )
    return (
        python_prefix
        or path.endswith(suffixes)
        or path in {"test.rs", "tests.rs"}
        or dotnet_test
    )


def _callee_key(name: str) -> str:
    normalized = name.strip().removesuffix("()").strip()
    return re.split(r"[.:\s]", normalized)[-1]


def _call_edge(
    file_id: int, entity_id: int, target_id: int | None
) -> dict[str, object]:
    target = {"target": "unknown"}
    if target_id is not None:
        target = {"target": "entity", "id": target_id}
    return {
        "from": file_id,
        "to": target,
        "kind": EdgeKind.CALL.as_str(),
        "resolved": target_id is not None,
        "from_entity": entity_id,
    }
