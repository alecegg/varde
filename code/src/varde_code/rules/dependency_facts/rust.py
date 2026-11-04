"""Rust module dependency facts."""

from __future__ import annotations

from pathlib import Path

from ...model import EntityKind, span_of
from ...parse import language_for_path, parse_source
from ...seams import ExtractionProvider
from .types import (
    IMPORT_KIND,
    Fact,
    FactInput,
    FileRow,
    ImportRow,
    metadata_if_exists,
    missing_fact,
)
from .types import (
    EdgeRow as EdgeRow,
)


def facts(input: FactInput, provider: ExtractionProvider) -> list[Fact]:
    by_id = {file.id: file for file in input.files}
    imports_by_id = {imp.id: imp for imp in input.imports}
    guarded = cfg_guarded_imports(input, provider)
    repo_root = repository_root(input.files)
    output = certified_facts(input, by_id, imports_by_id, guarded, repo_root)
    output.extend(missing_facts(input, by_id, guarded))
    return output


def repository_root(files: list[FileRow] | tuple[FileRow, ...]) -> Path | None:
    if not files:
        return None
    file = files[0]
    root = file.physical
    for _ in Path(file.relative).parts:
        root = root.parent
    return root


def certified_facts(
    input: FactInput,
    by_id: dict[int, FileRow],
    imports_by_id: dict[int, ImportRow],
    guarded: dict[int, set[str]],
    repo_root: Path | None,
) -> list[Fact]:
    units: dict[Path, str] = {}
    facts: list[Fact] = []
    for edge in input.edges:
        if not edge.resolved:
            continue
        source = by_id.get(edge.from_file_id)
        if source is None or source.is_test or source.is_tooling or not is_rust(source):
            continue
        imp = (
            imports_by_id.get(edge.from_entity_id)
            if edge.from_entity_id is not None
            else None
        )
        if (
            imp is None
            or imp.type_only
            or is_guarded(guarded, source.id, imp.specifier)
        ):
            continue
        if is_mod_declaration(imp.specifier) or edge.to_file_id is None:
            continue
        target = by_id.get(edge.to_file_id) if edge.to_file_id is not None else None
        if (
            target is None
            or not is_rust(target)
            or not physical_is_file(target.physical)
        ):
            continue
        if package_unit(source, repo_root, units) == package_unit(
            target, repo_root, units
        ):
            continue
        facts.append(
            Fact(
                source.id,
                source.relative,
                target.id,
                target.relative,
                IMPORT_KIND,
                "certified",
                imp.id,
                imp.specifier,
            )
        )
    return facts


def package_unit(
    source: FileRow, repo_root: Path | None, cache: dict[Path, str]
) -> str:
    parent = Path(source.relative).parent
    if parent in cache:
        return cache[parent]
    unit = discover_package_unit(parent, repo_root)
    cache[parent] = unit
    return unit


def discover_package_unit(directory: Path, repo_root: Path | None) -> str:
    cursor = directory
    while True:
        if repo_root is not None and has_package_manifest(repo_root / cursor):
            return unit_path(cursor)
        parent = cursor.parent
        if parent == cursor:
            break
        cursor = parent
    return unit_path(directory)


def has_package_manifest(directory: Path) -> bool:
    try:
        lines = (directory / "Cargo.toml").read_text(encoding="utf-8").splitlines()
    except OSError, UnicodeError:
        return False
    return any(
        line.strip() == "[package]" or line.strip().startswith("[package.")
        for line in lines
    )


def unit_path(directory: Path) -> str:
    return "." if str(directory) == "." else directory.as_posix()


def missing_facts(
    input: FactInput, by_id: dict[int, FileRow], guarded: dict[int, set[str]]
) -> list[Fact]:
    output: list[Fact] = []
    resolved_imports = {
        edge.from_entity_id
        for edge in input.edges
        if edge.resolved and edge.from_entity_id is not None
    }
    for imp in input.imports:
        source = by_id.get(imp.file_id)
        if (
            source is None
            or source.is_test
            or source.is_tooling
            or not is_rust(source)
            or imp.type_only
        ):
            continue
        segments = mod_segments(imp.specifier)
        if segments is None or len(segments) > 1:
            continue
        if imp.id in resolved_imports:
            continue
        if is_guarded(guarded, source.id, imp.specifier):
            continue
        if module_candidate_exists(source, segments):
            continue
        output.append(missing_fact(source, imp))
    return output


def is_guarded(guarded: dict[int, set[str]], file_id: int, specifier: str) -> bool:
    return specifier in guarded.get(file_id, set())


def is_rust(file: FileRow) -> bool:
    return language_for_path(file.path) == "rust"


def physical_is_file(path: Path) -> bool:
    metadata = metadata_if_exists(path)
    return metadata is not None and path.is_file()


def module_candidate_exists(source: FileRow, segments: list[str]) -> bool:
    stem = Path(source.relative).stem
    parent = source.physical.parent
    bases = [parent]
    if stem:
        bases.append(parent / stem)
    if not segments:
        return True
    *parents, last = segments
    for base in bases:
        directory = base.joinpath(*parents)
        for candidate in (directory / f"{last}.rs", directory / last / "mod.rs"):
            if physical_is_file(candidate):
                return True
    return False


def mod_segments(specifier: str) -> list[str] | None:
    if not specifier.startswith("mod "):
        return None
    segments = [part.strip() for part in specifier[4:].split("::") if part.strip()]
    return segments or None


def is_mod_declaration(specifier: str) -> bool:
    return specifier.startswith(("mod ", "#[path"))


def cfg_guarded_imports(
    input: FactInput, provider: ExtractionProvider
) -> dict[int, set[str]]:
    imported = {imp.file_id for imp in input.imports}
    guarded: dict[int, set[str]] = {}
    for file in input.files:
        if (
            file.id not in imported
            or file.is_test
            or file.is_tooling
            or not is_rust(file)
        ):
            continue
        try:
            source = file.physical.read_text(encoding="utf-8")
        except OSError, UnicodeError:
            continue
        if "cfg" not in source:
            continue
        parsed = parse_source("rust", source)
        ranges = cfg_ranges(parsed.root)
        if not ranges:
            continue
        extracted = provider.extract(file.physical, source, "rust")
        specs = {
            entity.name
            for entity in extracted.entities
            if entity.kind == EntityKind.IMPORT
            and any(start <= entity.span.start_byte < end for start, end in ranges)
        }
        if specs:
            guarded[file.id] = specs
    return guarded


def cfg_ranges(root) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []

    def visit(node) -> None:
        if has_cfg_attribute(node):
            span = span_of(node)
            ranges.append((span.start_byte, span.end_byte))
            return
        for child in node.children:
            visit(child)

    visit(root)
    return ranges


def walk(node):
    yield node
    for child in node.children:
        yield from walk(child)


def has_cfg_attribute(node) -> bool:
    sibling = node.prev_sibling
    while sibling is not None:
        if sibling.type == "attribute_item":
            text = sibling.text.decode("utf-8")
            inner = attribute_inner(text)
            if inner is not None and (
                inner == "cfg" or inner.startswith(("cfg(", "cfg_attr("))
            ):
                return True
        elif sibling.type not in {"line_comment", "block_comment"}:
            return False
        sibling = sibling.prev_sibling
    return False


def attribute_inner(text: str) -> str | None:
    text = text.strip()
    return text[2:-1].strip() if text.startswith("#[") and text.endswith("]") else None
