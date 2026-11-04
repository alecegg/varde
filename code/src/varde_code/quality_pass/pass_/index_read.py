"""Read-only view of the fast index: freshness, file list and path predicates.

The pass reads only the ``files`` table (paths and the generated path-class
columns) through a ``mode=ro`` connection. It never reads the index content
hash, ``function_metrics`` or ``resolved_edges``, and it never writes the index.
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from varde_code.git import run_git_bytes
from varde_code.index.paths import repo_db_path
from varde_code.index.slice import check_fresh
from varde_code.parse import language_for_path
from varde_code.query.modes import index_service

RELEASE_LANGUAGES = frozenset(
    {
        "c",
        "cpp",
        "csharp",
        "go",
        "java",
        "javascript",
        "python",
        "rust",
        "tsx",
        "typescript",
    }
)
# Root directories the fast index prunes; their source is still scored here so
# moving debt under them cannot hide it from the gate.
UNINDEXED_ROOT_DIRS = ("build", "dist")
_PRUNED_NAMES = frozenset({"__pycache__", "node_modules", ".git"})
_PACKAGE_MARKERS = {
    "python": ("__init__.py",),
    "typescript": ("package.json",),
    "javascript": ("package.json",),
    "tsx": ("package.json",),
    "java": ("pom.xml", "build.gradle", "build.gradle.kts"),
    "go": ("go.mod",),
    "rust": ("Cargo.toml",),
    "csharp": (".csproj", ".sln"),
    "cpp": ("CMakeLists.txt",),
    "c": ("CMakeLists.txt",),
}


class QualityPassError(Exception):
    """A stable refusal or failure reported by the quality pass."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class IndexedFile:
    """One release-language file read from the fast index."""

    path: str
    language: str
    absolute: Path
    is_test_path: bool
    is_tooling_path: bool


@dataclass(frozen=True)
class IndexView:
    """The file list and per-language package directories of a fresh index."""

    db_path: Path
    files: tuple[IndexedFile, ...]
    package_dirs: dict[str, tuple[str, ...]]


def resolve_fresh_index(root: str | Path) -> Path:
    """Return the fast index path, refusing when it is missing or stale.

    A registered index service is asked to freshen first (the same call scan
    makes); the result is verified with ``check_fresh`` either way, so a stale
    index is always a refusal rather than a silent full scan.
    """
    root = Path(root)
    service = index_service()
    if service is None:
        db_path = repo_db_path(root)
    else:
        try:
            db_path = Path(service.repo_db_path(root))
            service.ensure_fresh(root)
        except Exception as exc:
            raise QualityPassError("index_stale", str(exc)) from exc
    if not db_path.is_file():
        raise QualityPassError("index_missing", f"index missing at {db_path}")
    if not check_fresh(db_path, root):
        raise QualityPassError("index_stale", f"index is not fresh for {root}")
    return db_path


def read_index(db_path: str | Path, root: str | Path) -> IndexView:
    """Read the file list, path predicates and package markers, read-only."""
    root_path = Path(root)
    canonical = root_path.resolve()
    connection = sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT path, is_test_path, is_tooling_path FROM files ORDER BY path"
        ).fetchall()
    finally:
        connection.close()
    paths = [(str(row[0]), bool(row[1]), bool(row[2])) for row in rows]
    paths.extend((value, False, False) for value in unindexed_source_paths(root_path))
    files = []
    for value, is_test, is_tooling in paths:
        relative = _relative_path(value, canonical)
        absolute = root_path / relative
        language = language_for_path(absolute)
        if language not in RELEASE_LANGUAGES:
            continue
        files.append(
            IndexedFile(
                path=relative,
                language=language,
                absolute=absolute,
                is_test_path=is_test,
                is_tooling_path=is_tooling,
            )
        )
    return IndexView(
        db_path=Path(db_path),
        files=tuple(sorted(files, key=lambda item: item.path)),
        package_dirs=_package_dirs(paths, canonical),
    )


def unindexed_source_paths(root: Path) -> list[str]:
    """Root-relative files under the index-pruned root dirs, git-ignore aware."""
    existing = [name for name in UNINDEXED_ROOT_DIRS if (root / name).is_dir()]
    if not existing:
        return []
    listed = run_git_bytes(
        ["ls-files", "-z", "-co", "--exclude-standard", "--", *existing], root
    )
    if listed is not None:
        names = [item for item in os.fsdecode(listed).split("\0") if item]
    else:
        names = [path for name in existing for path in _walk_relative(root, name)]
    return sorted(
        name
        for name in set(names)
        if not _PRUNED_NAMES.intersection(PurePosixPath(name).parts)
        and (root / name).is_file()
    )


def _walk_relative(root: Path, name: str) -> list[str]:
    found = []
    for directory, subdirs, filenames in os.walk(root / name):
        subdirs[:] = [d for d in subdirs if d not in _PRUNED_NAMES]
        base = Path(directory).relative_to(root)
        found.extend((base / filename).as_posix() for filename in filenames)
    return found


def module_package_dirs(view: IndexView, language: str) -> tuple[str, ...]:
    """Return package-marker directories for one language."""
    return view.package_dirs.get(language, ())


def _relative_path(value: str, canonical_root: Path) -> str:
    path = Path(value)
    try:
        return path.resolve().relative_to(canonical_root).as_posix()
    except ValueError:
        try:
            return path.relative_to(canonical_root).as_posix()
        except ValueError:
            return path.as_posix()


def _package_dirs(
    paths: list[tuple[str, bool, bool]], canonical_root: Path
) -> dict[str, tuple[str, ...]]:
    """Return repo-relative package-marker directories per language."""
    found: dict[str, set[str]] = {}
    for value, _is_test, _is_tooling in paths:
        posix = PurePosixPath(value.replace("\\", "/"))
        for language, markers in _PACKAGE_MARKERS.items():
            if any(_is_marker(posix.name, marker) for marker in markers):
                parent = _relative_path(str(posix.parent), canonical_root)
                found.setdefault(language, set()).add(parent)
    return {language: tuple(sorted(dirs)) for language, dirs in found.items()}


def _is_marker(name: str, marker: str) -> bool:
    return name.endswith(marker) if marker.startswith(".") else name == marker
