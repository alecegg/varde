"""Python import path and binding resolution for the quality resolver."""

import ast
from functools import lru_cache
from pathlib import PurePosixPath
from posixpath import normpath


@lru_cache(maxsize=1)
def _file_index(file_set):
    paths = frozenset(file_set)
    suffix_matches = {}
    for path in file_set:
        if path.endswith(".py"):
            parts = path.split("/")
            for start in range(len(parts)):
                suffix_matches.setdefault("/".join(parts[start:]), []).append(path)
    return paths, {key: tuple(values) for key, values in suffix_matches.items()}


def import_targets(spec, importer_path, file_set, context):
    """Resolve a Python module spec to one repository source file."""
    module = spec.get("module")
    if not isinstance(module, str) or not module:
        return []

    importer = PurePosixPath(importer_path)
    if module.startswith(("./", "../")):
        relative = normpath(str(importer.parent / module))
    elif module.startswith("."):
        dots = len(module) - len(module.lstrip("."))
        parent = importer.parent
        for _ in range(dots - 1):
            parent = parent.parent
        relative = normpath(str(parent / module[dots:].replace(".", "/")))
    else:
        relative = module.replace(".", "/")

    if module.startswith(("./", "../", ".")):
        candidates = _module_paths(PurePosixPath(relative))
    else:
        bases = (importer.parent, *importer.parent.parents)
        candidates = [
            candidate for base in bases for candidate in _module_paths(base / relative)
        ]
    paths, suffix_index = _file_index(file_set)
    matches = sorted(set(candidates) & paths)
    if not module.startswith(("./", "../", ".")):
        suffix_matches = set(suffix_index.get(f"{relative}.py", ()))
        suffix_matches.update(suffix_index.get(f"{relative}/__init__.py", ()))
        if len(suffix_matches) > 1:
            return []
    return matches if len(matches) == 1 else []


def import_bindings(spec, importer_path, file_set, context):
    """Resolve imported Python names and aliases against one source file."""
    text = spec.get("text")
    if not isinstance(text, str):
        return []
    try:
        statement = ast.parse(text).body
    except SyntaxError:
        return _empty_binding(spec, importer_path, file_set, context)
    if len(statement) != 1:
        return _empty_binding(spec, importer_path, file_set, context)

    node = statement[0]
    if isinstance(node, ast.Import):
        return _module_bindings(node, spec, importer_path, file_set, context)
    if isinstance(node, ast.ImportFrom):
        return _member_bindings(node, spec, importer_path, file_set, context)
    return _empty_binding(spec, importer_path, file_set, context)


def _module_bindings(node, spec, importer_path, file_set, context):
    results = []
    for item in node.names:
        module = item.name
        if module.replace(".", "/") != spec.get("module"):
            continue
        bound_module = module if item.asname else module.split(".", 1)[0]
        targets = import_targets(
            {"module": bound_module, "line": spec.get("line")},
            importer_path,
            file_set,
            context,
        )
        if len(targets) != 1:
            continue
        if not item.asname and "." in module:
            dotted_targets = import_targets(
                {"module": module, "line": spec.get("line")},
                importer_path,
                file_set,
                context,
            )
            if len(dotted_targets) == 1:
                results.append(
                    {
                        "path": dotted_targets[0],
                        "names": [],
                        "binding": module,
                    }
                )
        results.append(
            {
                "path": targets[0],
                "names": [],
                "binding": item.asname or module.split(".", 1)[0],
            }
        )
    return results


def _member_bindings(node, spec, importer_path, file_set, context):
    bindings = _raw_member_bindings(node, spec, importer_path, file_set, context)
    result = []
    for binding in bindings:
        result.extend(_redirect_reexports(binding, file_set, context))
    return result


_REEXPORT_DEPTH = 4


def _redirect_reexports(binding, file_set, context):
    """Point each imported name at the file that defines it, through re-exports."""
    names = binding["names"]
    if names == "*" or not isinstance(names, list):
        return [binding]
    aliases = binding.get("aliases") or {}
    wanted = [(name, name) for name in names] + list(aliases.items())
    if not wanted:
        return [binding]
    grouped = {}
    for visible, original in wanted:
        path, final = _defining_file(binding["path"], original, file_set, context)
        grouped.setdefault(path, []).append((visible, final))
    if list(grouped) == [binding["path"]] and all(
        visible in names or aliases.get(visible) == final
        for visible, final in grouped[binding["path"]]
    ):
        return [binding]
    result = []
    for path, pairs in grouped.items():
        result.append(
            {
                **binding,
                "path": path,
                "names": [visible for visible, final in pairs if visible == final],
                "aliases": {
                    visible: final for visible, final in pairs if visible != final
                },
            }
        )
    return result


def _defining_file(path, name, file_set, context, depth=_REEXPORT_DEPTH):
    """Follow `from x import name` re-exports until a file defines the name."""
    facts = context.get(path, {})
    if depth == 0 or _defines(facts, name):
        return path, name
    source = _reexport_source(facts, path, name, file_set, context, depth)
    return (path, name) if source is None else source


def _defines(facts, name):
    return any(
        record.get("name") == name and record.get("owner") is None
        for record in facts.get("functions", ())
    ) or any(record.get("name") == name for record in facts.get("types", ()))


def _reexport_source(facts, path, name, file_set, context, depth):
    named = set()
    starred = set()
    for spec, node in _from_imports(facts):
        targets = import_targets(spec, path, file_set, context)
        if len(targets) != 1:
            continue
        for item in node.names:
            if item.name == "*":
                starred.add(targets[0])
            elif (item.asname or item.name) == name:
                named.add((targets[0], item.name))
    if len(named) == 1:
        target, original = next(iter(named))
        return _defining_file(target, original, file_set, context, depth - 1)
    if named:
        return None
    defined = {
        found
        for target in starred
        for found in [_defining_file(target, name, file_set, context, depth - 1)]
        if _defines(context.get(found[0], {}), found[1])
    }
    return next(iter(defined)) if len(defined) == 1 else None


def _from_imports(facts):
    for spec in facts.get("imports") or ():
        text = spec.get("text") if isinstance(spec, dict) else None
        if not isinstance(text, str):
            continue
        try:
            body = ast.parse(text).body
        except SyntaxError:
            continue
        if len(body) == 1 and isinstance(body[0], ast.ImportFrom):
            yield spec, body[0]


def _empty_binding(spec, importer_path, file_set, context):
    targets = import_targets(spec, importer_path, file_set, context)
    if len(targets) != 1:
        return []
    return [{"path": targets[0], "names": [], "aliases": {}, "binding": None}]


def _raw_member_bindings(node, spec, importer_path, file_set, context):
    module = spec.get("module")
    if not isinstance(module, str) or not module:
        return []
    targets = import_targets(spec, importer_path, file_set, context)
    if len(targets) != 1:
        return []
    if any(item.name == "*" for item in node.names):
        target_facts = context.get(targets[0], {})
        exports = _explicit_exports(target_facts)
        names = {
            function.get("name")
            for function in target_facts.get("functions", ())
            if function.get("owner") is None
            and isinstance(function.get("name"), str)
            and not function["name"].startswith("_")
        }
        if exports is not None:
            names &= exports
        return [
            {
                "path": targets[0],
                "names": sorted(names),
                "aliases": {},
                "binding": None,
            }
        ]
    submodules = []
    submodule_names = set()
    for item in node.names:
        if item.name == "*":
            continue
        base = PurePosixPath(targets[0])
        directory = base.parent
        candidates = (
            str(directory / f"{item.name}.py"),
            str(directory / item.name / "__init__.py"),
        )
        matches = set(candidates) & set(file_set)
        if len(matches) == 1:
            submodule_names.add(item.name)
            submodules.append(
                {
                    "path": next(iter(matches)),
                    "names": [],
                    "binding": item.asname or item.name,
                }
            )
    remaining = [item for item in node.names if item.name not in submodule_names]
    if submodules and not remaining:
        return submodules
    if submodules:
        names = [item.name for item in remaining if item.name != "*"]
        aliases = {
            item.asname: item.name
            for item in remaining
            if item.name != "*" and item.asname
        }
        names = [name for name in names if name not in aliases.values()]
        return [
            *submodules,
            {
                "path": targets[0],
                "names": names,
                "aliases": aliases,
                "binding": None,
            },
        ]
    names = [item.name for item in node.names if item.name != "*"]
    aliases = {
        item.asname: item.name
        for item in node.names
        if item.name != "*" and item.asname
    }
    names = [name for name in names if name not in aliases.values()]
    imported_names = "*" if any(item.name == "*" for item in node.names) else names
    return [
        {
            "path": targets[0],
            "names": imported_names,
            "aliases": aliases,
            "binding": None,
        }
    ]


def _explicit_exports(facts):
    if "exported_names" not in facts:
        return None
    exports = facts.get("exported_names")
    names = set()
    for item in exports:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            names.add(str(item[1]))
    return names


def _module_paths(base):
    raw = str(base)
    candidates = [raw + ".py", raw + "/__init__.py"]
    if raw.endswith(".py"):
        candidates.insert(0, raw)
    return candidates
