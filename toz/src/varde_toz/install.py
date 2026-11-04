"""Retire files written by older Toz installers."""

from __future__ import annotations

import contextlib
import json
from pathlib import Path

from blake3 import blake3

_MANIFESTS = (".varde-toz-install.json", ".toz-install.json")


def retire_owned_files(directory: Path, rels: list[str]) -> list[Path]:
    """Remove unchanged legacy files listed in a Toz install manifest.

    If any existing candidate is missing a matching manifest hash, keep all
    existing candidates and return the files that were kept.
    """
    manifest = _read_manifest(directory)
    owned: list[Path] = []
    kept: list[Path] = []
    for rel in rels:
        path = directory / rel
        try:
            current = path.read_text()
        except FileNotFoundError:
            continue
        digest = blake3(current.encode()).hexdigest()[:32]
        if manifest.get(rel) == digest:
            owned.append(path)
        else:
            kept.append(path)
    if kept:
        return kept
    for path in owned:
        path.unlink()
        _prune_empty_dirs(path.parent, directory)
    for name in _MANIFESTS:
        with contextlib.suppress(OSError):
            (directory / name).unlink()
    return kept


def _read_manifest(directory: Path) -> dict[str, str]:
    text = None
    for name in _MANIFESTS:
        try:
            text = (directory / name).read_text()
            break
        except OSError, UnicodeError:
            continue
    if text is None:
        return {}
    try:
        files = json.loads(text).get("files", {})
    except json.JSONDecodeError, AttributeError:
        return {}
    if not isinstance(files, dict):
        return {}
    return {
        key: value
        for key, value in files.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def _prune_empty_dirs(current: Path, stop: Path) -> None:
    while current != stop and current.is_relative_to(stop):
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent
