"""Check Python imports against the module levels declared in layers.toml."""

from __future__ import annotations

import ast
import tomllib
from collections.abc import Iterable
from functools import cache
from pathlib import Path
from typing import Any


def load_layers(path: Path) -> dict[str, dict[str, Any]]:
    """Load module layer metadata keyed by workspace directory."""
    return tomllib.loads(path.read_text(encoding="utf-8"))["module"]


@cache
def import_modules(path: Path, modified_ns: int, size: int) -> tuple[str, ...]:
    """Return imported module names; the stat arguments key the cache."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return tuple(modules)


def file_import_roots(path: Path) -> set[str]:
    """Return the top-level package names a file imports."""
    signature = path.stat()
    modules = import_modules(path, signature.st_mtime_ns, signature.st_size)
    return {module.split(".", 1)[0] for module in modules}


def package_modules(
    workspace: Path, layers: dict[str, dict[str, Any]]
) -> dict[str, str]:
    """Map each importable package name to its layers.toml module."""
    return {
        source.name: module
        for module in layers
        for source in (workspace / module / "src").glob("*")
        if source.is_dir() and (source / "__init__.py").is_file()
    }


def violates_level(
    layers: dict[str, dict[str, Any]], module: str, imported: str
) -> bool:
    """Return whether module may not import imported (same or higher level)."""
    return layers[imported]["level"] >= layers[module]["level"]


def layer_violations(workspace: Path, files: Iterable[Path]) -> list[str]:
    """Report files importing a package at the same or a higher level.

    Files outside a layers.toml module are skipped.
    """
    layers = load_layers(workspace / "layers.toml")
    owners = package_modules(workspace, layers)
    errors: list[str] = []
    for file in files:
        relative = file.resolve().relative_to(workspace.resolve())
        module = relative.parts[0]
        if module not in layers:
            continue
        level = layers[module]["level"]
        try:
            roots = sorted(file_import_roots(file))
        except SyntaxError as error:
            errors.append(f"{relative.as_posix()}: cannot parse ({error.msg})")
            continue
        for root in roots:
            imported = owners.get(root)
            if imported is None or imported == module:
                continue
            if violates_level(layers, module, imported):
                errors.append(
                    f"{relative.as_posix()}: {module} (level {level}) "
                    f"must not import {root} ({imported}, level "
                    f"{layers[imported]['level']})"
                )
    return errors
