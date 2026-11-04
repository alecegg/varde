"""Elixir and Haskell module dependency facts."""

from __future__ import annotations

import contextlib
from pathlib import Path

from ...parse import language_for_path
from .types import Fact, FactInput, FileRow, ImportRow, certified_fact, missing_fact


def facts(input: FactInput) -> list[Fact]:
    return elixir_facts(input) + haskell_facts(input)


def is_module_path(name: str, separator: str) -> bool:
    return bool(name) and all(
        part
        and part[0].isupper()
        and all(char.isalnum() or char == "_" for char in part)
        for part in name.split(separator)
    )


def read_source(file: FileRow) -> str | None:
    try:
        return file.physical.read_bytes().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return None


def modules_by_name(
    files: list[FileRow] | tuple[FileRow, ...], lang: str, parse_module
) -> dict[str, dict[str, FileRow]]:
    modules: dict[str, dict[str, FileRow]] = {}
    for file in files:
        if language_for_path(file.path) != lang:
            continue
        text = read_source(file)
        if text is None:
            continue
        for name in parse_module(text):
            modules.setdefault(name, {}).setdefault(file.relative, file)
    return modules


def elixir_facts(input: FactInput) -> list[Fact]:
    by_id = {file.id: file for file in input.files}
    modules = modules_by_name(input.files, "elixir", elixir_modules)
    output: list[Fact] = []
    for source in input.files:
        if (
            source.is_test
            or source.is_tooling
            or language_for_path(source.path) != "elixir"
        ):
            continue
        for imp in imports_of(input, source):
            spec = imp.specifier
            if imp.type_only or not is_module_path(spec, "."):
                continue
            targets = modules.get(spec, {})
            if len(targets) == 1:
                target = next(iter(targets.values()))
                fact = certified_fact(by_id, source, imp, target.id)
                if fact is not None:
                    output.append(fact)
            elif not targets and missing_parent_declared(modules, spec, "."):
                output.append(missing_fact(source, imp))
    return output


def elixir_modules(text: str) -> list[str]:
    stack: list[tuple[int, str]] = []
    modules: list[str] = []
    for line in text.splitlines():
        code = line.split("#", 1)[0]
        indent = len(code) - len(code.lstrip())
        trimmed = code.lstrip()
        rest = next(
            (
                trimmed[len(keyword) :]
                for keyword in ("defmodule", "defprotocol")
                if trimmed.startswith(keyword)
            ),
            None,
        )
        if rest is None or not rest.startswith((" ", "\t", "(")):
            continue
        name = rest.lstrip(" \t(").split("end", 1)[0]
        name = "".join(
            char if (char.isalnum() or char in "_.") else "\0" for char in name
        ).split("\0", 1)[0]
        if not is_module_path(name, "."):
            continue
        while stack and stack[-1][0] >= indent:
            stack.pop()
        full = f"{stack[-1][1]}.{name}" if stack else name
        stack.append((indent, full))
        modules.append(full)
    return modules


def haskell_facts(input: FactInput) -> list[Fact]:
    by_id = {file.id: file for file in input.files}
    files = [file for file in input.files if language_for_path(file.path) == "haskell"]
    declared: dict[str, dict[str, FileRow]] = {}
    declared_by_file: dict[str, str] = {}
    by_path = [file for file in files if file.relative.endswith(".hs")]
    for file in files:
        text = read_source(file)
        name = haskell_module(text or "") if text is not None else None
        if name:
            module = name.replace(".", "/")
            declared.setdefault(module, {}).setdefault(file.relative, file)
            declared_by_file[file.relative] = module
    output: list[Fact] = []
    manifests: dict[Path, set[str] | None] = {}
    tree_names: set[str] | None = None
    root = repository_root(input.files[0]) if input.files else None
    for source in files:
        if source.is_test or source.is_tooling:
            continue
        text = read_source(source)
        if text is None:
            continue
        imports = imports_of(input, source, include_type_only=True)
        for imp, guarded in pair_imports(imports, scan_haskell_imports(text)):
            if guarded or imp.type_only:
                continue
            spec = imp.specifier
            if not is_module_path(spec, "/"):
                continue
            targets = haskell_targets(declared, by_path, declared_by_file, spec)
            if len(targets) == 1:
                fact = certified_fact(by_id, source, imp, targets[0].id)
                if fact is not None:
                    output.append(fact)
                continue
            if targets or is_generated_module(spec):
                continue
            owned = manifest_owns(manifests, root, source, spec)
            if owned is None:
                owned = missing_parent_declared(declared, spec, "/")
            if not owned:
                continue
            if root is not None:
                if tree_names is None:
                    tree_names = collect_names(root)
                name = spec.rsplit("/", 1)[-1]
                if any(
                    item == name or item.startswith(name + ".") for item in tree_names
                ):
                    continue
            output.append(missing_fact(source, imp))
    return output


def haskell_targets(
    declared: dict[str, dict[str, FileRow]],
    by_path: list[FileRow],
    declared_by_file: dict[str, str],
    spec: str,
) -> list[FileRow]:
    found: dict[str, FileRow] = dict(declared.get(spec, {}))
    suffix = "/" + spec
    for file in by_path:
        base = file.relative[:-3]
        if (base == spec or base.endswith(suffix)) and declared_by_file.get(
            file.relative, spec
        ) == spec:
            found[file.relative] = file
    return list(found.values())


def haskell_module(text: str) -> str | None:
    for iter_line in text.splitlines():
        line = iter_line.strip()
        if not line.startswith("module "):
            continue
        name = line[7:].split(None, 1)[0].split("(", 1)[0]
        if is_module_path(name, "."):
            return name
    return None


def scan_haskell_imports(text: str) -> list[tuple[str, bool]]:
    depth = 0
    in_block = False
    result: list[tuple[str, bool]] = []
    for raw in text.splitlines():
        line, in_block = strip_haskell_block_comment(raw, in_block)
        trimmed = line.strip()
        if trimmed.startswith("#"):
            keyword = (
                trimmed[1:].lstrip().split(None, 1)[0] if trimmed[1:].strip() else ""
            )
            if keyword in {"if", "ifdef", "ifndef"}:
                depth += 1
            elif keyword == "endif":
                depth = max(0, depth - 1)
            continue
        line = blank_pragmas(trimmed)
        spec = haskell_import_spec(line)
        if spec:
            result.append((spec, depth > 0))
    return result


def strip_haskell_block_comment(line: str, in_block: bool) -> tuple[str, bool]:
    if in_block:
        end = line.find("-}")
        if end < 0:
            return "", True
        return line[end + 2 :], False
    start = line.find("{-")
    if start < 0:
        return line, False
    end = line.find("-}", start + 2)
    if end < 0:
        return line[:start], True
    return line[:start] + " " + line[end + 2 :], False


def blank_pragmas(line: str) -> str:
    while "{-#" in line:
        start = line.find("{-#")
        end = line.find("#-}", start + 3)
        if end < 0:
            return line[:start]
        line = line[:start] + " " + line[end + 3 :]
    return line


def haskell_import_spec(line: str) -> str | None:
    tokens = line.split()
    if not tokens or tokens[0] != "import":
        return None
    for token in tokens[1:]:
        if token[0].isupper() and is_module_path(token, "."):
            return token.replace(".", "/")
    return None


def pair_imports(imports: list[ImportRow], scanned: list[tuple[str, bool]]):
    next_index = 0
    for spec, guarded in scanned:
        offset = next(
            (i for i, imp in enumerate(imports[next_index:]) if imp.specifier == spec),
            None,
        )
        if offset is None:
            continue
        next_index += offset
        yield imports[next_index], guarded
        next_index += 1


def missing_parent_declared(
    modules: dict[str, dict[str, FileRow]], spec: str, separator: str
) -> bool:
    if separator not in spec:
        return False
    parent = spec.rsplit(separator, 1)[0]
    return separator in parent and parent in modules


def is_generated_module(spec: str) -> bool:
    return spec.rsplit("/", 1)[-1].startswith("Paths_")


def manifest_owns(
    cache: dict[Path, set[str] | None], root: Path | None, source: FileRow, spec: str
) -> bool | None:
    directory = source.physical.parent
    while True:
        if directory not in cache:
            cache[directory] = read_manifest_modules(directory)
        modules = cache[directory]
        if modules is not None:
            return spec.replace("/", ".") in modules
        if root is not None and directory == root:
            return None
        parent = directory.parent
        if parent == directory:
            return None
        directory = parent


MANIFEST_MODULE_FIELDS = {
    "exposed-modules",
    "other-modules",
    "reexported-modules",
    "signatures",
    "virtual-modules",
}


def read_manifest_modules(directory: Path) -> set[str] | None:
    try:
        entries = list(directory.iterdir())
    except OSError:
        return None
    paths = [
        entry
        for entry in entries
        if entry.name.endswith(".cabal") or entry.name == "package.yaml"
    ]
    if not paths:
        return None
    modules: set[str] = set()
    for path in paths:
        with contextlib.suppress(OSError, UnicodeError):
            collect_manifest_modules(path.read_text(encoding="utf-8"), modules)
    return modules


def collect_manifest_modules(text: str, output: set[str]) -> None:
    collecting = False
    for raw in text.splitlines():
        line = raw.split("--", 1)[0]
        trimmed = line.strip()
        if not trimmed:
            collecting = False
            continue
        if ":" in trimmed:
            field, rest = trimmed.split(":", 1)
            collecting = field.strip().lower() in MANIFEST_MODULE_FIELDS
            if collecting:
                add_module_names(rest, output)
            continue
        if collecting and line.startswith((" ", "\t")):
            add_module_names(trimmed, output)


def add_module_names(text: str, output: set[str]) -> None:
    output.update(
        token for token in text.replace(",", " ").split() if is_module_path(token, ".")
    )


def collect_names(root: Path) -> set[str]:
    names: set[str] = set()
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir():
                    if entry.name != ".git":
                        pending.append(entry)
                else:
                    names.add(entry.name)
            except OSError:
                continue
    return names


def repository_root(source: FileRow) -> Path:
    root = source.physical
    for _ in Path(source.relative).parts:
        root = root.parent
    return root


def imports_of(
    input: FactInput, source: FileRow, include_type_only: bool = False
) -> list[ImportRow]:
    return [
        imp
        for imp in input.imports
        if imp.file_id == source.id and (include_type_only or not imp.type_only)
    ]
