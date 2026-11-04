"""Repository path identity and glob ownership helpers."""

from __future__ import annotations

import errno
import os
from pathlib import Path


def matches_declaration(declaration: str, path: str) -> bool:
    directory = declaration.endswith("/")
    if "*" not in declaration and not directory:
        return declaration == path
    parts, values = declaration.rstrip("/").split("/"), path.split("/")
    if directory:
        parts += ["**"]

    def match(i: int, j: int) -> bool:
        if i == len(parts):
            return j == len(values)
        if parts[i] == "**":
            return match(i + 1, j) or (j < len(values) and match(i, j + 1))
        return (
            j < len(values)
            and segment_matches(parts[i], values[j])
            and match(i + 1, j + 1)
        )

    return match(0, 0)


def paths_outside_scope(paths: list[str], scope: list[str]) -> list[str]:
    """Sorted paths that no scope entry matches."""
    return sorted(
        path for path in paths if not any(matches_declaration(e, path) for e in scope)
    )


def segment_matches(pattern: str, value: str) -> bool:
    states = {0}

    def close(states: set[int]) -> set[int]:
        result = set(states)
        while True:
            expanded = result | {
                i + 1 for i in result if i < len(pattern) and pattern[i] == "*"
            }
            if expanded == result:
                return result
            result = expanded

    states = close(states)
    for char in value:
        next_states = set()
        for index in states:
            if index < len(pattern):
                if pattern[index] == "*":
                    next_states.add(index)
                elif pattern[index] == char:
                    next_states.add(index + 1)
        states = close(next_states)
    return len(pattern) in close(states)


def segment_overlap(left: str, right: str) -> bool:
    alphabet = (set(left) | set(right)) - {"*"}
    alphabet.add("a")
    pending, seen = [(0, 0, False)], set()
    while pending:
        i, j, nonempty = pending.pop()
        if (i, j, nonempty) in seen:
            continue
        seen.add((i, j, nonempty))
        if i == len(left) and j == len(right) and nonempty:
            return True
        if i < len(left) and left[i] == "*":
            pending.append((i + 1, j, nonempty))
        if j < len(right) and right[j] == "*":
            pending.append((i, j + 1, nonempty))
        for char in alphabet:
            ni = (
                i
                if i < len(left) and left[i] == "*"
                else i + 1
                if i < len(left) and left[i] == char
                else None
            )
            nj = (
                j
                if j < len(right) and right[j] == "*"
                else j + 1
                if j < len(right) and right[j] == char
                else None
            )
            if ni is not None and nj is not None:
                pending.append((ni, nj, True))
    return False


def declarations_overlap(left: str, right: str) -> bool:
    def parts(value: str) -> list[str]:
        result = value.rstrip("/").split("/")
        if value.endswith("/"):
            result += ["*", "**"]
        return result

    a, b = parts(left), parts(right)
    pending, seen = [(0, 0, False)], set()
    while pending:
        i, j, nonempty = pending.pop()
        if (i, j, nonempty) in seen:
            continue
        seen.add((i, j, nonempty))
        if i == len(a) and j == len(b) and nonempty:
            return True
        if i < len(a) and a[i] == "**":
            pending.append((i + 1, j, nonempty))
        if j < len(b) and b[j] == "**":
            pending.append((i, j + 1, nonempty))
        if i < len(a) and j < len(b):
            if a[i] == "**" and b[j] == "**":
                pending.append((i, j, True))
            elif a[i] == "**" and segment_overlap("*", b[j]):
                pending.append((i, j + 1, True))
            elif b[j] == "**" and segment_overlap(a[i], "*"):
                pending.append((i + 1, j, True))
            elif segment_overlap(a[i], b[j]):
                pending.append((i + 1, j + 1, True))
    return False


def canonical_path(root: Path, path: str) -> str:
    root = root.resolve()
    resolved = Path("/") if os.path.isabs(path) else root
    pending = path.split("/")
    hops = 0
    while pending:
        part = pending.pop(0)
        if part in {"", "."}:
            continue
        if part == "..":
            resolved = resolved.parent
            continue
        candidate = resolved / part
        if candidate.is_symlink():
            hops += 1
            if hops > 40:
                raise OSError(errno.ELOOP, "too many levels of symbolic links", path)
            target = os.readlink(candidate)
            if os.path.isabs(target):
                resolved = Path("/")
            pending[:0] = target.split("/")
            continue
        resolved = candidate
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise ValueError(f"path escapes repository: {path}") from exc


def canonical_declaration(root: Path, declaration: str) -> str:
    if Path(declaration).is_absolute():
        raise ValueError(f"path escapes repository: {declaration}")
    directory = declaration.endswith("/")
    parts = declaration.rstrip("/").split("/")
    wildcard = next((i for i, part in enumerate(parts) if "*" in part), None)
    if wildcard is None:
        result = canonical_path(root, declaration)
        return result + "/" if directory and result else result
    if any(p in {".", ".."} for p in parts[wildcard:]):
        raise ValueError("glob declarations cannot contain `.` or `..` components")
    prefix = "/".join(parts[:wildcard])
    canonical = canonical_path(root, prefix + "/" if prefix else ".")
    if canonical == ".":
        canonical = ""
    result = "/".join(filter(None, [canonical, "/".join(parts[wildcard:])]))
    return result + ("/" if directory else "")


def _walk_paths(root: Path, prefix: str) -> list[str]:
    start = root / prefix if prefix else root
    if not start.is_dir() or ".git" in Path(prefix).parts:
        return []

    # Prune dependency trees at any depth unless the declaration names them.
    pruned_names = {".venv", "node_modules"} - set(Path(prefix).parts) | {".git"}

    paths = [prefix] if prefix else []
    for current, directories, files in os.walk(start):
        directories[:] = sorted(
            name for name in directories if name not in pruned_names
        )
        current_path = Path(current)
        paths.extend(
            (current_path / name).relative_to(root).as_posix()
            for name in [*directories, *files]
        )
    return paths


def matching_paths(root: Path, declaration: str) -> list[str]:
    canonical = canonical_declaration(root, declaration)
    if not any(c in canonical for c in "*"):
        target = root / canonical.rstrip("/")
        if target.exists():
            if canonical.endswith("/") and not target.is_dir():
                raise ValueError(f"not a directory: {canonical}")
            return [canonical]
        return []
    pattern = canonical.removeprefix("./")
    parts = pattern.rstrip("/").split("/")
    wildcard = next(i for i, part in enumerate(parts) if "*" in part)
    prefix = "/".join(parts[:wildcard])
    return sorted(
        path
        for path in _walk_paths(root, prefix)
        if ".git" not in Path(path).parts and matches_declaration(pattern, path)
    )
