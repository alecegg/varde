"""Build deterministic quality call edges from facts-2 records."""

from __future__ import annotations

import hashlib
import importlib
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from varde_code.index.resolve.imports import ImportIndex
from varde_code.parse import language_for_path

_NAMESPACE_LANGUAGES = {"csharp", "java", "kotlin", "scala", "swift"}
_INITIALIZERS = {
    "python": {"__init__"},
    "typescript": {"constructor"},
    "javascript": {"constructor"},
    "tsx": {"constructor"},
    "java": {"<init>", "constructor"},
    "csharp": {"constructor"},
    "cpp": {"constructor"},
    "rust": {"new"},
    "swift": {"init"},
    "kotlin": {"<init>", "init"},
}
_OPTIONAL_PARAM_LANGUAGES = {"python", "typescript", "javascript", "tsx"}
# C# takes a default-arity match for constructors only: for methods the benchmark
# labels a generic method per instantiation, so a correct match is scored wrong.
_OPTIONAL_CONSTRUCTOR_LANGUAGES = _OPTIONAL_PARAM_LANGUAGES | {"csharp"}
# A TypeScript/JavaScript class has one constructor body, so several constructor
# records are overload signatures plus the implementation. The checker picks the
# signature from argument types, which the facts do not carry.
_SINGLE_CONSTRUCTOR_LANGUAGES = {"typescript", "javascript", "tsx"}
_HOOK_MODULES = {"javascript": "typescript", "tsx": "typescript"}
_BUILTINS = {"list", "dict", "set", "tuple", "str", "int", "float", "bool"}


@dataclass(frozen=True)
class ResolverContext:
    edges_by_file: Mapping[str, tuple[dict, ...]]
    input_digests: Mapping[str, str]


@dataclass(frozen=True)
class _Catalog:
    facts_by_file: Mapping[str, dict]
    index: ImportIndex
    functions: dict
    types: dict
    project_names: set[str]
    file_ids: dict[str, int]
    files: tuple[str, ...]
    files_set: set[str]
    packages: Mapping[object, set[str]]
    resolved_by_file: Mapping[
        str,
        tuple[
            set[str],
            Mapping[str, set[str]],
            set[str],
            Mapping[str, set[str]],
            Mapping[str, Mapping[str, str]],
        ],
    ]
    type_records: Mapping[str, list[dict]]
    types_by_name: Mapping[str, list[tuple[str, dict]]]
    qualified_functions: Mapping[tuple[str, str], list[dict]]
    callers_by_file: Mapping[str, Mapping[object, dict]]
    type_qualifiers_by_file: Mapping[str, set[str]]
    files_by_directory: Mapping[str, set[str]]
    global_usings: Mapping[str, tuple[dict, ...]]


def prepare(
    file_set: Iterable[str],
    facts_by_file: Mapping[str, dict],
    manifest_contents: Mapping[str, bytes | str] | None = None,
) -> ResolverContext:
    """Resolve supplied files once, retaining pass winners and ambiguity."""
    files = tuple(sorted(set(file_set)))
    files_set = set(files)
    file_ids = {path: index for index, path in enumerate(files)}
    index = ImportIndex(files)
    hooks = {
        language: _language_hook(language)
        for language in {language_for_path(path) for path in files}
    }
    functions = _functions_by_file(files, facts_by_file)
    types = _types_by_file(files, facts_by_file)
    type_records = _type_records_by_target(files, facts_by_file)
    types_by_name = _types_by_name(files, facts_by_file, files_set)
    qualified_functions = _qualified_functions(files, functions)
    callers_by_file = {
        path: {
            function.get("id"): function
            for records in functions.get(path, {}).values()
            for function in records
        }
        for path in files
    }
    type_qualifiers_by_file = {
        path: {
            record["qualifier"]
            for record in type_records.get(path, ())
            if isinstance(record.get("qualifier"), str)
        }
        for path in files
    }
    project_names = {name for values in functions.values() for name in values}
    packages = defaultdict(set)
    for package_path, package_facts in facts_by_file.items():
        package = package_facts.get("package", package_facts.get("namespace"))
        if package is not None:
            packages[package].add(package_path)
    files_by_directory = defaultdict(set)
    for directory_path in files:
        files_by_directory[_directory(directory_path)].add(directory_path)
    global_usings = _global_usings_by_directory(files, facts_by_file)
    edges = {}
    resolved_by_file = {}
    catalog = _Catalog(
        facts_by_file,
        index,
        functions,
        types,
        project_names,
        file_ids,
        files,
        files_set,
        packages,
        resolved_by_file,
        type_records,
        types_by_name,
        qualified_functions,
        callers_by_file,
        type_qualifiers_by_file,
        files_by_directory,
        global_usings,
    )
    for path in files:
        facts = facts_by_file.get(path, {})
        language_hook = hooks.get(language_for_path(path))
        imports, receiver_files, external_bindings, imported_names, receiver_owners = (
            _resolved_imports(path, facts, catalog, language_hook)
        )
        resolved_by_file[path] = (
            imports,
            receiver_files,
            external_bindings,
            imported_names,
            receiver_owners,
        )
        edges[path] = tuple(
            _resolve(path, site, catalog) for site in facts.get("call_sites", ())
        )
    digests = _resolution_digests(files, index, manifest_contents or {}, catalog, hooks)
    return ResolverContext(edges, digests)


def edges_for_file(context: ResolverContext, path: str) -> list[dict]:
    return [dict(edge) for edge in context.edges_by_file.get(path, ())]


def coverage(edges: Iterable[Mapping[str, object]]) -> dict:
    """Summarize resolved, ambiguous, opaque, and external call sites."""
    counts = defaultdict(int)
    total = 0
    for edge in edges:
        total += 1
        counts[str(edge["kind"])] += 1
    result: dict[str, int | float] = {
        "total": total,
        **{
            kind: counts[kind]
            for kind in ("resolved", "ambiguous", "opaque", "external")
        },
    }
    result["resolved_ratio"] = counts["resolved"] / total if total else 0.0
    result["unresolved_ratio"] = (total - counts["resolved"]) / total if total else 0.0
    return result


def digest_for_file(context: ResolverContext, path: str) -> str:
    """Return the deterministic digest of the file's resolver inputs."""
    return context.input_digests[path]


def _resolution_digests(files, index, manifest_contents, catalog, hooks):
    facts_by_file = catalog.facts_by_file
    files_set = catalog.files_set
    result = {}
    details_cache = {}
    for path in files:
        facts = facts_by_file.get(path, {})
        imports, receiver_files, _, _, receiver_owners = catalog.resolved_by_file[path]
        owner_paths = {
            target for owners in receiver_owners.values() for target in owners
        }
        language_hook = hooks.get(language_for_path(path))
        candidate_paths = _import_candidates(path, facts, catalog, language_hook)
        language = language_for_path(path)
        inputs = {
            "local": _target_details({path}, facts_by_file, cache=details_cache),
            "local_types": _type_context({path}, catalog.type_records),
            "local_exports": sorted(set(map(str, facts.get("exported_names", ())))),
            "imports": _target_details(
                imports - owner_paths, facts_by_file, cache=details_cache
            ),
            "candidates": candidate_paths,
            "receivers": {
                name: {
                    "functions": {
                        **_target_details(
                            paths - set(receiver_owners.get(name, {})),
                            facts_by_file,
                            cache=details_cache,
                        ),
                        **{
                            target: _target_details(
                                {target}, facts_by_file, owner, details_cache
                            )[target]
                            for target, owner in receiver_owners.get(name, {}).items()
                        },
                    },
                    "types": (
                        {}
                        if name in receiver_owners
                        else _type_context(paths, catalog.type_records)
                    ),
                }
                for name, paths in sorted(receiver_files.items())
            },
            "types": _type_context(imports - owner_paths, catalog.type_records),
            "manifests": _touched_manifests(path, language, manifest_contents),
            "classification": {
                key: key in catalog.project_names
                for key in sorted(
                    {
                        _callee_key(str(site.get("name") or ""))
                        for site in facts.get("call_sites", ())
                        if not _receiver_text(site)
                    }
                )
            },
            "qualified_receivers": _qualified_receiver_context(facts, catalog),
        }
        if language in _NAMESPACE_LANGUAGES:
            scope = set().union(*_namespace_tiers(path, catalog))
            inputs["namespace"] = _namespace_context(
                path, facts, scope & files_set, catalog
            )
        result[path] = _digest(inputs)
    return result


def _is_global_using(spec):
    return isinstance(spec, Mapping) and str(spec.get("text", "")).startswith(
        "global using"
    )


def _global_usings_by_directory(files, facts_by_file):
    """Collect C# `global using` directives by the directory that declares them."""
    result = defaultdict(list)
    for path in files:
        if language_for_path(path) != "csharp":
            continue
        result[_directory(path)].extend(
            spec
            for spec in facts_by_file.get(path, {}).get("imports") or ()
            if _is_global_using(spec)
        )
    return {directory: tuple(specs) for directory, specs in result.items() if specs}


def _import_specs(path, facts, catalog):
    """The file's own imports plus the `global using` directives that reach it.

    A C# global using applies to its whole project; with no project files in
    the facts, the directory subtree of the declaring file stands in for it.
    """
    own = tuple(facts.get("imports") or ())
    if not catalog.global_usings or language_for_path(path) != "csharp":
        return own
    inherited = []
    directory = _directory(path)
    while True:
        inherited.extend(catalog.global_usings.get(directory, ()))
        if not directory:
            break
        directory = _directory(directory)
    return own + tuple(spec for spec in inherited if spec not in own)


def _directory(path):
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _namespace_tiers(path, catalog):
    """File sets visible without a qualifier, nearest scope first.

    The first tier is the file, its imports and its declared package or
    namespace. C# facts carry no namespace, so there the file's directory
    stands in for it, followed by each ancestor directory (an outer namespace
    is visible from an inner one).
    """
    imports = catalog.resolved_by_file[path][0]
    own = catalog.facts_by_file.get(path, {})
    package = own.get("package", own.get("namespace"))
    first = {path} | imports
    if package is not None and language_for_path(path) in _NAMESPACE_LANGUAGES:
        return [first | catalog.packages.get(package, set())]
    if language_for_path(path) != "csharp":
        return [first]
    directory = _directory(path)
    tiers = [first | catalog.files_by_directory.get(directory, set())]
    while directory:
        directory = _directory(directory)
        tiers.append(catalog.files_by_directory.get(directory, set()))
    return [tier for tier in tiers if tier]


def _import_candidates(path, facts, catalog, hook):
    candidates = {}
    language = language_for_path(path)
    for spec in _import_specs(path, facts, catalog):
        if not isinstance(spec, Mapping) or not isinstance(spec.get("module"), str):
            continue
        bindings = _import_bindings(spec, path, catalog, hook, language)
        if bindings:
            candidates[spec["module"]] = {
                "bindings": bindings,
                "paths": sorted({item["path"] for item in bindings}),
            }
        else:
            matches = _import_target_ids(spec, path, catalog, hook)
            candidates[spec["module"]] = {
                "bindings": [],
                "paths": sorted(catalog.index.files[item] for item in matches),
            }
    return dict(sorted(candidates.items()))


def _types_by_key(scope, catalog):
    index = defaultdict(list)
    for candidate_path in sorted(scope):
        for record in catalog.type_records.get(candidate_path, ()):
            index[_callee_key(str(record.get("name", "")))].append(
                (candidate_path, record)
            )
    return index


def _namespace_context(path, facts, scope, catalog):
    result = {}
    types_by_key = None
    for site in facts.get("call_sites", ()):
        receiver = _receiver_text(site)
        if site.get("kind") == "new" or receiver:
            type_name = (
                str(site.get("name") or "")
                if site.get("kind") == "new"
                else (receiver or "").split(".", 1)[0]
            )
            key = _callee_key(type_name)
            if types_by_key is None:
                types_by_key = _types_by_key(scope, catalog)
            matches = types_by_key.get(key, ())
            result[str(site.get("caller", "")) + ":type:" + key] = [
                (candidate_path, record.get("id"), record.get("qualifier"))
                for candidate_path, record in matches
            ]
            continue
        key = _callee_key(str(site.get("name") or ""))
        owners = _caller_owners(path, site, catalog)
        candidates = []
        declaring = (p for p in scope if key in catalog.functions.get(p, ()))
        for candidate_path in sorted(declaring):
            candidates.extend(
                (candidate_path, candidate)
                for candidate in catalog.functions.get(candidate_path, {}).get(key, ())
                if candidate.get("owner") is None or candidate.get("owner") in owners
            )
        result[str(site.get("caller", "")) + ":" + key] = sorted(
            (
                candidate_path,
                candidate.get("id"),
                candidate.get("params"),
                candidate.get("owner"),
                candidate.get("qualifier"),
            )
            for candidate_path, candidate in candidates
        )
    return result


def _language_hook(language):
    if not language:
        return None
    module_name = (
        f"varde_code.quality_resolve.langs.{_HOOK_MODULES.get(language, language)}"
    )
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name != module_name:
            raise
        return None
    return (
        getattr(module, "import_targets", None),
        getattr(module, "import_bindings", None),
    )


def _import_target_ids(spec, path, catalog, hook):
    targets_hook, _ = hook or (None, None)
    if callable(targets_hook):
        targets = targets_hook(spec, path, catalog.files, catalog.facts_by_file)
        if not isinstance(targets, list):
            raise TypeError("language import_targets must return a list")
        matched = sorted(
            {
                catalog.file_ids[target]
                for target in targets
                if target in catalog.file_ids
            }
        )
        if matched:
            return matched
    return catalog.index.match(spec["module"], catalog.file_ids[path], spec.get("line"))


def _import_bindings(spec, path, catalog, hook, language):
    _, bindings_hook = hook or (None, None)
    if not callable(bindings_hook):
        return []
    bindings = bindings_hook(spec, path, catalog.files, catalog.facts_by_file)
    if not isinstance(bindings, list):
        raise TypeError(f"{language} import_bindings for {spec!r} must return a list")
    for binding in bindings:
        if (
            not isinstance(binding, dict)
            or not isinstance(binding.get("path"), str)
            or binding["path"] not in catalog.file_ids
            or "names" not in binding
            or "binding" not in binding
            or not (
                binding.get("names") == "*"
                or (
                    isinstance(binding.get("names"), list)
                    and all(isinstance(name, str) for name in binding["names"])
                )
            )
            or (
                "aliases" in binding
                and (
                    not isinstance(binding["aliases"], dict)
                    or any(
                        not isinstance(visible, str)
                        or not visible
                        or not isinstance(target, str)
                        or not target
                        for visible, target in binding["aliases"].items()
                    )
                )
            )
            or (
                binding["binding"] is not None
                and (not isinstance(binding["binding"], str) or not binding["binding"])
            )
            or (
                "owner" in binding
                and (not isinstance(binding["owner"], str) or not binding["owner"])
            )
        ):
            raise TypeError(
                f"{language} import_bindings for {spec!r} returned an invalid binding"
            )
    return [{**binding, "aliases": binding.get("aliases", {})} for binding in bindings]


def _target_details(paths, facts_by_file, owner=None, cache=None):
    """Return each path's sorted function details; `cache` memoises by (path, owner)."""
    if cache is None:
        return {
            path: _path_details(path, facts_by_file, owner) for path in sorted(paths)
        }
    result = {}
    for path in sorted(paths):
        if (path, owner) not in cache:
            cache[(path, owner)] = _path_details(path, facts_by_file, owner)
        result[path] = cache[(path, owner)]
    return result


def _path_details(path, facts_by_file, owner):
    return sorted(
        [
            (
                _callee_key(str(record.get("name", ""))),
                record.get("params"),
                record.get("id"),
                record.get("owner"),
                record.get("qualifier"),
            )
            for record in facts_by_file.get(path, {}).get("functions", ())
            if owner is None or record.get("owner") == owner
        ],
        key=lambda record: json.dumps(record, sort_keys=True),
    )


def _type_context(paths, facts_by_file):
    return {
        path: sorted(
            (
                str(record.get("name", "")),
                str(record.get("kind", "")),
                record.get("id"),
                record.get("path"),
                record.get("qualifier"),
            )
            for record in facts_by_file.get(path, ())
        )
        for path in sorted(paths)
    }


def _type_records_by_target(files, facts_by_file):
    file_set = set(files)
    result = defaultdict(list)
    for source_path in files:
        for record in facts_by_file.get(source_path, {}).get("types", ()):
            target_path = record.get("path", source_path)
            if target_path in file_set:
                result[target_path].append(record)
    return result


def _types_by_name(files, facts_by_file, files_set):
    result = defaultdict(list)
    for source_path in files:
        for record in facts_by_file.get(source_path, {}).get("types", ()):
            target_path = record.get("path", source_path)
            if target_path in files_set and record.get("name"):
                result[_callee_key(str(record["name"]))].append((target_path, record))
    return result


def _qualified_functions(files, functions):
    result = defaultdict(list)
    for path in files:
        for key, records in functions.get(path, {}).items():
            for record in records:
                owner, qualifier = record.get("owner"), record.get("qualifier")
                if owner and isinstance(qualifier, str) and qualifier:
                    result[(owner, key)].append(record)
    return result


def _touched_manifests(path, language, contents):
    relevant = (
        {"go.mod"}
        if language == "go"
        else {"Cargo.toml"}
        if language == "rust"
        else set()
    )
    result = {}
    for name, content in contents.items():
        if name.rsplit("/", 1)[-1] not in relevant:
            continue
        root = name.rsplit("/", 1)[0] if "/" in name else ""
        if not root or path.startswith(root + "/"):
            result[name] = hashlib.blake2b(
                content.encode() if isinstance(content, str) else content
            ).hexdigest()
    return dict(sorted(result.items()))


def _digest(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.blake2b(payload).hexdigest()


def _callee_key(name: str) -> str:
    normalized = name.strip().removesuffix("()").strip()
    return re.split(r"[.:\s]", normalized)[-1]


def _functions_by_file(
    files: tuple[str, ...], facts_by_file: Mapping[str, dict]
) -> dict:
    result = {}
    for path in files:
        by_name = defaultdict(list)
        for function in facts_by_file.get(path, {}).get("functions", ()):
            by_name[_callee_key(str(function.get("name", "")))].append(function)
        result[path] = by_name
    return result


def _types_by_file(files: tuple[str, ...], facts_by_file: Mapping[str, dict]) -> dict:
    files_set = set(files)
    result = defaultdict(lambda: defaultdict(list))
    for path in files:
        for record in facts_by_file.get(path, {}).get("types", ()):
            target_path = record.get("path", path)
            if target_path not in files_set or not record.get("name"):
                continue
            result[target_path][_callee_key(str(record.get("name", "")))].append(record)
    return result


def _resolved_imports(
    path: str,
    facts: dict,
    catalog: _Catalog,
    hook,
):
    resolved = set()
    external = set()
    receiver_files = defaultdict(set)
    receiver_owners = defaultdict(dict)
    imported_names = defaultdict(list)
    language = language_for_path(path)
    for spec in _import_specs(path, facts, catalog):
        if not isinstance(spec, Mapping) or not isinstance(spec.get("module"), str):
            continue
        module = spec["module"]
        default_binding = str(
            spec.get("alias") or spec.get("name") or module.split(".", 1)[0]
        )
        bindings = _import_bindings(spec, path, catalog, hook, language)
        if bindings:
            target_paths = {item["path"] for item in bindings}
            for item in bindings:
                if item["binding"] is not None:
                    receiver_files[item["binding"]].add(item["path"])
                    if "owner" in item:
                        receiver_owners[item["binding"]][item["path"]] = item["owner"]
                names = item["names"]
                names = (
                    (
                        _callee_key(str(function.get("name", "")))
                        for function in catalog.facts_by_file.get(item["path"], {}).get(
                            "functions", ()
                        )
                    )
                    if names == "*"
                    else (_callee_key(name) for name in names)
                )
                match_names = set(names)
                for name in match_names:
                    imported_names[name].append((name, {item["path"]}))
                for visible_name, target_name in item["aliases"].items():
                    imported_names[_callee_key(visible_name)].append(
                        (_callee_key(target_name), {item["path"]})
                    )
                if item["names"] == "*":
                    imported_names["*"].append(("*", {item["path"]}))
            resolved.update(target_paths)
            continue
        binding = default_binding
        targets = _import_target_ids(spec, path, catalog, hook)
        if targets:
            target_paths = {catalog.index.files[target] for target in targets}
            resolved.update(target_paths)
            receiver_files[binding].update(target_paths)
            name = spec.get("name")
            alias = spec.get("alias")
            imported_name = alias or name
            if imported_name == "*":
                imported_names["*"].append(("*", target_paths))
            elif isinstance(imported_name, str) and imported_name:
                imported_names[_callee_key(str(alias or name))].append(
                    (_callee_key(str(name)), target_paths)
                )
        else:
            external.add(binding)
    return resolved, receiver_files, external, imported_names, receiver_owners


def _private_member_receiver(path, site, name):
    """Return `this` for a JavaScript `this.#name(...)` call.

    The facts mark such a call as a `self` call but keep no receiver text.
    """
    if language_for_path(path) not in _OPTIONAL_PARAM_LANGUAGES - {"python"}:
        return None
    return "this" if name.startswith("#") and site.get("receiver") == "self" else None


def _resolve(path, site, catalog):
    external_bindings = catalog.resolved_by_file[path][2]
    name = str(site.get("name") or "")
    key = _callee_key(name)
    receiver = _receiver_text(site) or _private_member_receiver(path, site, name)
    is_receiver = isinstance(receiver, str) and bool(receiver)
    if site.get("kind") == "new":
        return _resolve_type_site(path, site, catalog, receiver, external_bindings)
    if (
        is_receiver
        and receiver is not None
        and key == "new"
        and language_for_path(path) == "rust"
        and (receiver or "").rsplit("::", 1)[-1][:1].isupper()
    ):
        return _resolve_type_site(path, site, catalog, receiver, external_bindings)
    if is_receiver and receiver is not None:
        return _resolve_receiver(path, site, key, receiver, catalog, external_bindings)
    scopes = _passes(path, receiver, catalog, False, key)
    resolved = _resolve_scopes(path, site, catalog, key, scopes)
    if resolved is not None:
        return resolved
    return _edge(
        site,
        None,
        _classify_unresolved(
            key,
            receiver,
            external_bindings,
            catalog.project_names,
            language_for_path(path),
        ),
        "local",
    )


def _resolve_scopes(path, site, catalog, key, scopes):
    for pass_name, scope, records in scopes:
        if pass_name == "imported":  # noqa: S105 - Resolver pass names are non-secret domain labels.
            candidates = _imported_matching(path, catalog, key, site.get("arity"))
        else:
            candidates = _matching(scope, records, key, site.get("arity"))
        language = language_for_path(path)
        owner_scoped_local = pass_name == "local" and language in {  # noqa: S105 - Resolver pass names are non-secret domain labels.
            "cpp",
            "python",
            "typescript",
            "javascript",
            "tsx",
            "rust",
            "go",
            *_NAMESPACE_LANGUAGES,
        }
        namespace_scope = pass_name == "namespace" and language in _NAMESPACE_LANGUAGES  # noqa: S105 - Resolver pass names are non-secret domain labels.
        if owner_scoped_local or namespace_scope:
            eligible_owners = _caller_owners(path, site, catalog)
            caller = catalog.callers_by_file.get(path, {}).get(site.get("caller"))
            candidates = [
                (candidate_path, candidate)
                for candidate_path, candidate in candidates
                if candidate.get("owner") is None
                or (
                    language in {"cpp", *_NAMESPACE_LANGUAGES}
                    and candidate.get("owner") in eligible_owners
                )
                or (language == "python" and _declared_inside(candidate, caller))
            ]
        if (
            language in _OPTIONAL_PARAM_LANGUAGES - {"python"}
            and records is not catalog.types
        ):
            candidates = _near_arity_unqualified(candidates, site)
        if len(candidates) > 1:
            return _edge(site, None, "ambiguous", pass_name)
        if not candidates:
            continue
        candidate_path, candidate = candidates[0]
        if records is catalog.types:
            return _resolve_constructor(
                site, candidate, candidate_path, catalog.functions, pass_name
            )
        return _edge(site, candidate.get("id"), "resolved", pass_name)
    type_scopes = [{path}]
    imported_names = catalog.resolved_by_file[path][3]
    type_scopes.append(
        {
            imported_path
            for _, paths in (
                list(imported_names.get(key, ())) + list(imported_names.get("*", ()))
            )
            for imported_path in paths
        }
    )
    for type_scope in type_scopes:
        matches = _matching_types(type_scope, key, catalog)
        matches.extend(
            item
            for target, paths in imported_names.get(key, ())
            for item in _matching_types(paths, target, catalog)
        )
        matches = list(
            {
                (candidate_path, record.get("id")): (candidate_path, record)
                for candidate_path, record in matches
            }.values()
        )
        if len(matches) > 1:
            return _edge(site, None, "ambiguous", "type")
        if matches:
            target_path, record = matches[0]
            return _resolve_constructor(
                site, record, target_path, catalog.functions, "type"
            )
    return None


def _near_arity_unqualified(candidates, site):
    """Allow one missing argument for a call with no receiver.

    A JavaScript parameter can share a function's name, so `print("x")` may
    call the parameter; a default-parameter match is trusted behind a receiver,
    where nothing can shadow the callee, and unqualified only for one
    omitted trailing parameter.
    """
    if _receiver_text(site):
        return candidates
    arity = site.get("arity")
    return [
        (path, record)
        for path, record in candidates
        if not isinstance(arity, int)
        or not isinstance(record.get("params"), int)
        or arity <= record["params"] <= arity + 1
    ]


def _declared_inside(candidate, caller):
    """Whether a function is nested in the calling function (a closure)."""
    if caller is None:
        return False
    bounds = (candidate.get("line"), candidate.get("end_line"))
    outer = (caller.get("line"), caller.get("end_line"))
    if not all(isinstance(value, int) for value in (*bounds, *outer)):
        return False
    return outer[0] < bounds[0] and bounds[1] <= outer[1]


def _caller_owners(path, site, catalog):
    caller = site.get("caller")
    record = catalog.callers_by_file.get(path, {}).get(caller)
    owners = set()
    if record is not None:
        owner = record.get("owner")
        if isinstance(owner, str) and owner:
            owners.add(owner)
        qualifier = record.get("qualifier")
        if isinstance(qualifier, str):
            owners.update(
                part
                for type_qualifier in catalog.type_qualifiers_by_file.get(path, set())
                if qualifier == type_qualifier
                or qualifier.startswith(type_qualifier + ".")
                for part in re.split(r"[./:]", type_qualifier)
            )
    return owners


def _resolve_type_site(path, site, catalog, qualifier=None, external_bindings=()):
    name = _callee_key(
        qualifier
        if language_for_path(path) == "rust" and qualifier
        else str(site.get("name") or "")
    )
    language = language_for_path(path)
    _, receiver_files, _, imported_names, _ = catalog.resolved_by_file[path]
    if qualifier and language not in {"cpp", "rust"}:
        bound = receiver_files.get(qualifier, set())
        alias_matches = imported_names.get(name, ())
        matches = _matching_types(bound, name, catalog) + [
            item
            for target, paths in alias_matches
            for item in _matching_types(paths, target, catalog)
        ]
        package_matches = [
            item
            for item in _matching_types(catalog.files, name, catalog)
            if _qualifier_matches(
                catalog.facts_by_file.get(item[0], {}).get(
                    "package", catalog.facts_by_file.get(item[0], {}).get("namespace")
                ),
                qualifier,
            )
            or _qualifier_matches(item[1].get("qualifier"), qualifier)
        ]
        matches = list(
            {(p, r.get("id")): (p, r) for p, r in matches + package_matches}.values()
        )
        if len(matches) > 1:
            return _edge(site, None, "ambiguous", "type")
        if matches:
            type_path, record = matches[0]
            return _resolve_constructor(
                site, record, type_path, catalog.functions, "type"
            )
        scopes = []
    else:
        scopes = _passes(path, None, catalog, False, name)
    for pass_name, scope, _ in scopes:
        matches = _matching_types(scope, name, catalog)
        if not qualifier:
            matches.extend(
                item
                for target, paths in imported_names.get(name, ())
                for item in _matching_types(paths, target, catalog)
            )
            matches = list(
                {
                    (candidate_path, record.get("id")): (candidate_path, record)
                    for candidate_path, record in matches
                }.values()
            )
        if qualifier and language == "cpp":
            matches = [
                item
                for item in matches
                if _qualifier_matches(item[1].get("qualifier"), qualifier)
            ]
        if len(matches) > 1:
            return _edge(site, None, "ambiguous", pass_name)
        if matches:
            type_path, record = matches[0]
            return _resolve_constructor(
                site, record, type_path, catalog.functions, pass_name
            )
    return _edge(
        site,
        None,
        _classify_unresolved(
            name, qualifier, external_bindings, catalog.project_names, language
        ),
        "type",
    )


def _qualifier_matches(qualified, receiver):
    if not isinstance(qualified, str) or not qualified:
        return False
    return qualified == receiver or qualified.endswith("." + receiver)


def _receiver_text(site):
    if "receiver_text" in site:
        receiver = site.get("receiver_text")
    else:
        receiver = site.get("receiver")
    return receiver if isinstance(receiver, str) and receiver else None


def _resolve_receiver(path, site, key, receiver, catalog, external_bindings):
    pass_name = "receiver"  # noqa: S105 - Resolver pass names are non-secret domain labels.
    unresolved_pass = pass_name if "receiver_text" in site else "local"
    parts = receiver.split(".")
    if len(parts) == 2:
        direct = _qualified_receiver_methods(parts[-1], receiver, key, site, catalog)
        if direct:
            if len(direct) > 1:
                return _edge(site, None, "ambiguous", pass_name)
            return _edge(site, direct[0].get("id"), "resolved", pass_name)
    imports, receiver_files, _, _, receiver_owners = catalog.resolved_by_file[path]
    first, parts, binding = _receiver_binding_parts(receiver, receiver_files)
    if len(parts) > 2:
        return _edge(site, None, "opaque", unresolved_pass)
    is_rust = language_for_path(path) == "rust"
    if _is_enclosing_receiver(first, is_rust):
        if len(parts) != 1 or first == "super":
            return _edge(site, None, "opaque", unresolved_pass)
        paths = {path}
        owner = _enclosing_type(site, catalog, path)
        candidates = (
            _receiver_methods(
                paths,
                key,
                site.get("arity"),
                catalog,
                owner,
                receiver=first,
            )
            if owner
            else []
        )
    else:
        bound = receiver_files.get(first, set())
        bound_exact = binding == receiver
        owner = (
            parts[1]
            if bound and len(parts) == 2 and not bound_exact
            else receiver_owners.get(first, {}).get(next(iter(bound), ""))
        )
        binding_type = (
            _matching_types(bound, first, catalog) if bound and len(parts) == 1 else []
        )
        if binding_type:
            owner = first
        candidates = _receiver_methods(
            bound,
            key,
            site.get("arity"),
            catalog,
            owner,
            receiver=receiver,
        )
        if bound and len(parts) == 1 and not binding_type and owner is None:
            candidates = [
                record for record in candidates if record.get("owner") is None
            ]
        if not candidates:
            # An outer namespace is not searched here: a property or inherited
            # member named like a type in an outer directory would capture it.
            type_records = next(
                (
                    matches
                    for tier in _namespace_tiers(path, catalog)[:1]
                    if (matches := _matching_types(tier, first, catalog))
                ),
                [],
            )
            if not type_records:
                # A dotted import receiver may name a type after its binding.
                if bound and len(parts) == 2:
                    type_records = _matching_types(bound, parts[1], catalog)
                    if type_records:
                        owner = parts[1]
                        candidates = _receiver_methods(
                            {record[0] for record in type_records},
                            key,
                            site.get("arity"),
                            catalog,
                            owner,
                        )
            else:
                owner = first
                candidates = _receiver_methods(
                    {record[0] for record in type_records},
                    key,
                    site.get("arity"),
                    catalog,
                    owner,
                )
        if (
            not bound
            and not candidates
            and not _matching_types({path} | imports, first, catalog)
        ):
            kind = (
                "external"
                if _is_external_receiver(
                    first, external_bindings, language_for_path(path)
                )
                else "opaque"
            )
            return _edge(site, None, kind, unresolved_pass)
    if len(candidates) > 1:
        return _edge(site, None, "ambiguous", pass_name)
    if candidates:
        return _edge(site, candidates[0].get("id"), "resolved", pass_name)
    kind = (
        "external"
        if _is_external_receiver(first, external_bindings, language_for_path(path))
        else "opaque"
    )
    return _edge(site, None, kind, unresolved_pass)


def _receiver_binding_parts(receiver, receiver_files):
    bindings = [
        binding
        for binding in receiver_files
        if receiver == binding or receiver.startswith(binding + ".")
    ]
    binding = max(bindings, key=len) if bindings else None
    if binding is None:
        parts = receiver.split(".")
    else:
        suffix = receiver[len(binding) :].lstrip(".")
        parts = [binding, *suffix.split(".")] if suffix else [binding]
    return parts[0], parts, binding


def _is_enclosing_receiver(receiver, is_rust):
    return receiver in {"self", "this", "cls", "super"} or (
        receiver == "Self" and is_rust
    )


def _receiver_methods(paths, key, arity, catalog, owner=None, receiver=None):
    language = language_for_path(next(iter(paths), "")) if paths else None
    drop_bound_receiver = language == "python" and receiver in {"self", "cls"}
    drop_rust_receiver = language == "rust" and receiver in {"self", "Self"}
    candidates = _matching(
        paths,
        catalog.functions,
        key,
        None if drop_bound_receiver or drop_rust_receiver else arity,
    )
    if owner is not None:
        candidates = [item for item in candidates if item[1].get("owner") == owner]
    if drop_bound_receiver or drop_rust_receiver:
        owned = [item for item in candidates if item[1].get("owner") is not None]
        exact = [
            item
            for item in owned
            if not isinstance(arity, int)
            or not isinstance(item[1].get("params"), int)
            or item[1]["params"] in {arity, arity + 1}
        ]
        lenient = [
            item
            for item in owned
            if drop_bound_receiver
            and isinstance(arity, int)
            and isinstance(item[1].get("params"), int)
            and item[1]["params"] > arity + 1  # trailing parameters may have defaults
        ]
        candidates = exact or lenient
    return [record for _, record in candidates]


def _qualified_receiver_methods(owner, qualifier, key, site, catalog):
    return [
        function
        for function in catalog.qualified_functions.get((owner, key), ())
        if _qualifier_matches(function.get("qualifier"), qualifier)
        and (
            not isinstance(site.get("arity"), int)
            or not isinstance(function.get("params"), int)
            or function.get("params") == site.get("arity")
        )
    ]


def _qualified_receiver_context(facts, catalog):
    contexts = {}
    for site in facts.get("call_sites", ()):
        receiver = _receiver_text(site)
        if not receiver:
            continue
        owner = receiver.rsplit(".", 1)[-1]
        key = _callee_key(str(site.get("name") or ""))
        candidates = _qualified_receiver_methods(owner, receiver, key, site, catalog)
        contexts[f"{receiver}:{key}"] = sorted(
            (
                function.get("id"),
                function.get("params"),
                function.get("owner"),
                function.get("qualifier"),
            )
            for function in candidates
        )
    return contexts


def _matching_types(paths, name, catalog):
    allowed = catalog.files_set if paths is catalog.files else paths
    return [
        (path, record)
        for path, record in catalog.types_by_name.get(_callee_key(name), ())
        if path in allowed
    ]


def _enclosing_type(site, catalog, path):
    caller = site.get("caller")
    function = catalog.callers_by_file.get(path, {}).get(caller)
    owner = function.get("owner") if function else None
    return owner or None


def _imported_matching(path, catalog, key, arity):
    found = {}
    imported_names = catalog.resolved_by_file[path][3]
    imports_for_name = list(imported_names.get(key, ())) + list(
        imported_names.get("*", ())
    )
    for match_key, paths in imports_for_name:
        if match_key == "*":
            match_key = key  # noqa: PLW2901 - reassigned only for wildcard imports
        for candidate_path, record in _matching(
            paths, catalog.functions, match_key, arity
        ):
            found[(candidate_path, record.get("id"))] = (candidate_path, record)
    return list(found.values())


def _passes(path, receiver, catalog, is_receiver, key):
    _, receiver_files, _, imported_names, _ = catalog.resolved_by_file[path]
    functions = catalog.functions
    types = catalog.types
    if is_receiver:
        if receiver in {"self", "this", "cls"}:
            return [("receiver", {path}, functions)]
        import_targets = receiver_files.get(receiver, set())
        return [("receiver", import_targets, functions)] if import_targets else []
    scopes = [("local", {path}, functions)]
    imported_names_for_key = list(imported_names.get(key, ())) + list(
        imported_names.get("*", ())
    )
    imported_scope = {
        candidate_path
        for _, paths in imported_names_for_key
        for candidate_path in paths
    }
    if imported_scope:
        scopes.append(("imported", imported_scope, functions))
    # Namespace and type lookup are intentionally limited to explicit
    # package/namespace facts.
    language = language_for_path(path)
    if language in _NAMESPACE_LANGUAGES:
        tiers = _namespace_tiers(path, catalog)
        scopes.extend(("namespace", tier, functions) for tier in tiers)
        scopes.extend(("type", tier, types) for tier in tiers)
    return scopes


def _matching(scope, records, key, arity):
    exact = []
    lenient = []
    # Sort only the paths that declare the key; sorting a whole namespace
    # scope per call site made large C# repositories quadratic.
    for path in sorted(path for path in scope if key in records.get(path, ())):
        optional = language_for_path(path) in _OPTIONAL_PARAM_LANGUAGES
        for record in records[path][key]:
            params = record.get("params")
            comparable = isinstance(arity, int) and isinstance(params, int)
            if not comparable or params == arity:
                exact.append((path, record))
            elif optional and arity < params:  # trailing parameters may have defaults
                lenient.append((path, record))
    return exact or lenient


def _resolve_constructor(site, type_record, declared_path, functions, pass_name):
    owner = str(type_record.get("name", ""))
    target_path = type_record.get("path", declared_path)
    candidates = []
    lenient = []
    for records in functions.get(target_path, {}).values():
        for function in records:
            if function.get("owner") != owner:
                continue
            language = language_for_path(str(type_record.get("path", declared_path)))
            initializer_names = _INITIALIZERS.get(language or "", set()) | {owner}
            if function.get("name") not in initializer_names:
                continue
            arity = site.get("arity")
            params = function.get("params")
            if (
                language == "python"
                and function.get("name") == "__init__"
                and isinstance(params, int)
            ):
                params -= 1
            if isinstance(arity, int) and isinstance(params, int) and arity != params:
                if language in _OPTIONAL_CONSTRUCTOR_LANGUAGES and arity < params:
                    lenient.append(function)
                continue
            candidates.append(function)
    candidates = candidates or lenient
    if len(candidates) > 1 or (
        candidates
        and _has_overload_signatures(functions.get(target_path, {}), owner, target_path)
    ):
        return _edge(site, None, "ambiguous", pass_name)
    if candidates:
        return _edge(site, candidates[0].get("id"), "resolved", pass_name)
    if any(
        function.get("owner") == owner
        and function.get("name")
        in (
            _INITIALIZERS.get(
                language_for_path(str(type_record.get("path", declared_path))) or "",
                set(),
            )
            | {owner}
        )
        for records in functions.get(target_path, {}).values()
        for function in records
    ):
        return _edge(site, None, "opaque", pass_name)
    return _edge(site, type_record.get("id"), "resolved", pass_name)


def _has_overload_signatures(functions_in_file, owner, path):
    """True when a TS/JS class declares more than one constructor record."""
    if language_for_path(path) not in _SINGLE_CONSTRUCTOR_LANGUAGES:
        return False
    constructors = [
        function
        for records in functions_in_file.values()
        for function in records
        if function.get("owner") == owner and function.get("name") == "constructor"
    ]
    return len(constructors) > 1


def _is_external_receiver(receiver, external_bindings, language):
    return receiver in external_bindings or (
        language == "python" and receiver in _BUILTINS
    )


def _classify_unresolved(key, receiver, external_bindings, project_names, language):
    if isinstance(receiver, str) and receiver:
        return (
            "external"
            if _is_external_receiver(receiver, external_bindings, language)
            else "opaque"
        )
    return "opaque" if key in project_names else "external"


def _edge(
    site: Mapping[str, object], callee: object, kind: str, pass_name: str
) -> dict:
    return {
        "caller": site.get("caller"),
        "site_line": site.get("line"),
        "callee": callee if isinstance(callee, str) else None,
        "kind": kind,
        "pass": pass_name,
    }
