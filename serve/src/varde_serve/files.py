"""Walk the working dir for files, never entering generated or archived trees."""

from __future__ import annotations

import os
from pathlib import Path

SKIP_DIRS = frozenset({".cache", ".git", "archive", "node_modules"})


def files_with_suffix(root: Path, suffix: str) -> list[Path]:
    """Sorted files under `root` ending in `suffix`, pruning `SKIP_DIRS`."""
    found = []
    for directory, subdirs, names in os.walk(root):
        subdirs[:] = [d for d in subdirs if d not in SKIP_DIRS]
        found.extend(Path(directory, n) for n in names if n.endswith(suffix))
    return sorted(found)
