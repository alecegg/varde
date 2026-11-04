"""Discover skills, agents, and uv projects in module layouts."""

from __future__ import annotations

import tomllib
from pathlib import Path


def _named_dirs(candidates: list[Path], marker: str | None = None) -> dict[str, Path]:
    found: dict[str, Path] = {}
    for path in candidates:
        if marker and not (path / marker).is_file():
            continue
        name = path.name
        if name in found:
            raise ValueError(f"duplicate {name}: {found[name]} and {path}")
        found[name] = path
    return found


def skill_dirs(root: Path) -> dict[str, Path]:
    candidates = sorted(
        path
        for path in root.glob("*/skills/varde-*")
        if (path.parents[1] / "pyproject.toml").is_file()
    )
    return _named_dirs(candidates, "SKILL.md")


def agent_dirs(root: Path) -> dict[str, Path]:
    candidates = sorted(
        path
        for path in root.glob("*/agents/varde-*")
        if (path.parents[1] / "pyproject.toml").is_file()
    )
    return _named_dirs(candidates)


def project_dirs(root: Path) -> dict[str, Path]:
    manifests = sorted(
        manifest
        for manifest in root.glob("*/pyproject.toml")
        if not any(part.startswith(".") for part in manifest.relative_to(root).parts)
    )
    projects: dict[str, Path] = {}
    for manifest in manifests:
        name = tomllib.loads(manifest.read_text(encoding="utf-8"))["project"]["name"]
        if name in projects:
            raise ValueError(
                f"duplicate {name}: {projects[name]} and {manifest.parent}"
            )
        projects[name] = manifest.parent
    return projects
