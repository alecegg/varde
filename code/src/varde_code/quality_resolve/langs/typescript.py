"""TypeScript relative import path and binding resolution."""

import re
from pathlib import PurePosixPath
from posixpath import normpath

_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx", ".mts", ".cts", ".mjs", ".cjs")


def import_targets(spec, importer_path, file_set, context):
    """Resolve a relative TypeScript spec using extension and index rules."""
    module = spec.get("module")
    if not isinstance(module, str) or not module.startswith(("./", "../")):
        return []

    raw = normpath(str(PurePosixPath(importer_path).parent / module))
    suffix = PurePosixPath(raw).suffix
    if suffix not in _EXTENSIONS:
        suffix = ""
    candidates = [raw] if suffix else []
    if suffix:
        candidates.extend(
            raw.removesuffix(suffix) + extension
            for extension in _source_extensions(suffix)
        )
    else:
        candidates.extend(raw + extension for extension in _EXTENSIONS)
        candidates.extend(f"{raw}/index{extension}" for extension in _EXTENSIONS)
    paths = set(file_set)
    matches = sorted(set(candidates) & paths)
    return matches if len(matches) == 1 else []


def import_bindings(spec, importer_path, file_set, context):
    """Resolve TypeScript import names and aliases from the source statement."""
    text = spec.get("text")
    if not isinstance(text, str):
        return []
    parsed = re.fullmatch(
        r"\s*import\s+(?:(.*?)\s+from\s+)?(['\"])(.*?)\2\s*;?\s*",
        text,
        re.DOTALL,
    )
    if not parsed:
        return _empty_binding(spec, importer_path, file_set, context)
    targets = import_targets(spec, importer_path, file_set, context)
    if len(targets) != 1:
        return []

    clause = (parsed.group(1) or "").strip()
    if clause.startswith("type "):
        clause = clause[5:].strip()
    names, aliases, binding = _import_clause(clause)
    default = _default_name(clause)
    exported = _default_export(targets[0], context, default) if default else None
    if exported and exported == default:
        names.append(default)
    elif exported:
        aliases[default] = exported
    return [
        {
            "path": targets[0],
            "names": names,
            "aliases": aliases,
            "binding": binding,
        }
    ]


def _default_name(clause):
    """Return the local name bound to the module default export, if any."""
    if not clause or clause.startswith(("{", "*")):
        return None
    first, _ = _default_and_suffix(clause)
    return first


def _default_export(target, context, local_name):
    """Name the declaration a default import binds, else None.

    The facts do not record `export default`. A public top-level declaration
    named like the import is taken as the export; otherwise a file with exactly
    one public top-level declaration is read as exporting it.
    """
    facts = context.get(target) if isinstance(context, dict) else None
    if not isinstance(facts, dict):
        return None
    functions = [
        record
        for record in facts.get("functions") or ()
        if record.get("owner") is None and not record.get("file_private")
    ]
    names = [str(record.get("name")) for record in functions]
    names += [str(record.get("name")) for record in facts.get("types") or ()]
    if names.count(local_name) == 1:
        return local_name
    return names[0] if len(names) == 1 else None


def _empty_binding(spec, importer_path, file_set, context):
    targets = import_targets(spec, importer_path, file_set, context)
    if len(targets) != 1:
        return []
    return [{"path": targets[0], "names": [], "aliases": {}, "binding": None}]


def _import_clause(clause):
    names = []
    aliases = {}
    binding = None
    if not clause:
        pass
    elif clause.startswith("{"):
        if not _named_imports(clause, names, aliases):
            names, aliases = [], {}
    else:
        first, suffix = _default_and_suffix(clause)
        if first is None:
            names, aliases = [], {}
        elif first.startswith("*"):
            match = re.fullmatch(r"\*\s+as\s+([\w$]+)", first)
            binding = match.group(1) if match else None
            if not match:
                names, aliases = [], {}
        else:
            pass
        if suffix:
            if suffix.startswith("{"):
                if not _named_imports(suffix, names, aliases):
                    names, aliases = [], {}
            elif suffix.startswith("*"):
                match = re.fullmatch(r"\*\s+as\s+([\w$]+)", suffix)
                if not match or binding is not None:
                    names, aliases, binding = [], {}, None
                else:
                    binding = match.group(1)
            else:
                names, aliases, binding = [], {}, None
    return names, aliases, binding


def _default_and_suffix(clause):
    if clause.startswith("*"):
        return clause, ""
    if "," in clause:
        first, suffix = (part.strip() for part in clause.split(",", 1))
    else:
        first, suffix = clause, ""
    if first.startswith("*"):
        return first, suffix
    if not re.fullmatch(r"[\w$]+", first):
        return None, ""
    return first, suffix


def _named_imports(clause, names, aliases):
    match = re.fullmatch(r"\{(.*)\}", clause.strip(), re.DOTALL)
    if not match:
        return False
    for iter_item in match.group(1).split(","):
        item = iter_item.strip()
        if not item:
            continue
        name = re.fullmatch(r"(?:type\s+)?([\w$]+)(?:\s+as\s+([\w$]+))?", item)
        if not name:
            return False
        target, visible = name.groups()
        if item.startswith("type "):
            continue
        if visible:
            aliases[visible] = target
        else:
            names.append(target)
    return True


def _source_extensions(suffix):
    return {
        ".js": (".ts", ".tsx"),
        ".jsx": (".tsx",),
        ".mjs": (".mts",),
        ".cjs": (".cts",),
    }.get(suffix, ())
