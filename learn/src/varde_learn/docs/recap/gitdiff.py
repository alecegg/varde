"""Read-only git diff between two refs, parsed into per-file changes."""

import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
_GIT = ("git", "-c", "core.quotepath=off", "-c", "diff.renames=true")
_DIFF_FLAGS = ("--no-color", "--no-ext-diff", "--no-textconv", "-M")


class GitError(Exception):
    pass


@dataclass
class FileChange:
    path: str
    old_path: str | None = None
    status: str = "M"  # A, M, D, R
    binary: bool = False
    added: list[list[int]] = field(default_factory=list)
    removed: list[list[int]] = field(default_factory=list)
    hunk_lines: list[str] = field(default_factory=list)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603 - fixed git argv; refs checked not to start with -
        [*_GIT, "-C", str(root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or f"git {args[0]} failed")
    return result.stdout


def repo_root(start: Path) -> Path:
    return Path(_git(start, "rev-parse", "--show-toplevel").strip())


def parse_name_status(text: str) -> list[FileChange]:
    """Parse `diff --name-status -z -M` output."""
    parts = text.split("\0")
    changes: list[FileChange] = []
    i = 0
    while i < len(parts) and parts[i]:
        code = parts[i][0]
        if code in "RC":
            changes.append(FileChange(parts[i + 2], old_path=parts[i + 1], status="R"))
            i += 3
        else:
            changes.append(
                FileChange(parts[i + 1], status=code if code in "AD" else "M")
            )
            i += 2
    return changes


def parse_binary_paths(text: str) -> set[str]:
    """Paths git reports as binary (`-\t-`) in `diff --numstat -z -M` output."""
    parts = text.split("\0")
    binary: set[str] = set()
    i = 0
    while i < len(parts) and parts[i]:
        head = parts[i].split("\t")
        is_binary = head[0] == "-" and head[1] == "-"
        renamed = not head[2]
        path = parts[i + 2] if renamed else head[2]
        if is_binary:
            binary.add(path)
        i += 3 if renamed else 1
    return binary


_C_ESCAPES = {"a": 7, "b": 8, "f": 12, "n": 10, "r": 13, "t": 9, "v": 11}
_C_ESCAPE = re.compile(r"\\([0-7]{3}|.)", re.DOTALL)


def _unquote_c(quoted: str) -> str:
    """Decode a git C-style quoted path (`"a/q\\"x"`, octal bytes) to text."""
    raw = bytearray()
    pos = 0
    body = quoted[1:-1]
    for match in _C_ESCAPE.finditer(body):
        raw += body[pos : match.start()].encode()
        code = match.group(1)
        if len(code) == 3:
            raw.append(int(code, 8))
        else:
            raw.append(_C_ESCAPES.get(code, ord(code)))
        pos = match.end()
    raw += body[pos:].encode()
    return raw.decode("utf-8", errors="replace")


def _patch_path(field: str) -> str:
    """Path from a `---`/`+++` line: git quotes odd names and tab-pads spaced ones."""
    if len(field) > 1 and field.startswith('"') and field.endswith('"'):
        return _unquote_c(field)
    return field.removesuffix("\t")


def _range(start: int, count: int) -> list[int] | None:
    return [start, start + count - 1] if count > 0 else None


def parse_patch(text: str) -> dict[str, FileChange]:
    """Parse a zero-context patch into changes keyed by new path (old for deletes)."""
    files: dict[str, FileChange] = {}
    current: FileChange | None = None
    old_name = new_name = None
    for line in text.splitlines():
        if line.startswith("diff --git "):
            current, old_name, new_name = None, None, None
        elif current is None and line.startswith("--- "):
            old_name = _patch_path(line[4:]).removeprefix("a/")
        elif current is None and line.startswith("+++ "):
            new_name = _patch_path(line[4:]).removeprefix("b/")
            deleted = new_name == "/dev/null"
            key = old_name if deleted else new_name
            current = files.setdefault(key or "", FileChange(key or ""))
        elif current is not None and (hunk := _HUNK.match(line)):
            a, b, c, d = hunk.groups()
            removed = _range(int(a), 1 if b is None else int(b))
            added = _range(int(c), 1 if d is None else int(d))
            if removed:
                current.removed.append(removed)
            if added:
                current.added.append(added)
            current.hunk_lines.append(line)
        elif current is not None and line[:1] in "+-":
            current.hunk_lines.append(line)
    return files


def _check_ref(root: Path, ref: str) -> None:
    """Refuse anything that is not a commit-ish (git would read it as a pathspec)."""
    if ref.startswith("-") or not ref:
        raise GitError(f"invalid ref '{ref}'")
    try:
        _git(
            root,
            "rev-parse",
            "--verify",
            "--quiet",
            "--end-of-options",
            f"{ref}^{{commit}}",
        )
    except GitError as error:
        raise GitError(f"not a valid git ref: '{ref}'") from error


def _warn_unmatched(patch: dict[str, FileChange], names: list[FileChange]) -> None:
    known = {n.path for n in names} | {n.old_path for n in names if n.old_path}
    for path in sorted(set(patch) - known):
        print(
            f"warning: no changed-file entry for patch path {path!r}", file=sys.stderr
        )


def changed_files(root: Path, base: str, head: str) -> list[FileChange]:
    _check_ref(root, base)
    _check_ref(root, head)
    refs = [base, head, "--"]
    names = parse_name_status(
        _git(root, "diff", *_DIFF_FLAGS, "--name-status", "-z", *refs)
    )
    binary = parse_binary_paths(
        _git(root, "diff", *_DIFF_FLAGS, "--numstat", "-z", *refs)
    )
    patch = parse_patch(_git(root, "diff", *_DIFF_FLAGS, "--unified=0", *refs))
    _warn_unmatched(patch, names)
    for change in names:
        change.binary = change.path in binary
        found = patch.get(change.path) or patch.get(change.old_path or "")
        if found is None:
            continue
        change.added, change.removed = found.added, found.removed
        change.hunk_lines = found.hunk_lines
    return names
