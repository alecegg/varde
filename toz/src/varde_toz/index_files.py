"""File indexing and stale-file refresh behavior."""

from __future__ import annotations

import re
from pathlib import Path

import blake3

from . import metadata
from .capture import CaptureInput, CaptureResult, capture, source_key
from .project import project_root
from .redact_toz import configured_redactor, redact_configured
from .store import Store


def file_meta(path: Path, data: bytes) -> tuple[int, bytes]:
    return path.stat().st_mtime_ns, blake3.blake3(data).digest()


def is_stale(path: str | Path, mtime: int | None, digest: bytes | None) -> bool:
    try:
        stat = Path(path).stat()
    except OSError:
        return True
    now_mtime = stat.st_mtime_ns
    if mtime is not None and now_mtime == mtime:
        return False
    try:
        current = Path(path).read_bytes()
    except OSError:
        return True
    return digest is None or blake3.blake3(current).digest() != digest


def index_file(
    path: Path,
    label: str | None,
    root: Path | None = None,
    store_path: Path | None = None,
) -> CaptureResult:
    absolute = path.resolve(strict=True)
    data = absolute.read_bytes()
    mtime, digest = file_meta(absolute, data)
    return capture(
        CaptureInput(
            data,
            label=label,
            source=str(absolute),
            kind="index",
            force=True,
            file_mtime=mtime,
            file_hash=digest,
        ),
        root,
        store_path,
    )


def index_bytes(
    data: bytes, label: str | None, root: Path | None = None
) -> CaptureResult:
    source = label or "stdin"
    return capture(
        CaptureInput(data, label=label, source=source, kind="index", force=True), root
    )


def skipped_index_message(source: str, rule: str, root: Path) -> str:
    redactor = configured_redactor(root)
    safe_source = metadata.sanitize_text(
        source, lambda value: redact_configured(value, redactor)
    )
    return f"varde-toz: {safe_source}: not indexed ({rule})\n"


def refresh_stale(store: Store, root: Path | None = None) -> list[str]:
    root = root or project_root()
    refreshed = []
    for row in store.list(2**63 - 1, False):
        if row["kind"] != "index" or not Path(row["source"]).is_file():
            continue
        if not is_stale(row["source"], row["file_mtime"], row["file_hash"]):
            continue
        source_key_value = store.conn.execute(
            "SELECT source_key FROM captures WHERE id=?", (row["id"],)
        ).fetchone()[0]
        default_key = source_key(row["source"])
        key_dir = store.path.parent
        if source_key_value in (
            default_key,
            metadata.identity_at(key_dir, default_key),
        ):
            label = None
        elif source_key_value in (
            row["label"],
            metadata.identity_at(key_dir, row["label"]),
        ):
            label = row["label"]
        else:
            continue
        try:
            file_root = root or project_root(Path(row["source"]).parent)
            status, _ = index_file(Path(row["source"]), label, file_root, store.path)
        except OSError, ValueError, RuntimeError:
            continue
        if status:
            refreshed.append(row["source"])
    return refreshed


def glob_matches(pattern: str, filename: str) -> bool:
    expression = "^"
    in_alt = False
    for char in pattern:
        if char == "*":
            expression += ".*"
        elif char == "?":
            expression += "."
        elif char == "{" and not in_alt:
            in_alt = True
            expression += "(?:"
        elif char == "}" and in_alt:
            in_alt = False
            expression += ")"
        elif char == "," and in_alt:
            expression += "|"
        else:
            expression += re.escape(char)
    expression += "$"
    return re.fullmatch(expression, filename) is not None


def collect_paths(paths: list[Path], recursive: bool, glob: str | None) -> list[Path]:
    found: list[Path] = []

    def walk(directory: Path) -> None:
        for candidate in sorted(directory.iterdir(), key=lambda entry: entry.name):
            if candidate.name.startswith("."):
                continue
            if candidate.is_symlink():
                continue
            if candidate.is_dir():
                if recursive:
                    walk(candidate)
            elif candidate.is_file():
                found.append(candidate)

    for path in paths:
        if path.is_dir():
            walk(path)
        elif path.is_file():
            found.append(path)
        else:
            raise FileNotFoundError(f"no such file or directory: {path}")
    if glob is not None:
        found = [path for path in found if glob_matches(glob, path.name)]
    if not found:
        raise ValueError("nothing to index")
    return found
