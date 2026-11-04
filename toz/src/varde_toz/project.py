"""Project identity and store path helpers."""

from __future__ import annotations

import os
from pathlib import Path


def project_root(path: str | Path | None = None) -> Path:
    start = Path(path or os.getcwd()).resolve()
    directory = start if start.is_dir() else start.parent
    for candidate in (directory, *directory.parents):
        if (candidate / ".git").exists():
            return candidate
    return start


def project_key(root: str | Path) -> str:
    path = Path(root).resolve()
    readable = (
        "".join(
            "-"
            if char in "/\\:"
            else char
            if (char.isalnum() or char in "-_ .")
            else "_"
            for char in str(path)
        )
        .replace(" ", "_")
        .strip("-")
        or "project"
    )
    readable = readable[:96]
    # Rust uses BLAKE3; use the compatible implementation when installed.
    try:
        import blake3  # type: ignore[import-not-found]

        digest = blake3.blake3(os.fsencode(path)).hexdigest()[:32]
    except ImportError as exc:
        raise RuntimeError(
            "the blake3 package is required for Rust-compatible project keys"
        ) from exc
    return f"{readable}-{digest}"


def store_db_path(root: str | Path, config_dir: str | Path) -> Path:
    return Path(config_dir) / project_key(root) / "toz.db"
