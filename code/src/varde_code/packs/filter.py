"""Drop excluded folders from nav_map data before packs are rendered."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from varde_code.packs import DOC_DIR

EXCLUDE_FILE = f"{DOC_DIR}/exclude.txt"


def read_excluded(root: Path) -> list[str]:
    """Return the folders in ``exclude.txt`` (one per line, ``#`` comments)."""
    target = root / EXCLUDE_FILE
    if not target.is_file():
        return []
    lines = (line.split("#", 1)[0].strip() for line in target.read_text().splitlines())
    return [line.strip("/") for line in lines if line.strip("/")]


def _is_under(path: str, folders: list[str]) -> bool:
    return any(path == folder or path.startswith(folder + "/") for folder in folders)


def _relative(path: str, root: str) -> str:
    return path.removeprefix(root + "/") if root else path


def _keeper(folders: list[str], root: str) -> Callable[[str], bool]:
    return lambda path: not _is_under(_relative(path, root), folders)


def drop_excluded(
    data: dict[str, Any], folders: list[str], root: str = ""
) -> dict[str, Any]:
    """Return ``data`` without files under ``folders`` (paths may start with root)."""
    if not folders:
        return data
    keep = _keeper(folders, root)
    result = dict(data)
    for section in ("entrypoints", "foundational_files", "symbols", "hotspots"):
        if isinstance(data.get(section), list):
            result[section] = [i for i in data[section] if keep(str(i.get("file", "")))]
    if isinstance(data.get("flows"), list):
        result["flows"] = [i for i in data["flows"] if keep(_flow_file(i))]
    if isinstance(data.get("subsystems"), list):
        result["subsystems"] = _subsystems(data["subsystems"], keep)
    if isinstance(data.get("module_layers"), dict):
        result["module_layers"] = _layers(data["module_layers"], keep)
    return result


def _flow_file(flow: dict[str, Any]) -> str:
    node = flow.get("root")
    return str(node.get("file", "")) if isinstance(node, dict) else ""


def _subsystems(
    items: list[dict[str, Any]], keep: Callable[[str], bool]
) -> list[dict[str, Any]]:
    kept = [
        {**i, "members": [m for m in i.get("members", []) if keep(m)]} for i in items
    ]
    return [item for item in kept if item["members"]]


def _layers(layers: dict[str, Any], keep: Callable[[str], bool]) -> dict[str, Any]:
    return {
        "edges": [
            e
            for e in layers.get("edges", [])
            if keep(e["from_module"]) and keep(e["to_module"])
        ],
        "cycles": [c for c in layers.get("cycles", []) if all(map(keep, c))],
    }
