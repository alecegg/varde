"""Helpers for safely applying eval-suite text mutations."""

from __future__ import annotations

import shutil
from pathlib import Path


def copy_skill(source: Path, destination: Path) -> None:
    shutil.rmtree(destination, ignore_errors=True)
    shutil.copytree(source, destination)


def apply_mutation(
    skill_dir: Path, file: str, remove: str, replace_with: str = ""
) -> None:
    relative = Path(file)
    if (
        not file
        or relative.is_absolute()
        or any(part in {".", ".."} for part in relative.parts)
    ):
        raise ValueError(f"invalid mutation file path: {file}")
    target = skill_dir / relative
    original = target.read_text()
    if not remove or original.count(remove) != 1:
        raise ValueError(
            f"mutation must match exactly one non-empty text span in {file}"
        )
    target.write_text(original.replace(remove, replace_with, 1))
