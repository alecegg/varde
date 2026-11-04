"""Source file discovery for the code index."""

from __future__ import annotations

import contextlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from varde_code.git import run_git_bytes
from varde_code.model import Diagnostic

UNKNOWN_METADATA = -1
_FNV_OFFSET_BASIS = 14_695_981_039_346_656_037
_FNV_PRIME = 1_099_511_628_211
_IGNORED_DIRECTORY_NAMES = frozenset(
    {
        "__pycache__",
        "node_modules",
    }
)
_ROOT_ONLY_IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".cache",
        ".mypy_cache",
        ".next",
        ".nox",
        ".nuxt",
        ".pytest_cache",
        ".ruff_cache",
        ".scratch",
        ".tox",
        ".uv-cache",
        ".venv",
        "bower_components",
        "build",
        "dist",
        "target",
        "venv",
    }
)


@dataclass(frozen=True)
class SourceFile:
    path: str
    mtime: int
    size: int
    content_hash: str | None = None


@dataclass(frozen=True)
class SourceListing:
    files: list[SourceFile]
    diagnostics: list[Diagnostic]


def is_vcs_internal(path: Path) -> bool:
    """Return whether a path is Git's internal directory or gitlink file."""
    return path.name == ".git"


def list_source_files(path: str | Path) -> list[SourceFile]:
    return list_source_listing(path).files


def indexed_source_files(files: list[SourceFile]) -> list[SourceFile]:
    """Return every walked file represented in the code index."""
    return files


def list_source_listing(path: str | Path) -> SourceListing:
    root = Path(path)
    if not root.exists():
        raise FileNotFoundError(f"path does not exist: {root}")
    if root.is_file():
        return SourceListing([_source_file(root, hash_unknown=True)], [])

    listed = run_git_bytes(["ls-files", "-z", "-co", "--exclude-standard"], root)
    if listed is not None:
        return _git_listing(root, os.fsdecode(listed))
    return _walk_listing(root)


def _git_listing(root: Path, listed: str) -> SourceListing:
    """List tracked and untracked-unignored regular files from `git ls-files`."""
    pruned: dict[tuple[str, ...], bool] = {(): False}

    def directory_pruned(parts: tuple[str, ...]) -> bool:
        if parts not in pruned:
            directory = root.joinpath(*parts)
            pruned[parts] = (
                directory_pruned(parts[:-1])
                or _is_ignored_directory(directory, root)
                or _is_linked_worktree_dir(directory)
            )
        return pruned[parts]

    files: list[SourceFile] = []
    diagnostics: list[Diagnostic] = []
    for relative in set(listed.split("\0")):
        if not relative or relative.endswith("/"):
            continue
        parts = tuple(relative.split("/"))
        path = root.joinpath(*parts)
        if is_vcs_internal(path) or directory_pruned(parts[:-1]):
            continue
        try:
            is_regular = stat.S_ISREG(os.lstat(path).st_mode)
        except FileNotFoundError:
            continue
        except OSError as error:
            diagnostics.append(_walk_diagnostic(path, error))
            continue
        if is_regular:
            files.append(_source_file(path))
    files.sort(key=lambda file: file.path)
    diagnostics.sort(key=lambda item: (item.path, item.message))
    return SourceListing(files, diagnostics)


def _is_linked_worktree_dir(directory: Path) -> bool:
    git_file = directory / ".git"
    if not git_file.is_file() or git_file.is_symlink():
        return False
    try:
        text = git_file.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return text.startswith("gitdir:") and "/worktrees/" in text


def _walk_listing(root: Path) -> SourceListing:
    """Walk the directory tree when Git cannot list the root."""
    files: list[SourceFile] = []
    diagnostics: list[Diagnostic] = []

    def walk(directory: Path) -> None:
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as error:
            diagnostics.append(_walk_diagnostic(directory, error))
            return
        if directory != root and _is_linked_worktree(entries):
            return
        for entry in entries:
            entry_path = Path(entry.path)
            try:
                if entry.is_dir(follow_symlinks=False):
                    if not _is_ignored_directory(entry_path, root):
                        walk(entry_path)
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                if is_vcs_internal(entry_path):
                    continue
                files.append(_source_file(entry_path))
            except OSError as error:
                diagnostics.append(_walk_diagnostic(entry_path, error))

    walk(root)
    files.sort(key=lambda file: file.path)
    diagnostics.sort(key=lambda item: (item.path, item.message))
    deduplicated = list(dict.fromkeys(diagnostics))
    return SourceListing(files, deduplicated)


def _is_ignored_directory(path: Path, root: Path) -> bool:
    """Return whether discovery should prune a generated or internal directory."""
    relative_parts = path.relative_to(root).parts
    if path.name in _IGNORED_DIRECTORY_NAMES or is_vcs_internal(path):
        return True
    return (
        _is_root_generated_directory(relative_parts)
        or _is_varde_worktrees_dir(relative_parts)
        or _is_varde_scratch_dir(relative_parts)
        or _is_repo_map_dir(relative_parts)
    )


def _is_root_generated_directory(relative_parts: tuple[str, ...]) -> bool:
    return (
        len(relative_parts) == 1
        and relative_parts[0] in _ROOT_ONLY_IGNORED_DIRECTORY_NAMES
    )


def _is_varde_worktrees_dir(relative_parts: tuple[str, ...]) -> bool:
    return relative_parts[:2] == (".varde", "worktrees")


def _is_varde_scratch_dir(relative_parts: tuple[str, ...]) -> bool:
    return relative_parts[:2] == (".varde", ".scratch")


def _is_repo_map_dir(relative_parts: tuple[str, ...]) -> bool:
    """Generated packs must not make the index stale when they are written."""
    return relative_parts == ("docs", "repo-map")


def _is_linked_worktree(entries: list[os.DirEntry[str]]) -> bool:
    """Return whether a directory's .git file points into Git worktrees."""
    for entry in entries:
        if entry.name != ".git" or not entry.is_file(follow_symlinks=False):
            continue
        try:
            git_file = Path(entry.path).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if git_file.startswith("gitdir:") and "/worktrees/" in git_file:
            return True
    return False


class DefaultFileWalker:
    """Default implementation of the core file walker seam."""

    def list_source_listing(self, root: Path) -> list[Path]:
        return [Path(file.path) for file in list_source_listing(root).files]

    def is_vcs_internal(self, path: Path) -> bool:
        return is_vcs_internal(path)


def _source_file(path: Path, *, hash_unknown: bool = False) -> SourceFile:
    try:
        metadata = path.stat()
        mtime = _mtime_ns(metadata)
        size = _i64(metadata.st_size)
    except OSError:
        mtime = size = UNKNOWN_METADATA
    content_hash = None
    if hash_unknown and mtime == size == UNKNOWN_METADATA:
        with contextlib.suppress(OSError):
            content_hash = _content_hash(path.read_bytes())
    return SourceFile(str(path), mtime, size, content_hash)


def _mtime_ns(metadata: os.stat_result) -> int:
    try:
        return _i64(metadata.st_mtime_ns)
    except AttributeError, OverflowError:
        return UNKNOWN_METADATA


def _i64(value: int) -> int:
    return value if -(2**63) <= value < 2**63 else UNKNOWN_METADATA


def _content_hash(contents: bytes) -> str:
    value = _FNV_OFFSET_BASIS
    for byte in contents:
        value = ((value ^ byte) * _FNV_PRIME) & 0xFFFFFFFFFFFFFFFF
    return f"{value:016x}"


def _walk_diagnostic(path: Path, error: OSError) -> Diagnostic:
    return Diagnostic(
        file_id=None,
        path=str(path),
        message=f"directory traversal failed — skipped: {error}",
        severity="error",
    )
