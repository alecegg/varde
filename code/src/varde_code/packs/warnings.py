"""Pack warnings for the scan report: missing packs or a README far behind."""

from __future__ import annotations

from pathlib import Path

from varde_code.errors import ApiError
from varde_code.packs import README
from varde_code.packs.refresh import MODULES_FILE, module_path, read_modules
from varde_code.packs.status import PackStatus, collect_packs

BUILD_HINT = "run: varde map packs build"


def pack_warnings(
    statuses: list[PackStatus],
    readme_exists: bool,
    listed_missing: list[str],
    readme_max_behind: int,
) -> list[str]:
    """Warnings for a missing README, missing listed packs, or a README too far behind.

    A stale module pack alone gives no warning.
    """
    warnings = []
    if not readme_exists:
        warnings.append(f"{README} is missing; {BUILD_HINT}")
    warnings.extend(f"{path} is missing; {BUILD_HINT}" for path in listed_missing)
    warnings.extend(
        f"{README} is {status.commits_behind} commits behind; {BUILD_HINT}"
        for status in statuses
        if status.path == README and status.commits_behind >= readme_max_behind
    )
    return warnings


def _listed(root: Path) -> set[str] | None:
    if not (root / MODULES_FILE).is_file():
        return None
    return {module_path(folder) for folder in read_modules(root)}


def collect_pack_warnings(root: Path, readme_max_behind: int = 100) -> list[str]:
    """Collect pack statuses under ``root`` and return the warnings, if any."""
    try:
        listed = _listed(root)
        statuses = collect_packs(root, listed, readme_max_behind)
    except ApiError as error:
        return [f"packs status failed: {error.code}: {error.message}"]
    missing = sorted(path for path in listed or () if not (root / path).is_file())
    return pack_warnings(
        statuses, (root / README).is_file(), missing, readme_max_behind
    )
