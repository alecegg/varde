"""Shared memory store: a git checkout read from its default branch."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from varde_core.frontmatter import FrontmatterError
from varde_core.paths import local_share_dir

from varde_learn.memory import store
from varde_learn.memory.entry import (
    DEFAULT_TYPE,
    SCOPES,
    Entry,
    EntryError,
    find_secret,
    is_slug,
    validate,
)
from varde_learn.memory.index import IndexLine, summarize

SHARED_PREFIX = "shared:"
SHARED_SCOPES = ("agent", "skill", "global")
MAX_TAGS = 8
MAX_TAG_CHARS = 32
MAX_SOURCE_CHARS = 200
MAX_FIELD_CHARS = 80
MAX_TOPIC_CHARS = 32
MAX_DESCRIPTION_CHARS = 200
MAX_TEXT_CHARS = 2000
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_SINGLE_LINE = re.compile(r"[\x00-\x1f\x7f]+")


class ShareError(Exception):
    """A shared-store operation cannot proceed (usage-level failure)."""


def checkout_path() -> Path:
    return local_share_dir() / "varde" / "memory-shared"


def store_id(root: Path) -> str:
    """Stable id of a local memory store; never a local path."""
    return hashlib.sha256(str(root).encode()).hexdigest()[:12]


def single_line(text: str, limit: int) -> str:
    return _SINGLE_LINE.sub(" ", text).strip()[:limit]


def sanitize(entry: Entry) -> Entry:
    """Strip control characters from untrusted text and cap its short fields."""
    tags = tuple(single_line(t, MAX_TAG_CHARS) for t in entry.tags[:MAX_TAGS])
    return replace(
        entry,
        text=_CONTROL.sub("", entry.text),
        tags=tuple(t for t in tags if t),
        source=single_line(entry.source, MAX_SOURCE_CHARS),
        model=single_line(entry.model, MAX_FIELD_CHARS),
        harness_version=single_line(entry.harness_version, MAX_FIELD_CHARS),
        type=entry.type if is_slug(entry.type) else DEFAULT_TYPE,
        topic=entry.topic if _valid_topic(entry.topic) else "",
        description=single_line(entry.description, MAX_DESCRIPTION_CHARS),
    )


def _valid_topic(topic: str) -> bool:
    return is_slug(topic) and len(topic) <= MAX_TOPIC_CHARS


def valid_timestamp(value: str) -> bool:
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return False
    return True


def shared_violation(entry: Entry) -> str | None:
    """Why an entry may not live in the shared store, or None."""
    if entry.scope not in SHARED_SCOPES:
        return "project-scope entries are not shared"
    if entry.project:
        return "entries with a project field are not shared"
    if len(entry.text) > MAX_TEXT_CHARS:
        return f"text exceeds {MAX_TEXT_CHARS} characters"
    if find_secret(entry.text) is not None:
        return "text looks like a secret"
    return None


def shared_line(entry: Entry) -> IndexLine:
    return IndexLine(
        f"{SHARED_PREFIX}{entry.id}",
        entry.scope,
        single_line(summarize(entry.text), 80),
        entry.tags,
    )


def shared_index(entries: list[Entry]) -> list[IndexLine]:
    ordered = sorted(entries, key=lambda e: (SCOPES.index(e.scope), e.created, e.id))
    return [shared_line(e) for e in ordered]


def parse_tree_listing(listing: str) -> list[tuple[str, str]]:
    """(blob sha, path) pairs of `.md` files under a scope directory."""
    found = []
    for line in listing.splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        is_entry = len(parts) == 3 and parts[1] == "blob" and path.endswith(".md")
        if is_entry and path.split("/", 1)[0] in SCOPES:
            found.append((parts[2], path))
    return found


def entry_from_blob(data: str, path: str) -> Entry:
    """Validate one shared file against its path; raise EntryError if it fails."""
    entry = sanitize(store.from_document(data))
    violation = shared_violation(entry)
    if violation:
        raise EntryError(violation)
    validate(entry)
    if not valid_timestamp(entry.created):
        raise EntryError(f"invalid created timestamp: {entry.created!r}")
    expected = store.entry_path(Path(), entry.scope, entry.scope_key, entry.id)
    if expected.as_posix() != path:
        raise EntryError(f"frontmatter does not match path: {path}")
    return entry


def _git(checkout: Path, *args: str, stdin: bytes | None = None) -> bytes:
    result = subprocess.run(  # noqa: S603
        ["git", "-C", str(checkout), *args],  # noqa: S607
        input=stdin,
        capture_output=True,
        check=False,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if result.returncode != 0:
        message = result.stderr.decode(errors="replace").strip()
        raise ShareError(f"git {args[0]} failed: {message}")
    return result.stdout


def default_branch(checkout: Path) -> str:
    """The checkout stays on its default branch; promote works in a worktree."""
    return _git(checkout, "symbolic-ref", "--short", "HEAD").decode().strip()


def _read_blobs(checkout: Path, shas: list[str]) -> list[str]:
    raw = _git(checkout, "cat-file", "--batch", stdin=("\n".join(shas) + "\n").encode())
    blobs, position = [], 0
    for _ in shas:
        end = raw.index(b"\n", position)
        size = int(raw[position:end].split()[2])
        blobs.append(raw[end + 1 : end + 1 + size].decode("utf-8", errors="replace"))
        position = end + size + 2
    return blobs


def load_shared(checkout: Path | None = None) -> list[Entry]:
    """Valid shared entries from the default-branch tree; none without a checkout."""
    return read_shared(checkout)[0]


def read_shared(checkout: Path | None = None) -> tuple[list[Entry], list[str]]:
    """Valid shared entries and one warning per dropped file."""
    checkout = checkout or checkout_path()
    if not (checkout / ".git").exists():
        return [], []
    try:
        branch = default_branch(checkout)
        listing = _git(checkout, "ls-tree", "-r", branch).decode()
        files = parse_tree_listing(listing)
        blobs = _read_blobs(checkout, [sha for sha, _ in files]) if files else []
    except (ShareError, ValueError, IndexError) as error:
        print(f"warning: shared store unreadable: {error}", file=sys.stderr)
        return [], []
    entries, dropped = [], []
    for (_, path), data in zip(files, blobs, strict=True):
        try:
            entries.append(entry_from_blob(data, path))
        except (EntryError, FrontmatterError) as error:
            dropped.append(f"dropped shared {path}: {error}")
    return entries, dropped


def warn_dropped(dropped: list[str]) -> None:
    """Print dropped-file warnings; only explicit list and pull call this."""
    for message in dropped:
        print(f"warning: {message}", file=sys.stderr)


def pull(source: str, checkout: Path | None = None) -> str:
    """Clone `source` when there is no checkout, else fast-forward it."""
    checkout = checkout or checkout_path()
    if (checkout / ".git").exists():
        _git(checkout, "pull", "--ff-only")
        return "updated"
    checkout.parent.mkdir(parents=True, exist_ok=True)
    target = os.path.expanduser(source)
    result = subprocess.run(  # noqa: S603
        ["git", "clone", "--", target, str(checkout)],  # noqa: S607
        capture_output=True,
        check=False,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if result.returncode != 0:
        raise ShareError(f"git clone failed: {result.stderr.decode().strip()}")
    return "cloned"


def git_user(checkout: Path) -> tuple[str, str]:
    values = []
    for key in ("user.name", "user.email"):
        try:
            values.append(_git(checkout, "config", key).decode().strip())
        except ShareError:
            raise ShareError(f"git {key} is not set; set it before promoting") from None
    return values[0], values[1]


def require_checkout(checkout: Path) -> None:
    if not (checkout / ".git").exists():
        raise ShareError("no shared checkout; run `varde learn memory pull` first")


def promote(entry: Entry, root: Path, checkout: Path | None = None) -> str:
    """Commit `entry` onto branch `promote/<id>` of the checkout; return the branch."""
    checkout = checkout or checkout_path()
    require_checkout(checkout)
    if entry.status != "active":
        raise ShareError(f"cannot promote {entry.id}: only active entries")
    violation = shared_violation(entry)
    if violation:
        raise ShareError(f"cannot promote {entry.id}: {violation}")
    branch = f"promote/{entry.id}"
    if _branch_exists(checkout, branch):
        raise ShareError(f"branch {branch} already exists in the shared checkout")
    base = default_branch(checkout)
    if _in_default_tree(checkout, base, entry.id):
        raise ShareError(f"entry {entry.id} already exists in the shared store")
    name, email = git_user(checkout)
    origin = store_id(root)
    promoted = replace(entry, source=f"{single_line(name, 80)} via store {origin}")
    try:
        _commit_on_branch(checkout, base, branch, promoted, (name, email), origin)
    except Exception:
        _delete_branch(checkout, branch)
        raise
    return branch


def _commit_on_branch(
    checkout: Path,
    base: str,
    branch: str,
    entry: Entry,
    author: tuple[str, str],
    origin: str,
) -> None:
    name, email = author
    with tempfile.TemporaryDirectory() as temporary:
        tree = Path(temporary) / "wt"
        _git(checkout, "worktree", "add", "-b", branch, str(tree), base)
        try:
            store.write_entry(tree, entry)
            _git(tree, "add", "--all")
            message = f"Promote memory entry {entry.id}\n\nPromoted-from: {origin}\n"
            _git(
                tree, "-c", f"user.name={name}", "-c", f"user.email={email}",
                "commit", f"--author={name} <{email}>", "-m", message,
            )  # fmt: skip
        finally:
            _git(checkout, "worktree", "remove", "--force", str(tree))


def _in_default_tree(checkout: Path, base: str, entry_id: str) -> bool:
    files = parse_tree_listing(_git(checkout, "ls-tree", "-r", base).decode())
    return any(path.rsplit("/", 1)[-1] == f"{entry_id}.md" for _, path in files)


def _delete_branch(checkout: Path, branch: str) -> None:
    try:
        _git(checkout, "branch", "-D", branch)
    except ShareError:
        return  # the branch was never created; nothing to clear


def _branch_exists(checkout: Path, branch: str) -> bool:
    try:
        _git(checkout, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
    except ShareError:
        return False
    return True
