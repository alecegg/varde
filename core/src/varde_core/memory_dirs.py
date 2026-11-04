"""Resolve per-project working and knowledge directories.

Precedence: environment variable, `[project]` entry, `[default]` table, then
the user-level default under `local_share_dir()`. Nothing is created here.
"""

from __future__ import annotations

import os
import subprocess
import tomllib
from functools import lru_cache
from pathlib import Path
from typing import Any

from varde_core.paths import fnv1a64, local_share_dir, varde_config_dir

KINDS = ("working", "knowledge", "memory")
LEGACY_KINDS = ("working", "knowledge")
PROJECT_FREE_KINDS = ("memory",)
ENV_NAMES = {
    "working": "VARDE_WORKING_DIR",
    "knowledge": "VARDE_KNOWLEDGE_DIR",
    "memory": "VARDE_MEMORY_DIR",
}
SOURCE_ENV = "env"
SOURCE_PROJECT = "project"
SOURCE_DEFAULT = "default"
SOURCE_BUILTIN = "builtin"
LEGACY_MEMORY_BANK = "memory-bank"


def canonical_or_lexical(path: Path) -> Path:
    return path.resolve(strict=False)


def project_key(root: Path) -> str:
    """Return the `<name>-<16 hex>` key for a project root."""
    root = canonical_or_lexical(root)
    name = root.name or "repo"
    return f"{name}-{fnv1a64(str(root).encode()):016x}"


def default_memory_dir(root: Path, kind: str) -> Path:
    """Return the built-in directory for a kind.

    Project kinds live at `<share>/varde/projects/<name>-<16 hex>/<kind>`;
    `memory` is project-independent: `<share>/varde/memory`.
    """
    if kind in PROJECT_FREE_KINDS:
        return local_share_dir() / "varde" / kind
    return local_share_dir() / "varde" / "projects" / project_key(root) / kind


def legacy_memory_bank_dirs(root: Path) -> list[Path]:
    """Return existing `<root>/memory-bank/{working,knowledge}` directories."""
    return [
        path
        for path in (root / LEGACY_MEMORY_BANK / kind for kind in LEGACY_KINDS)
        if path.is_dir()
    ]


def table(value: Any) -> Any:
    return value if hasattr(value, "items") else {}


def path_value(source: Any, key: str) -> str | None:
    value = table(source).get(key)
    return value if isinstance(value, str) else None


def project_entry(document: Any, root: Path) -> Any:
    for key, entry in table(document.get("project")).items():
        if canonical_or_lexical(Path(str(key))) == root:
            return table(entry)
    return {}


def expand(root: Path, value: str) -> Path:
    value = value.replace("{project}", root.name)
    if value == "~" or value.startswith("~/"):
        value = str(Path.home() / value[2:])
    path = Path(value)
    return canonical_or_lexical(path if path.is_absolute() else root / path)


def resolve_memory_dir(root: Path, kind: str, document: Any) -> tuple[Path, str]:
    """Return the directory and the source name for one memory kind."""
    env_value = os.environ.get(ENV_NAMES[kind])
    if env_value:
        return expand(root, env_value), SOURCE_ENV
    if kind not in PROJECT_FREE_KINDS:
        value = path_value(project_entry(document, root), kind)
        if value is not None:
            return expand(root, value), SOURCE_PROJECT
    value = path_value(table(document.get("default")), kind)
    if value is not None:
        return expand(root, value), SOURCE_DEFAULT
    return default_memory_dir(root, kind), SOURCE_BUILTIN


def load_config_document() -> dict[str, Any]:
    """Read config.toml (or legacy paths.toml); an unreadable file counts as empty."""
    path = varde_config_dir() / "config.toml"
    if not path.exists():
        path = path.with_name("paths.toml")
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError, ValueError:
        return {}


def resolve_project_dir(start: Path, kind: str) -> Path:
    """Resolve a kind for the repository containing `start`, with config overrides."""
    start = canonical_or_lexical(start)
    begin = start if start.is_dir() else start.parent
    top = git_path(begin, "--show-toplevel") or begin
    root = repository_memory_root(top)
    return resolve_memory_dir(root, kind, load_config_document())[0]


def repository_memory_root(root: str | Path) -> Path:
    return _repository_memory_root(canonical_or_lexical(Path(root)))


@lru_cache(maxsize=128)
# Per-process cache; repository changes do not invalidate it.
def _repository_memory_root(root: Path) -> Path:
    common = git_path(root, "--git-common-dir")
    git_dir = git_path(root, "--git-dir")
    if common is None or git_dir is None or common == git_dir:
        return root
    configured = _core_worktree(root, common)
    if configured is not None:
        return configured
    return _first_worktree(root) or root


def _core_worktree(root: Path, common: Path) -> Path | None:
    try:
        output = subprocess.run(  # noqa: S603 - Reads Git worktree configuration from the repository.
            [  # noqa: S607 - Git is resolved from PATH.
                "git",
                "--git-dir",
                str(common),
                "config",
                "--null",
                "--get",
                "core.worktree",
            ],
            cwd=root,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if output.returncode != 0:
        return None
    raw = output.stdout.removesuffix(b"\0").decode(errors="surrogateescape")
    if not raw:
        return None
    path = Path(raw)
    return canonical_or_lexical(path if path.is_absolute() else common / path)


def _first_worktree(root: Path) -> Path | None:
    try:
        output = subprocess.run(
            ["git", "worktree", "list", "--porcelain", "-z"],  # noqa: S607 - Git is resolved from PATH.
            cwd=root,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if output.returncode != 0:
        return None
    first = output.stdout.split(b"\0", 1)[0]
    if not first.startswith(b"worktree "):
        return None
    return canonical_or_lexical(Path(first[9:].decode(errors="surrogateescape")))


def git_path(root: Path, flag: str) -> Path | None:
    try:
        result = subprocess.run(  # noqa: S603 - Resolves a Git path for an internal fixed flag.
            ["git", "rev-parse", flag],  # noqa: S607 - Git is resolved from PATH.
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    path = Path(result.stdout.strip())
    return canonical_or_lexical(path if path.is_absolute() else root / path)
