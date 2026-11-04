"""Rust ``use`` path to module source mapping for quality call resolution."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from functools import lru_cache
from pathlib import PurePosixPath

_CRATE_ROOT_NAMES = {"lib.rs", "main.rs"}


def import_targets(
    spec: Mapping[str, object],
    importer_path: str,
    file_set: tuple[str, ...],
    context: Mapping[str, dict],
) -> list[str]:
    """Map a Rust path to source files for its deepest known module prefix."""
    del context
    module = spec.get("module")
    if not isinstance(module, str):
        return []
    roots, files = _file_index(file_set)
    paths = _search_paths(module, importer_path, roots)
    return sorted(
        {path for root, parts in paths for path in _module_targets(root, parts, files)}
    )


def import_bindings(
    spec: Mapping[str, object],
    importer_path: str,
    file_set: tuple[str, ...],
    context: Mapping[str, dict],
) -> list[dict]:
    """Bind Rust use paths to an imported item, module, or glob."""
    module = spec.get("module")
    text = spec.get("text")
    if not isinstance(module, str) or not isinstance(text, str):
        return []
    roots, files = _file_index(file_set)
    bindings = []
    imported_paths = _imported_paths(text)
    if not imported_paths:
        return _opaque_module_bindings(module, importer_path, roots, files)
    for imported_path, alias, is_glob in imported_paths:
        search_paths = _search_paths(imported_path, importer_path, roots)
        for root, requested in search_paths:
            targets, resolved = _find_module_targets(root, requested, files)
            imported_parts = _path_parts(imported_path)
            external_crate = bool(imported_parts) and imported_parts[0] not in {
                "crate",
                "self",
                "super",
            }
            if external_crate and resolved not in {requested, requested[:-1]}:
                continue
            for path in targets:
                leaf = requested[-1] if requested else None
                if is_glob:
                    bindings.append({"path": path, "names": "*", "binding": None})
                    continue
                is_module = resolved == requested and leaf
                is_type = leaf and _has_type(context, path, leaf)
                if is_module:
                    bindings.append(
                        {"path": path, "names": [], "binding": alias or leaf}
                    )
                elif is_type:
                    type_binding = {
                        "path": path,
                        "names": [leaf],
                        "binding": alias or leaf,
                    }
                    if alias and alias != leaf:
                        type_binding = {
                            "path": path,
                            "names": [],
                            "aliases": {alias: leaf},
                            "binding": alias,
                        }
                    bindings.append(type_binding)
                elif leaf:
                    binding = {"path": path, "names": [leaf], "binding": None}
                    if alias and alias != leaf:
                        binding = {
                            "path": path,
                            "names": [],
                            "aliases": {alias: leaf},
                            "binding": None,
                        }
                    bindings.append(binding)
    return _deduplicate(bindings)


def _opaque_module_bindings(module, importer_path, roots, files):
    return [
        {"path": path, "names": [], "binding": None}
        for root, parts in _search_paths(module, importer_path, roots)
        for path in _module_targets(root, parts, files)
    ]


def _search_paths(
    module: str, importer_path: str, roots: Sequence[str]
) -> list[tuple[str, tuple[str, ...]]]:
    declared = _declared_module(module)
    if declared is not None:
        root = _crate_for_file(importer_path, roots)
        if root is None:
            return []
        return [(root, (*_module_path(root, importer_path), declared))]
    parts = _path_parts(module)
    if not parts:
        return []
    kind = parts[0]
    if kind in {"crate", "self", "super"}:
        root = _crate_for_file(importer_path, roots)
        if root is None:
            return []
        current = _module_path(root, importer_path)
        if kind == "crate":
            start = ()
        elif kind == "self":
            start = current
        elif kind == "super":
            return _super_search_path(root, current, parts)
        elif current:
            start = current[:-1]
        else:
            return []
        return [(root, (*start, *parts[1:]))]
    return [(root, tuple(parts[1:])) for root in _roots_named(kind, roots)]


def _super_search_path(
    root: str, current: tuple[str, ...], parts: tuple[str, ...]
) -> list[tuple[str, tuple[str, ...]]]:
    parents = 0
    while parents < len(parts) and parts[parents] == "super":
        parents += 1
    if parents > len(current):
        return []
    start = current[: len(current) - parents]
    return [(root, (*start, *parts[parents:]))]


def _path_parts(module: str) -> tuple[str, ...]:
    parts = tuple(
        part
        for part in module.replace("/", "::").replace("\\", "::").split("::")
        if part and part != "*"
    )
    if any(
        part in {".", ".."} or not _is_identifier(part.removeprefix("r#"))
        for part in parts
    ):
        return ()
    return tuple(part.removeprefix("r#") for part in parts)


def _declared_module(module: str) -> str | None:
    parts = module.strip().split()
    if len(parts) >= 2 and parts[-2] == "mod":
        return parts[-1].removeprefix("r#")
    return None


def _imported_paths(text: str) -> list[tuple[str, str | None, bool]]:
    statement = text.strip().removesuffix(";").strip()
    if statement.startswith("pub "):
        statement = statement[4:].strip()
    if statement.startswith("mod "):
        name = statement[4:].strip().removeprefix("r#")
        if _is_identifier(name):
            return [(f"mod {name}", None, False)]
        return []
    if not statement.startswith("use "):
        return []
    return _expand_use_tree(statement[4:].strip())


def _expand_use_tree(
    value: str, prefix: tuple[str, ...] = ()
) -> list[tuple[str, str | None, bool]]:
    opening = value.find("{")
    if opening >= 0:
        return _expand_use_group(value, opening, prefix)
    return _expand_use_item(value, prefix)


def _expand_use_group(value, opening, prefix):
    if not value.endswith("}") or "}" in value[:opening]:
        return []
    head = value[:opening].strip().removesuffix("::").strip()
    head_parts = _path_parts(head)
    entries = _split_use_group(value[opening + 1 : -1])
    if not head_parts or entries is None:
        return []
    results = []
    for entry in entries:
        expanded = _expand_use_tree(entry, (*prefix, *head_parts))
        if not expanded:
            return []
        results.extend(expanded)
    return results


def _expand_use_item(
    value: str, prefix: tuple[str, ...]
) -> list[tuple[str, str | None, bool]]:
    item = value.strip()
    if not item:
        return []
    if item == "self":
        return [("::".join(prefix), None, False)] if prefix else []
    if item == "*":
        return [("::".join(prefix), None, True)] if prefix else []
    path, alias = _split_alias(item)
    if path is None:
        return []
    parts = _path_parts(path)
    if not parts:
        return []
    is_glob = path.endswith(("::*", "/*"))
    return [("::".join((*prefix, *parts)), alias, is_glob)]


def _split_use_group(value: str) -> list[str] | None:
    parts = []
    depth = 0
    start = 0
    for index, char in enumerate(value):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                return None
        elif char == "," and depth == 0:
            parts.append(value[start:index].strip())
            start = index + 1
    if depth:
        return None
    parts.append(value[start:].strip())
    return [part for part in parts if part]


def _split_alias(value: str) -> tuple[str | None, str | None]:
    parts = value.split(" as ")
    if len(parts) > 2:
        return None, None
    path = parts[0].strip()
    alias = parts[1].strip().removeprefix("r#") if len(parts) == 2 else None
    if alias is not None and not _is_identifier(alias):
        return None, None
    return (path, alias) if path else (None, None)


def _is_identifier(value: str) -> bool:
    return value.isidentifier()


def _is_glob(module: str) -> bool:
    return module.rstrip().endswith(("::*", "/*"))


def _has_type(context: Mapping[str, dict], path: str, name: str) -> bool:
    return any(
        record.get("name") == name for record in context.get(path, {}).get("types", ())
    )


def _deduplicate(bindings: list[dict]) -> list[dict]:
    unique = {
        (
            item["path"],
            tuple(item["names"]) if isinstance(item["names"], list) else item["names"],
            item["binding"],
            tuple(sorted(item.get("aliases", {}).items())),
        ): item
        for item in bindings
    }
    return [unique[key] for key in sorted(unique, key=str)]


def _crate_roots(file_set: Sequence[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            path
            for path in file_set
            if PurePosixPath(path).suffix == ".rs"
            if _is_crate_root(path)
        )
    )


@lru_cache(maxsize=1)
def _file_index(file_set: tuple[str, ...]) -> tuple[tuple[str, ...], frozenset[str]]:
    return _crate_roots(file_set), frozenset(file_set)


def _is_crate_root(path: str) -> bool:
    source = PurePosixPath(path)
    if source.name in _CRATE_ROOT_NAMES and source.parent.name == "src":
        return True
    return source.parent.name == "bin" and source.parent.parent.name == "src"


def _crate_for_file(importer_path: str, roots: Sequence[str]) -> str | None:
    importer = PurePosixPath(importer_path)
    candidates = [
        root
        for root in roots
        if importer == PurePosixPath(root)
        or importer.is_relative_to(PurePosixPath(root).parent)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda root: len(PurePosixPath(root).parts))


def _module_path(root: str, path: str) -> tuple[str, ...]:
    if path == root:
        return ()
    source_root = PurePosixPath(root).parent
    relative = PurePosixPath(path).relative_to(source_root)
    if relative == PurePosixPath("."):
        return ()
    if relative.name == "mod.rs":
        return relative.parent.parts
    if relative.suffix == ".rs":
        return (*relative.parent.parts, relative.stem)
    return relative.parts


def _roots_named(name: str, roots: Sequence[str]) -> tuple[str, ...]:
    normalized = name.replace("-", "_")
    return tuple(
        root for root in roots if _crate_name(root).replace("-", "_") == normalized
    )


def _crate_name(root: str) -> str:
    parent = PurePosixPath(root).parent
    if parent.name == "bin":
        return parent.parent.parent.name
    return parent.parent.name


def _module_targets(
    root: str, parts: Sequence[str], file_set: Iterable[str]
) -> list[str]:
    targets, _ = _find_module_targets(root, parts, file_set)
    return targets


def _find_module_targets(
    root: str, parts: Sequence[str], file_set: Iterable[str]
) -> tuple[list[str], tuple[str, ...]]:
    source_root = PurePosixPath(root).parent
    files = file_set if isinstance(file_set, (set, frozenset)) else set(file_set)
    for length in range(len(parts), -1, -1):
        module_dir = source_root.joinpath(*parts[:length])
        if length == 0:
            candidates = [root]
        else:
            candidates = [f"{module_dir}.rs", str(module_dir / "mod.rs")]
        found = sorted(set(candidates) & files)
        if found:
            return found, tuple(parts[:length])
    return [], ()
