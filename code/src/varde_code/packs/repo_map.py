"""Top-level repo map: render nav_map data as committed markdown."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from varde_code.index.provenance import current_head
from varde_code.packs import README
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
from varde_code.query.nav_map import format_map, nav_map
from varde_code.seams import ExtractionProvider


def render_repo_map(data: dict[str, Any], header: Header) -> str:
    """Return the full README text for nav_map ``data``."""
    return f"{render_header(header)}# Repo map\n\n{format_map(data)}"


def build(root: Path, extractor: ExtractionProvider) -> Path:
    """Refresh the index, then write ``docs/repo-map/README.md``; return its path."""
    db_path = ensure_index(root, extractor)
    data = nav_map({"repoRoot": str(root), "dbPath": str(db_path)})
    data = drop_excluded(data, read_excluded(root), str(root))
    header = Header(
        kind="repo-map",
        commit=current_head(root) or NO_COMMIT,
        scope=".",
        generated_at=utc_now(),
        generator=generator_name(),
        dirty=is_dirty(root),
    )
    target = root / README
    write_if_changed(target, relativize(render_repo_map(data, header), root))
    return target


def relativize(text: str, root: Path) -> str:
    """Strip the repo root so packs hold repo-relative paths, not machine paths."""
    for prefix in {str(root), str(root.resolve())}:
        text = text.replace(f"{prefix}/", "")
    return text


_GENERATED_AT = re.compile(r"^generated_at: .*$", re.MULTILINE)


def write_if_changed(target: Path, text: str) -> None:
    """Write ``text`` unless the file already equals it apart from ``generated_at``."""
    if target.is_file():
        existing = target.read_text(encoding="utf-8")
        if _GENERATED_AT.sub("", existing, 1) == _GENERATED_AT.sub("", text, 1):
            return
    write_atomic(target, text)


def write_atomic(target: Path, text: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, target)
