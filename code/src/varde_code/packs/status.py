"""Pack staleness: commits after a pack's sha that touch paths it documents."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from varde_code.errors import ApiError
from varde_code.index.paths import repo_db_path
from varde_code.index.provenance import current_head, read_built
from varde_code.packs import DOC_DIR, README
from varde_code.packs.gitinfo import commits_after
from varde_code.packs.header import NO_COMMIT, Header, parse_header
from varde_code.query.staleness import content_stale


@dataclass(frozen=True)
class PackStatus:
    path: str
    kind: str
    commit: str
    scope: str
    stale: bool
    commits_behind: int


def touches_pack(paths: list[str], scope: str) -> bool:
    """Whether a commit's paths change what a pack with ``scope`` documents."""
    prefix = "" if scope == "." else scope.rstrip("/") + "/"
    return any(
        not path.startswith(f"{DOC_DIR}/")
        and (path.startswith(prefix) or path == scope)
        for path in paths
    )


def count_behind(commits: list[list[str]], scope: str) -> int:
    """Count commits that touch paths inside ``scope`` outside the pack directory."""
    return sum(touches_pack(paths, scope) for paths in commits)


def pack_status(
    root: Path, relative: str, header: Header, readme_max_behind: int = 1
) -> PackStatus:
    """Status of one pack; raises ``ApiError('git_error', ...)`` when git fails.

    Module packs are stale after any scope commit; the README only once it is
    ``readme_max_behind`` or more commits behind.
    """
    if header.commit == NO_COMMIT:
        return PackStatus(relative, header.kind, header.commit, header.scope, False, 0)
    commits = commits_after(root, header.commit)
    if commits is None:
        raise ApiError("git_error", f"cannot list commits after {header.commit}")
    behind = count_behind(commits, header.scope)
    limit = readme_max_behind if relative == README else 1
    return PackStatus(
        relative,
        header.kind,
        header.commit,
        header.scope,
        behind > 0 and behind >= limit,
        behind,
    )


def pack_paths(root: Path, listed: set[str] | None = None) -> list[str]:
    """Return generated pack paths (relative, sorted), README first when present.

    ``listed`` limits the result to the README and those paths (orphans ignored).
    """
    directory = root / DOC_DIR
    found = [
        path.relative_to(root).as_posix() for path in sorted(directory.rglob("*.md"))
    ]
    if listed is not None:
        found = [path for path in found if path == README or path in listed]
    return sorted(found, key=lambda path: (path != README, path))


def collect_packs(
    root: Path, listed: set[str] | None = None, readme_max_behind: int = 1
) -> list[PackStatus]:
    statuses = []
    for relative in pack_paths(root, listed):
        header = parse_header((root / relative).read_text(encoding="utf-8"))
        if header is not None:
            statuses.append(pack_status(root, relative, header, readme_max_behind))
    return statuses


def index_status(root: Path) -> dict[str, object]:
    """Index provenance for the status report; ``present`` is false without an index."""
    db_path = repo_db_path(root)
    if not db_path.is_file():
        return {"present": False}
    built = read_built(db_path)
    age = None if built.built_at is None else max(0, int(time.time()) - built.built_at)
    return {
        "present": True,
        "built_head": built.built_head,
        "head": current_head(root),
        "age_seconds": age,
        "stale": content_stale(str(db_path), str(root)),
    }
