"""Install properties of a synced skill, kept in its `.varde-managed-skill` sidecar.

The sidecar is the ownership marker line followed by `key=value` lines. Old
readers only test marker line membership, so extra lines are safe.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path

SIDECAR = ".varde-managed-skill"
MARKER_LINE = "varde-managed-skill"
_KNOWN = (
    "packaged-version",
    "packaged-hash",
    "loop-hash",
    "pending-version",
    "pending-hash",
)


@dataclass(frozen=True)
class Props:
    packaged_version: str = ""
    packaged_hash: str = ""
    loop_hash: str = ""
    pending_version: str = ""
    pending_hash: str = ""
    extra: tuple[tuple[str, str], ...] = field(default_factory=tuple)


_FIELDS = {
    "packaged-version": "packaged_version",
    "packaged-hash": "packaged_hash",
    "loop-hash": "loop_hash",
    "pending-version": "pending_version",
    "pending-hash": "pending_hash",
}


def is_hashed_path(relative_path: str) -> bool:
    """Whether a skill-relative path belongs to the hashed tree."""
    parts = relative_path.split("/")
    if parts == [SIDECAR]:
        return False
    return not any(
        part.startswith(".")
        or part in {"__pycache__", "evals"}
        or part.endswith((".pyc", "-workspace"))
        for part in parts
    )


def disk_tree(directory: Path) -> dict[str, bytes]:
    """Relative path to bytes of the hashed files under an installed skill dir."""
    tree = {}
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory).as_posix()
        if path.is_file() and not path.is_symlink() and is_hashed_path(relative):
            tree[relative] = path.read_bytes()
    return tree


def tree_hash(files: Mapping[str, bytes]) -> str:
    """Sha256 over sorted relative paths and bytes, excluding the sidecar."""
    digest = hashlib.sha256()
    for path in sorted(files):
        if path == SIDECAR:
            continue
        name = path.encode()
        digest.update(len(name).to_bytes(8, "big") + name)
        digest.update(len(files[path]).to_bytes(8, "big") + files[path])
    return digest.hexdigest()


def parse(text: str) -> Props:
    """Properties in sidecar text; a marker-only sidecar gives empty props."""
    values: dict[str, str] = {}
    extra: list[tuple[str, str]] = []
    for line in text.splitlines():
        key, separator, value = line.partition("=")
        if not separator:
            continue
        if key in _FIELDS:
            values[_FIELDS[key]] = value
        else:
            extra.append((key, value))
    return Props(**values, extra=tuple(extra))


def render(props: Props) -> str:
    lines = [MARKER_LINE]
    for key in _KNOWN:
        value = getattr(props, _FIELDS[key])
        if value:
            lines.append(f"{key}={value}")
    lines.extend(f"{key}={value}" for key, value in props.extra)
    return "\n".join(lines) + "\n"


def is_modified(props: Props, current_hash: str) -> bool:
    """The on-disk tree differs from the packaged copy recorded at install."""
    return current_hash != props.packaged_hash


def with_pending(props: Props, version: str, packaged_hash: str) -> Props:
    return replace(props, pending_version=version, pending_hash=packaged_hash)


def render_registry(rows: Iterable[tuple[str, str, str]]) -> str:
    """Registry text of `(skill, step, entry)` rows (hashes and diffs share it)."""
    return "\n".join(
        f"[[tool]]\nskill = {_quote(skill)}\nstep = {_quote(step)}\n"
        f"entry = {_quote(entry)}\n"
        for skill, step, entry in rows
    )


def _quote(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)
