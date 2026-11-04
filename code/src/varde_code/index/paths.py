"""Repository-specific paths for the Python code index."""

from __future__ import annotations

from pathlib import Path

from varde_core.paths import fnv1a64, varde_config_dir


def repo_identity(repo_root: Path) -> int:
    """Return FNV-1a 64-bit identity of the canonical repository path."""
    canonical = _canonical(repo_root)
    value = fnv1a64(str(canonical).encode())
    return value if value < 0x8000000000000000 else value - 0x10000000000000000


def repo_db_path(repo_root: Path) -> Path:
    canonical = _canonical(repo_root)
    name = canonical.name or "repo"
    identity = repo_identity(canonical) & 0xFFFFFFFFFFFFFFFF
    return (
        varde_config_dir()
        / "code"
        / "repos-py"
        / f"{name}-{identity:016x}"
        / "index.db"
    )


def _canonical(path: Path) -> Path:
    try:
        return path.resolve(strict=True)
    except OSError:
        return path
