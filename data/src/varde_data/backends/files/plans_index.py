"""Thread-safe incremental index for file-backed plans."""

from __future__ import annotations

import hashlib
import os
import struct
import threading
import time
from collections.abc import Callable
from copy import deepcopy
from pathlib import Path

from varde_data.version import Version

StatKey = tuple[int, int, int, int]
Entry = tuple[Path, bool, bool, bool]
_ARTIFACT_NAMES = {"plan.md", "task.md", "review.md"}


def _key(info: os.stat_result) -> StatKey:
    return (info.st_mtime_ns, info.st_ctime_ns, info.st_size, info.st_ino)


class PlansIndex:
    """Cache discovered directories, reader artifacts, and parsed file data."""

    def __init__(self, root: Path) -> None:
        self.root = os.fspath(root)
        self.lock = threading.RLock()
        self._directories: dict[str, tuple[int, int]] = {}
        self._directory_ids: dict[str, tuple[int, int]] = {}
        self._children: dict[str, tuple[tuple[str, bool, bool, bool], ...]] = {}
        self._path_children: dict[str, tuple[Entry, ...]] = {}
        self._artifacts: dict[str, None] = {}
        self._bytes: dict[str, tuple[StatKey, bytes, int]] = {}
        self._fields: dict[
            str, tuple[StatKey, Callable[[bytes], object], bool, dict[str, object], int]
        ] = {}

    def paths(self, directory: Path) -> tuple[Entry, ...] | None:
        """Return sorted children for existing discovery behavior."""
        with self.lock:
            return self._paths(directory)

    def _paths(self, directory: Path) -> tuple[Entry, ...] | None:
        name = os.fspath(directory)
        try:
            info = os.stat(name)
        except OSError:
            _forget_tree(self, name)
            return None
        identity = (info.st_dev, info.st_ino)
        cached_identity = self._directory_ids.get(name)
        self._directory_ids[name] = identity
        cached = self._directories.get(name)
        if (
            cached is None
            or cached[0] != info.st_mtime_ns
            or cached_identity != identity
            or _is_racy(cached[0], cached[1])
        ):
            self._scan(name, info.st_mtime_ns)
        return self._path_children.get(name)

    def read(self, path: Path) -> bytes:
        """Read a file once per stat key, rereading near the racy window."""
        with self.lock:
            return self._read(path)

    def directory_id(self, directory: Path) -> tuple[int, int] | None:
        """Return the identity from the most recent directory stat."""
        with self.lock:
            return self._directory_ids.get(os.fspath(directory))

    def _read(self, path: Path) -> bytes:
        raw, _, _ = self._read_snapshot(path)
        return raw

    def _read_snapshot(self, path: Path) -> tuple[bytes, StatKey | None, int]:
        name = os.fspath(path)
        key = _key(os.stat(name))
        cached = self._bytes.get(name)
        if cached is not None and cached[0] == key and not _is_racy(key[0], cached[2]):
            return cached[1], key, cached[2]
        raw = path.read_bytes()
        after = _key(os.stat(name))
        if after != key:
            key = after
            raw = path.read_bytes()
            after = _key(os.stat(name))
        loaded_ns = time.time_ns()
        if after == key:
            self._bytes[name] = (key, raw, loaded_ns)
            stable_key = key
        else:
            self._bytes.pop(name, None)
            self._fields.pop(name, None)
            stable_key = None
        return raw, stable_key, loaded_ns

    def fields(
        self,
        path: Path,
        parser: Callable[[bytes], tuple[dict[str, object], object]],
        *,
        normalize_newlines: bool = False,
    ) -> tuple[bytes, dict[str, object]]:
        """Return parsed frontmatter cached by the current file stat key."""
        with self.lock:
            return self._fields_for(path, parser, normalize_newlines)

    def _fields_for(
        self,
        path: Path,
        parser: Callable[[bytes], tuple[dict[str, object], object]],
        normalize_newlines: bool,
    ) -> tuple[bytes, dict[str, object]]:
        raw, read_key, loaded_ns = self._read_snapshot(path)
        name = os.fspath(path)
        cached = self._fields.get(name)
        if (
            cached is not None
            and read_key is not None
            and cached[0] == read_key
            and cached[1] is parser
            and cached[2] == normalize_newlines
            and not _is_racy(read_key[0], cached[4])
        ):
            return raw, deepcopy(cached[3])
        source = raw.replace(b"\r\n", b"\n") if normalize_newlines else raw
        fields, _ = parser(source)
        try:
            parsed_key = _key(os.stat(name))
        except OSError:
            self._fields.pop(name, None)
        else:
            if (
                read_key is not None
                and parsed_key == read_key
                and not _is_racy(read_key[0], loaded_ns)
            ):
                self._fields[name] = (
                    read_key,
                    parser,
                    normalize_newlines,
                    deepcopy(fields),
                    loaded_ns,
                )
            else:
                self._fields.pop(name, None)
        return raw, fields

    def version(self) -> Version:
        """Version only directories and files that can affect reader results."""
        with self.lock:
            return self._version()

    def _version(self) -> Version:
        if self.root not in self._directories:
            self._scan_tree(self.root)

        _rescan_changed_directories(self, _changed_directories(self))

        digest = hashlib.blake2b(digest_size=16)
        mtimes: list[int] = []
        _fold_directory_keys(self, digest, mtimes)
        _fold_artifact_keys(self, digest, mtimes)
        return Version(digest.digest(), tuple(mtimes))

    def _scan_tree(self, start: str) -> None:
        _scan_directories(self, [start], set())

    def _scan_new_directories(self, start: str) -> None:
        pending = [
            child
            for child, is_dir, _, _ in self._children.get(start, ())
            if is_dir and self._directories.get(child) == (-1, 0)
        ]
        _scan_directories(self, pending, set(self._directory_ids.values()))

    def _scan(
        self, directory: str, mtime: int
    ) -> tuple[tuple[str, bool, bool, bool], ...]:
        old_children = self._children.get(directory, ())
        try:
            with os.scandir(directory) as scanner:
                children = tuple(
                    (
                        os.path.join(directory, entry.name),
                        entry.is_dir(),
                        entry.is_file(),
                        entry.is_symlink(),
                    )
                    for entry in scanner
                )
        except OSError:
            _forget_tree(self, directory)
            return ()

        new_names = {child for child, _, _, _ in children}
        for child, was_dir, _, _ in old_children:
            if child not in new_names:
                if was_dir:
                    _forget_tree(self, child)
                else:
                    self._forget(child)
        for child, is_dir, is_file, _ in children:
            if is_dir:
                self._artifacts.pop(child, None)
                self._directories.setdefault(child, (-1, 0))
            elif is_file and _is_artifact(directory, child):
                self._artifacts.setdefault(child, None)
            else:
                self._artifacts.pop(child, None)
        self._children[directory] = children
        self._path_children[directory] = tuple(
            (Path(child), is_dir, is_file, is_symlink)
            for child, is_dir, is_file, is_symlink in sorted(children)
        )
        self._directories[directory] = (mtime, time.time_ns())
        return children

    def _forget(self, name: str) -> None:
        self._directories.pop(name, None)
        self._directory_ids.pop(name, None)
        self._children.pop(name, None)
        self._path_children.pop(name, None)
        self._artifacts.pop(name, None)
        self._bytes.pop(name, None)
        self._fields.pop(name, None)


def _is_artifact(directory: str, child: str) -> bool:
    name = os.path.basename(child)
    if name in _ARTIFACT_NAMES:
        return True
    return os.path.basename(directory) == "tasks" and name.endswith(".md")


def _scan_directories(
    index: PlansIndex, pending: list[str], visited: set[tuple[int, int]]
) -> None:
    while pending:
        directory = pending.pop()
        try:
            info = os.stat(directory)
        except OSError:
            _forget_tree(index, directory)
            continue
        identity = (info.st_dev, info.st_ino)
        if identity in visited:
            _forget_tree(index, directory)
            continue
        visited.add(identity)
        index._directory_ids[directory] = identity
        children = index._scan(directory, info.st_mtime_ns)
        pending.extend(child for child, is_dir, _, _ in children if is_dir)


def _changed_directories(index: PlansIndex) -> list[tuple[str, int | None]]:
    changed = []
    for directory in index._directories:
        info = _directory_stat(directory)
        mtime = info.st_mtime_ns if info is not None else None
        cached_mtime, loaded_ns = index._directories[directory]
        identity = (info.st_dev, info.st_ino) if info is not None else None
        if (
            mtime is None
            or cached_mtime != mtime
            or index._directory_ids.get(directory) != identity
            or _is_racy(mtime, loaded_ns)
        ):
            changed.append((directory, mtime))
    return changed


def _rescan_changed_directories(
    index: PlansIndex, changed: list[tuple[str, int | None]]
) -> None:
    for directory, mtime in changed:
        if mtime is None:
            _forget_tree(index, directory)
            continue
        index._scan(directory, mtime)
        index._scan_new_directories(directory)


def _directory_stat(directory: str) -> os.stat_result | None:
    try:
        return os.stat(directory)
    except OSError:
        return None


def _fold_directory_keys(index: PlansIndex, digest, mtimes: list[int]) -> None:
    for directory, (mtime, _) in index._directories.items():
        digest.update(b"d\0" + os.fsencode(directory))
        digest.update(struct.pack("!q", mtime))
        mtimes.append(mtime)


def _fold_artifact_keys(index: PlansIndex, digest, mtimes: list[int]) -> None:
    for artifact in index._artifacts:
        key = _artifact_stat_key(artifact)
        digest.update(b"f\0" + os.fsencode(artifact))
        if key is None:
            digest.update(b"missing")
            continue
        digest.update(struct.pack("!qqqq", *key))
        mtimes.append(key[0])


def _artifact_stat_key(artifact: str) -> StatKey | None:
    try:
        return _key(os.stat(artifact))
    except OSError:
        return None


def _forget_tree(index: PlansIndex, directory: str) -> None:
    prefix = directory.rstrip(os.sep) + os.sep
    caches = (
        index._directories,
        index._directory_ids,
        index._children,
        index._path_children,
        index._artifacts,
        index._bytes,
        index._fields,
    )
    names = {
        name
        for cache in caches
        for name in cache
        if name == directory or name.startswith(prefix)
    }
    for name in names:
        index._forget(name)


def _is_racy(mtime_ns: int, loaded_ns: int) -> bool:
    return loaded_ns - mtime_ns <= 2_000_000_000
