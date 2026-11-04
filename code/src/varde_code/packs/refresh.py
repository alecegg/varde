"""Build every listed pack (``--all``) or only the stale ones (``--stale``)."""

from __future__ import annotations

from pathlib import Path

from varde_code.errors import ApiError
from varde_code.packs import DOC_DIR, README
from varde_code.packs.module_pack import build as build_module
from varde_code.packs.module_pack import normalize_folder, slug
from varde_code.packs.repo_map import build as build_readme
from varde_code.packs.status import collect_packs
from varde_code.seams import ExtractionProvider

MODULES_FILE = f"{DOC_DIR}/modules.txt"


def read_modules(root: Path) -> list[str]:
    """Return the folders in ``modules.txt``; raise ``modules_missing`` if absent."""
    target = root / MODULES_FILE
    if not target.is_file():
        raise ApiError("modules_missing", f"{MODULES_FILE} not found")
    lines = (line.split("#", 1)[0].strip() for line in target.read_text().splitlines())
    return [line.strip("/") for line in lines if line.strip("/")]


def module_path(folder: str) -> str:
    return f"{DOC_DIR}/modules/{slug(folder)}.md"


def _validated(root: Path, modules: list[str]) -> list[str]:
    return [normalize_folder(root, folder) for folder in modules]


def build_all(root: Path, extractor: ExtractionProvider) -> list[Path]:
    """Write the README and every listed module pack."""
    folders = _validated(root, read_modules(root))
    written = [build_readme(root, extractor)]
    written += [build_module(root, folder, extractor) for folder in folders]
    return written


def build_stale(
    root: Path, extractor: ExtractionProvider, readme_max_behind: int
) -> list[Path]:
    """Write only a missing or behind README and missing or stale module packs."""
    modules = _validated(root, read_modules(root))
    listed = {module_path(folder) for folder in modules}
    packs = {p.path: p for p in collect_packs(root, listed, readme_max_behind)}
    written = []
    readme = packs.get(README)
    if readme is None or readme.stale:
        written.append(build_readme(root, extractor))
    for folder in modules:
        pack = packs.get(module_path(folder))
        if pack is None or pack.stale:
            written.append(build_module(root, folder, extractor))
    return written
