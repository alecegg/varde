"""Python import dependency facts."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from ...parse import language_for_path, parse_source
from .types import (
    Fact,
    FactInput,
    FileRow,
    ImportRow,
    certified_fact,
    indexed_paths,
    missing_fact,
    physical_targets,
    resolve_relative_path,
)


def facts(input: FactInput) -> list[Fact]:
    by_id = {file.id: file for file in input.files}
    indexed = indexed_paths(input.files)
    roots = package_roots(input.files)
    imports_by_file: dict[int, list[ImportRow]] = {}
    for imp in input.imports:
        imports_by_file.setdefault(imp.file_id, []).append(imp)
    result: list[Fact] = []
    for source in input.files:
        if source.is_test or source.is_tooling or not is_python(source):
            continue
        imports = imports_by_file.get(source.id, [])
        if not imports:
            continue
        try:
            text = source.physical.read_text(encoding="utf-8")
        except OSError, UnicodeError:
            continue
        root = repository_root(source)
        for imp, record in pair_imports(imports, scan_imports(text)):
            if imp.type_only or record.guarded:
                continue
            fact = python_fact(
                root, by_id, indexed, roots, source, imp, record.attribute_form
            )
            if fact is not None:
                result.append(fact)
    return result


def is_python(file: FileRow) -> bool:
    return language_for_path(file.path) == "python"


def repository_root(source: FileRow) -> Path:
    root = source.physical
    for _ in Path(source.relative).parts:
        root = root.parent
    return root


def package_roots(files: list[FileRow] | tuple[FileRow, ...]) -> dict[str, list[str]]:
    roots: dict[str, list[str]] = {}
    for file in files:
        path = Path(file.relative)
        if path.name != "__init__.py" or path.parent == Path("."):
            continue
        directory = path.parent.as_posix()
        grandparent = path.parent.parent.as_posix()
        if grandparent == ".":
            grandparent = ""
        if not is_source_root(grandparent):
            continue
        entries = roots.setdefault(path.parent.name, [])
        if directory not in entries:
            entries.append(directory)
    return roots


def is_source_root(directory: str) -> bool:
    return directory in ("", "src") or directory.endswith("/src")


def module_candidates(base: str) -> list[str]:
    return [f"{base}.py", f"{base}/__init__.py"]


def python_fact(
    root: Path,
    by_id: dict[int, FileRow],
    indexed: dict[str, list[int]],
    roots: dict[str, list[str]],
    source: FileRow,
    imp: ImportRow,
    attribute_form: bool,
) -> Fact | None:
    spec = imp.specifier
    if spec.startswith(("./", "../")):
        if not source_is_package(source, indexed):
            return None
        base = resolve_relative_path(source.relative, spec)
        if base is None:
            return None
        return relative_fact(root, by_id, indexed, source, imp, base, attribute_form)
    if not is_module_path(spec):
        return None
    first, _, rest = spec.partition("/")
    package_dirs = roots.get(first)
    if package_dirs is None or len(package_dirs) != 1:
        return None
    base = f"{package_dirs[0]}/{rest}" if rest else package_dirs[0]
    return certified_target(root, by_id, indexed, source, imp, base)


def relative_fact(
    root: Path,
    by_id: dict[int, FileRow],
    indexed: dict[str, list[int]],
    source: FileRow,
    imp: ImportRow,
    base: str,
    attribute_form: bool,
) -> Fact | None:
    targets = physical_targets(root, module_candidates(base))
    if len(targets.paths) == 1:
        ids = indexed.get(targets.paths[0][0], [])
        return certified_fact(by_id, source, imp, ids[0]) if len(ids) == 1 else None
    if targets.paths or targets.existing_path:
        return None
    if attribute_form or has_sibling_with_stem(root, base):
        return None
    return missing_fact(source, imp)


def certified_target(
    root: Path,
    by_id: dict[int, FileRow],
    indexed: dict[str, list[int]],
    source: FileRow,
    imp: ImportRow,
    base: str,
) -> Fact | None:
    targets = physical_targets(root, module_candidates(base))
    if len(targets.paths) != 1:
        return None
    ids = indexed.get(targets.paths[0][0], [])
    return certified_fact(by_id, source, imp, ids[0]) if len(ids) == 1 else None


def source_is_package(source: FileRow, indexed: dict[str, list[int]]) -> bool:
    parent = Path(source.relative).parent.as_posix()
    init = "__init__.py" if parent == "." else f"{parent}/__init__.py"
    return init in indexed


def has_sibling_with_stem(root: Path, base: str) -> bool:
    path = Path(base)
    try:
        entries = (root / path.parent).iterdir()
    except OSError:
        return False
    return any(item.stem == path.name for item in entries)


def is_module_path(spec: str) -> bool:
    return (
        bool(spec)
        and not spec.startswith("/")
        and all(
            segment
            and (segment[0].isascii() and (segment[0].isalpha() or segment[0] == "_"))
            and all(
                char.isascii() and (char.isalnum() or char == "_") for char in segment
            )
            for segment in spec.split("/")
        )
    )


class PyImport:
    def __init__(self, spec: str, guarded: bool, attribute_form: bool):
        self.spec = spec
        self.guarded = guarded
        self.attribute_form = attribute_form


def walk(node) -> Iterator:
    yield node
    for child in node.children:
        yield from walk(child)


def field(node, name: str):
    return node.child_by_field_name(name)


def dotted_path(node) -> str | None:
    if node.type == "aliased_import":
        node = field(node, "name")
        if node is None:
            return None
    return node.text.decode("utf-8").replace(".", "/")


def relative_import_path(node) -> str:
    children = list(node.children)
    prefix = next((child for child in children if child.type == "import_prefix"), None)
    dots = prefix.text.decode("utf-8").count(".") if prefix else 0
    module = next((child for child in children if child.type == "dotted_name"), None)
    name = module.text.decode("utf-8").replace(".", "/") if module else ""
    return f"./{'../' * max(0, dots - 1)}{name}" if dots else name


def import_module(node) -> str:
    return (
        relative_import_path(node)
        if node.type == "relative_import"
        else (dotted_path(node) or "")
    )


def is_guarded(node) -> bool:
    ancestor = node.parent
    while ancestor is not None:
        if ancestor.type == "if_statement":
            condition = field(ancestor, "condition")
            if condition and b"TYPE_CHECKING" in condition.text:
                return True
        if ancestor.type == "try_statement":
            for child in ancestor.children:
                if child.type == "except_clause" and except_catches_import_error(
                    child.text.decode("utf-8")
                ):
                    return True
        ancestor = ancestor.parent
    return False


def except_catches_import_error(text: str) -> bool:
    after = text.split("except", 1)[-1].strip().rstrip(":").strip()
    return not after or any(
        name in after
        for name in ("ImportError", "ModuleNotFoundError", "Exception", "BaseException")
    )


def scan_imports(text: str) -> list[PyImport]:
    root = parse_source("python", text).root
    output: list[PyImport] = []
    for node in walk(root):
        if node.type == "import_statement":
            guarded = is_guarded(node)
            for name in (
                child
                for child in node.children
                if child.type in {"dotted_name", "aliased_import"}
            ):
                spec = dotted_path(name)
                if spec is not None:
                    output.append(PyImport(spec, guarded, False))
        elif node.type == "import_from_statement":
            module = field(node, "module_name")
            if module is None:
                continue
            spec = import_module(module)
            attribute_form = not spec or spec.endswith("/")
            if attribute_form:
                names = [
                    child
                    for child in node.children
                    if child.type in {"dotted_name", "aliased_import"}
                ]
                if names:
                    spec += dotted_path(names[0]) or ""
            if spec:
                output.append(PyImport(spec, is_guarded(node), attribute_form))
    return output


def pair_imports(imports: list[ImportRow], scanned: list[PyImport]):
    pairs = []
    next_index = 0
    for record in scanned:
        offset = next(
            (
                i
                for i, imp in enumerate(imports[next_index:])
                if imp.specifier == record.spec
            ),
            None,
        )
        if offset is not None:
            next_index += offset
            pairs.append((imports[next_index], record))
            next_index += 1
    return pairs
