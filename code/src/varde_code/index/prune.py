"""Remove orphaned Python code-index folders, defaulting to a dry run."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from varde_core.paths import varde_config_dir

from varde_code import ApiError

from .repo_lock import probe

SOURCE_ROOT_FILE = "source-root"
SECONDS_PER_DAY = 86_400


def run(input: Any) -> dict[str, Any]:
    return run_in(varde_config_dir(), input)


def run_in(config_dir: Path, input: Any) -> dict[str, Any]:
    if not isinstance(input, dict):
        raise ApiError("invalid_input", "prune input must be a JSON object")
    apply = input.get("apply", False)
    if not isinstance(apply, bool):
        apply = False
    older = input.get("unknownOlderThanDays")
    if older is not None and (
        not isinstance(older, int) or isinstance(older, bool) or older < 0
    ):
        raise ApiError(
            "invalid_input", "unknownOlderThanDays must be a non-negative integer"
        )

    key = "removed" if apply else "wouldRemove"
    selected: list[dict[str, Any]] = []
    failed: list[dict[str, str]] = []
    unknown: list[dict[str, Any]] = []
    counts = {"scanned": 0, "failed": 0, "unknown": 0, "locked": 0, "kept": 0}
    kept_bytes = selected_bytes = 0
    for folder in _index_folders(Path(config_dir)):
        counts["scanned"] += 1
        size = _folder_bytes(folder)
        is_locked, guard = probe(folder / "index.db")
        if is_locked:
            counts["locked"] += 1
            continue
        try:
            reason, is_unknown = _classify(folder, older)
            if is_unknown:
                unknown.append({"folder": str(folder), "bytes": size})
            if reason is None:
                counts["kept"] += 1
                kept_bytes += size
                continue
            if apply:
                try:
                    import shutil

                    shutil.rmtree(folder)
                except OSError as exc:
                    failed.append({"folder": str(folder), "error": str(exc)})
                    continue
            selected_bytes += size
            selected.append({"folder": str(folder), "reason": reason, "bytes": size})
        finally:
            if guard is not None:
                guard.close()

    counts[key] = len(selected)
    counts["failed"] = len(failed)
    counts["unknown"] = len(unknown)
    return {
        "apply": apply,
        key: selected,
        "failed": failed,
        "unknown": unknown,
        "keptBytes": kept_bytes,
        "selectedBytes": selected_bytes,
        "counts": counts,
    }


def _index_folders(config_dir: Path) -> list[Path]:
    try:
        folders = [
            path
            for path in (config_dir / "code" / "repos-py").iterdir()
            if path.is_dir()
        ]
    except OSError:
        return []
    return sorted(folders)


def _classify(folder: Path, older_than_days: int | None) -> tuple[str | None, bool]:
    try:
        source = (folder / SOURCE_ROOT_FILE).read_text().strip()
    except OSError:
        source = ""
    if source:
        return ("source_missing", False) if not _exists(source) else (None, False)
    if older_than_days is None:
        return None, True
    try:
        modified = (folder / "index.db").stat().st_mtime
    except OSError:
        return None, True
    age = max(0.0, time.time() - modified)
    return (
        ("unknown_idle", True)
        if age >= older_than_days * SECONDS_PER_DAY
        else (None, True)
    )


def record_source_root(db_path: Path, source_root: Path) -> None:
    """Record the canonical source root beside an index database."""
    value = f"{source_root.resolve(strict=True)}\n"
    sidecar = db_path.parent / SOURCE_ROOT_FILE
    try:
        if sidecar.read_text(encoding="utf-8") == value:
            return
    except OSError:
        pass
    sidecar.write_text(value, encoding="utf-8")


def _exists(path: str) -> bool:
    try:
        Path(path).stat()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        # Permission and other inspection errors are unknown, so preserve the folder.
        return True


def _folder_bytes(folder: Path) -> int:
    total = 0
    stack = [folder]
    while stack:
        directory = stack.pop()
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir() and not entry.is_symlink():
                    stack.append(entry)
                else:
                    total += entry.stat().st_size
            except OSError:
                continue
    return total
