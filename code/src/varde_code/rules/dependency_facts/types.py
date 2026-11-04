"""Shared records and path helpers for dependency fact builders."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

IMPORT_KIND = 1
TYPE_ONLY = "type_only"


@dataclass(frozen=True)
class FileRow:
    id: int
    path: str
    relative: str
    physical: Path
    is_test: bool = False
    is_tooling: bool = False


@dataclass(frozen=True)
class ImportRow:
    id: int
    file_id: int
    specifier: str
    type_only: bool = False


@dataclass(frozen=True)
class EdgeRow:
    from_file_id: int
    from_entity_id: int | None
    to_file_id: int | None
    resolved: bool


@dataclass(frozen=True)
class Fact:
    from_file_id: int
    from_unit: str
    to_file_id: int | None
    to_unit: str | None
    kind: int
    certainty: str
    source_entity_id: int
    specifier: str


@dataclass(frozen=True)
class FactInput:
    files: list[FileRow] | tuple[FileRow, ...]
    imports: list[ImportRow] | tuple[ImportRow, ...]
    edges: list[EdgeRow] | tuple[EdgeRow, ...]


def indexed_paths(files: list[FileRow] | tuple[FileRow, ...]) -> dict[str, list[int]]:
    indexed: dict[str, list[int]] = {}
    for file in files:
        indexed.setdefault(file.relative, []).append(file.id)
    return indexed


def certified_fact(
    by_id: dict[int, FileRow], source: FileRow, imp: ImportRow, target_id: int
) -> Fact | None:
    target = by_id.get(target_id)
    if target is None or target.is_test or target.is_tooling or target.id == source.id:
        return None
    if source.relative == target.relative:
        return None
    return Fact(
        source.id,
        source.relative,
        target.id,
        target.relative,
        IMPORT_KIND,
        "certified",
        imp.id,
        imp.specifier,
    )


def missing_fact(source: FileRow, imp: ImportRow) -> Fact:
    return Fact(
        source.id,
        source.relative,
        None,
        None,
        IMPORT_KIND,
        "missing",
        imp.id,
        imp.specifier,
    )


@dataclass(frozen=True)
class PhysicalTargets:
    paths: tuple[tuple[str, Path], ...]
    existing_path: bool


def physical_targets(root: Path, candidates: list[str]) -> PhysicalTargets:
    found: list[tuple[str, Path]] = []
    existing = False
    seen: set[str] = set()
    for candidate in candidates:
        path = root / candidate
        try:
            path.stat()
        except FileNotFoundError, NotADirectoryError:
            continue
        except OSError as exc:
            raise OSError(f"stat dependency target {path}: {exc}") from exc
        existing = True
        if path.is_file() and candidate not in seen:
            seen.add(candidate)
            found.append((candidate, path))
    return PhysicalTargets(tuple(found), existing)


def resolve_relative_path(source: str, specifier: str) -> str | None:
    if not specifier or Path(specifier).is_absolute():
        return None
    parts = list(Path(source).parent.parts)
    for part in Path(specifier).parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not parts:
                return None
            parts.pop()
        else:
            parts.append(part)
    return "/".join(parts) if parts else None


def metadata_if_exists(path: Path):
    try:
        return path.stat()
    except FileNotFoundError, NotADirectoryError:
        return None
    except OSError as exc:
        raise OSError(f"stat dependency target {path}: {exc}") from exc
