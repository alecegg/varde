"""Folder-scoped module packs: nav_map data restricted to one folder."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from varde_code.errors import ApiError
from varde_code.index.provenance import current_head
from varde_code.packs import DOC_DIR
from varde_code.packs.filter import drop_excluded, read_excluded
from varde_code.packs.gitinfo import is_dirty
from varde_code.packs.header import (
    NO_COMMIT,
    Header,
    generator_name,
    render_header,
    utc_now,
)
from varde_code.packs.index_refresh import ensure_index
from varde_code.packs.repo_map import relativize, write_if_changed
from varde_code.query.nav_map import format_map, nav_map
from varde_code.seams import ExtractionProvider


def normalize_folder(root: Path, folder: str) -> str:
    """Return ``folder`` relative to ``root``; raise ``folder_not_found`` if absent."""
    target = (root / folder).resolve()
    inside = target.is_relative_to(root.resolve()) and target != root.resolve()
    if not inside or not target.is_dir():
        raise ApiError("folder_not_found", f"folder not found: {folder}")
    return target.relative_to(root.resolve()).as_posix()


def slug(folder: str) -> str:
    """Return an injective file stem: ``/`` is ``-``; ``-`` and ``%`` are escaped."""
    escaped = folder.replace("%", "%25").replace("-", "%2D")
    return escaped.replace("/", "-")


def render_module_pack(data: dict[str, Any], header: Header) -> str:
    return f"{render_header(header)}# Module {header.scope}\n\n{format_map(data)}"


def build(root: Path, folder: str, extractor: ExtractionProvider) -> Path:
    """Write the module pack for ``folder`` and return its path."""
    relative = normalize_folder(root, folder)
    db_path = ensure_index(root, extractor)
    data = nav_map({"repoRoot": str(root), "dbPath": str(db_path), "folder": relative})
    data = drop_excluded(data, read_excluded(root), str(root))
    header = Header(
        kind="module-pack",
        commit=current_head(root) or NO_COMMIT,
        scope=relative,
        generated_at=utc_now(),
        generator=generator_name(),
        dirty=is_dirty(root),
    )
    target = root / DOC_DIR / "modules" / f"{slug(relative)}.md"
    write_if_changed(target, relativize(render_module_pack(data, header), root))
    return target
