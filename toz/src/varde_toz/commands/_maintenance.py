"""Shared paths and rendering helpers for maintenance commands."""

from __future__ import annotations

from pathlib import Path

from varde_toz.config import config_dir, env_os, load_config, varde_toz_dir
from varde_toz.project import project_root, store_db_path


def current_project(explicit: str | None = None) -> Path:
    root = project_root(explicit or env_os("TOZ_PROJECT"))
    load_config()
    return root


def current_store(root: Path) -> Path:
    base = env_os("TOZ_CONFIG_DIR")
    return store_db_path(root, base or str(config_dir()))


def all_stores(root: Path) -> list[tuple[str, Path]]:
    bases = [config_dir()]
    configured = varde_toz_dir(root)
    if configured is not None:
        bases.append(configured)
    fallback = env_os("TOZ_FALLBACK_DIR")
    if fallback:
        bases.append(Path(fallback))
    stores = []
    for base in bases:
        try:
            for child in base.iterdir():
                path = child / "toz.db"
                if path.is_file():
                    stores.append((child.name, path))
        except OSError:
            continue
    return sorted(set(stores))


def json_enabled(args: object) -> bool:
    return bool(
        getattr(args, "json", False)
        or env_os("TOZ_JSON") not in (None, "", "0", "false")
    )


def error(message: str) -> int:
    import sys

    print(f"varde-toz: {message}", file=sys.stderr)
    return 2


def version() -> str:
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as package_version

    try:
        return package_version("varde-toz")
    except PackageNotFoundError:
        return "0.1.0"
