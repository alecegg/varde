"""What one daemon serves."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Project:
    """The working dir (plans, docs, mail), its repository and the config dir."""

    config_dir: Path
    working: Path
    repository: Path
