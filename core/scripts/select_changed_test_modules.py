"""Select test-fast modules affected by changed workspace files."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _layers(root: Path) -> dict[str, dict[str, object]]:
    return tomllib.loads((root / "layers.toml").read_text())["module"]


def _test_modules(root: Path, layers: dict[str, dict[str, object]]) -> list[str]:
    return [
        module
        for module in layers
        if (tests := root / module / "tests").is_dir()
        and any(
            path.is_file()
            and (path.name.startswith("test_") or path.name.endswith("_test.py"))
            for path in tests.rglob("*.py")
        )
    ]


def select_modules(
    changed_paths: list[str],
    dependencies: dict[str, set[str]],
    modules: list[str],
    workspace_modules: list[str],
) -> list[str]:
    """Return changed pytest modules and their reverse dependency closure."""
    if not changed_paths or any(
        path == "layers.toml" or Path(path).parts[0] == "core"
        for path in changed_paths
        if Path(path).parts
    ):
        return modules.copy()

    changed = set()
    for path in changed_paths:
        parts = Path(path).parts
        if not parts or parts[0] not in workspace_modules:
            return modules.copy()
        changed.add(parts[0])

    selected = set(changed)
    while True:
        dependents = {
            module for module, required in dependencies.items() if required & selected
        }
        updated = selected | dependents
        if updated == selected:
            return [module for module in modules if module in selected]
        selected = updated


def _module_dependencies(
    root: Path, layers: dict[str, dict[str, object]]
) -> dict[str, set[str]]:
    distribution_to_module = {
        str(layer["dist"]).lower().replace("_", "-"): module
        for module, layer in layers.items()
    }
    dependencies = {module: set() for module in layers}
    for module in layers:
        metadata = tomllib.loads((root / module / "pyproject.toml").read_text())
        requirements = list(metadata["project"].get("dependencies", []))
        requirements.extend(
            item
            for group in metadata["project"].get("optional-dependencies", {}).values()
            for item in group
        )
        requirements.extend(
            item
            for group in metadata.get("dependency-groups", {}).values()
            for item in group
        )
        for requirement in requirements:
            match = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", requirement)
            if match:
                dependency = match.group().lower().replace("_", "-")
                if dependency in distribution_to_module:
                    dependencies[module].add(distribution_to_module[dependency])
    for coupling in tomllib.loads((root / "layers.toml").read_text()).get(
        "coupling", []
    ):
        dependencies[coupling["from"]].add(coupling["to"])
    return dependencies


def _changed_paths(root: Path) -> list[str]:
    base = subprocess.check_output(
        ["git", "merge-base", "HEAD", "main"],  # noqa: S607
        cwd=root,
        text=True,
    ).strip()
    changed = subprocess.check_output(  # noqa: S603
        ["git", "diff", "--name-only", base],  # noqa: S607
        cwd=root,
        text=True,
    ).splitlines()
    untracked = subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard"],  # noqa: S607
        cwd=root,
        text=True,
    ).splitlines()
    return sorted(set(changed) | set(untracked))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true", help="list test-fast modules")
    args = parser.parse_args()
    layers = _layers(ROOT)
    modules = _test_modules(ROOT, layers)
    if args.list:
        print(" ".join(modules))
        return 0
    selected = select_modules(
        _changed_paths(ROOT),
        _module_dependencies(ROOT, layers),
        modules,
        list(layers),
    )
    print(" ".join(selected))
    return 0


if __name__ == "__main__":
    sys.exit(main())
