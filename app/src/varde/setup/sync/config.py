"""Saved sync settings stored in the user config document."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from varde.setup.catalog import skills as catalog_skills
from varde.setup.sync.skills import RETIRED_SKILLS


@dataclass
class SavedSettings:
    skills_dir: Path | None = None
    agents_dir: Path | None = None
    link_mode: str | None = None
    skills: list[str] | None = None
    presets: list[str] | None = None


RENAMED_PRESETS = {"doc": "learn", "knowledge": "learn"}


def migrate_presets(config: Any) -> str | None:
    """Map saved presets renamed by the module merge; return a notice or None."""
    document = getattr(config, "document", config)
    table = document.get("sync")
    saved = table.get("presets") if isinstance(table, dict) else None
    if not isinstance(saved, list):
        return None
    old = [name for name in dict.fromkeys(saved) if name in RENAMED_PRESETS]
    if not old:
        return None
    mapped = [RENAMED_PRESETS.get(name, name) for name in saved]
    table["presets"] = list(dict.fromkeys(mapped))
    return (
        f"varde setup sync: saved preset {', '.join(old)} is now preset learn; "
        "config rewritten. Run varde setup sync once to finish the migration; "
        "installed skills stay in place."
    )


def validate_skills(names: list[str]) -> None:
    valid = [skill.name for skill in catalog_skills()]
    unknown = next((name for name in names if name not in valid), None)
    if unknown is not None:
        raise ValueError(f"unknown skill {unknown}; valid skills: {', '.join(valid)}")


def _without_retired(names: list[str]) -> list[str] | None:
    retired = [name for name in dict.fromkeys(names) if name in RETIRED_SKILLS]
    if not retired:
        return names
    print(
        f"varde setup sync: ignoring retired skills in saved [sync].skills: "
        f"{', '.join(retired)}",
        file=sys.stderr,
    )
    return [name for name in names if name not in RETIRED_SKILLS] or None


def read(config: Any) -> SavedSettings:
    document = getattr(config, "document", config)
    value = document.get("sync")
    if value is None:
        return SavedSettings()
    if not isinstance(value, dict):
        raise ValueError("the [sync] config must be a table")

    def read_path(key: str) -> Path | None:
        item = value.get(key)
        if item is None:
            return None
        if not isinstance(item, str):
            raise ValueError(f"[sync].{key} must be a string")
        return Path(item)

    mode = value.get("link_mode")
    if mode is not None and not isinstance(mode, str):
        raise ValueError("[sync].link_mode must be a string")
    selected = value.get("skills")
    if selected is not None:
        if not isinstance(selected, list) or not all(
            isinstance(item, str) for item in selected
        ):
            raise ValueError("[sync].skills must be an array of strings")
        selected = _without_retired(selected)
        if selected is not None:
            validate_skills(selected)
    presets = value.get("presets")
    if presets is not None and (
        not isinstance(presets, list) or not all(isinstance(i, str) for i in presets)
    ):
        raise ValueError("[sync].presets must be an array of strings")
    return SavedSettings(
        read_path("skills_dir"), read_path("agents_dir"), mode, selected, presets
    )


def write(
    config: Any,
    skills_dir: Path,
    agents_dir: Path,
    link_mode: str,
    selected: list[str] | None = None,
) -> None:
    document = getattr(config, "document", config)
    current = document.get("sync")
    table = dict(current) if isinstance(current, dict) else {}
    table.update(
        skills_dir=str(skills_dir), agents_dir=str(agents_dir), link_mode=link_mode
    )
    if selected is not None:
        if selected:
            table["skills"] = list(selected)
        else:
            table.pop("skills", None)
    document["sync"] = table
