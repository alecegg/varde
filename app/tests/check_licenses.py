"""Check the runtime dependency closure against the Python license policy."""

from __future__ import annotations

import tomllib
from pathlib import Path

from varde_core.layout import project_dirs

ROOT = Path(__file__).resolve().parents[2]
ALLOWED = {
    "MIT",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "Apache-2.0",
    "ISC",
    "PSF-2.0",
    "PSF-2.0 OR GPL-2.0-only",
    "MPL-2.0",
    "Unlicense",
}
# SPDX values for the runtime dependency set.
THIRD_PARTY = {
    "ast-grep-py": "MIT",
    "beautifulsoup4": "MIT",
    "blake3": "Apache-2.0",
    "markdownify": "MIT",
    "pyyaml": "MIT",
    "six": "MIT",
    "soupsieve": "MIT",
    "tomlkit": "MIT",
    "tree-sitter": "MIT",
    "tree-sitter-language-pack": "MIT",
    "wasmtime": "Apache-2.0 WITH LLVM-exception",
    "watchdog": "Apache-2.0",
}
LOCAL = {
    "varde",
    "varde-core",
    "varde-code",
    "varde-data",
    "varde-knowledge",
    "varde-workflow",
    "varde-toz",
    "varde-learn",
    "varde-dev",
    "varde-visualize",
    "varde-design",
}
# The toz port predates adding SPDX metadata to its project file; its package
# license is recorded as MIT in the packaging spike's license inventory.
LOCAL_LICENSES = {"varde-toz": "MIT"}


def runtime_packages() -> dict[str, dict]:
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    packages = {package["name"]: package for package in lock["package"]}
    found: dict[str, dict] = {}
    pending = ["varde"]
    while pending:
        name = pending.pop()
        if name in found:
            continue
        package = packages[name]
        found[name] = package
        pending.extend(dep["name"] for dep in package.get("dependencies", []))
    return found


def main() -> int:
    packages = runtime_packages()
    local_projects = project_dirs(ROOT)
    errors: list[str] = []
    for name in sorted(packages):
        if name in LOCAL:
            module_root = local_projects[name]
            project = tomllib.loads((module_root / "pyproject.toml").read_text())[
                "project"
            ]
            expression = project.get("license") or LOCAL_LICENSES.get(name)
        else:
            expression = THIRD_PARTY.get(name)
        if expression is None:
            errors.append(f"{name}: missing license policy entry")
            continue
        # WITH exceptions retain the SPDX base; an OR accepts any allowed option.
        options = [
            part.strip().split(" WITH ", 1)[0] for part in expression.split(" OR ")
        ]
        if not any(option in ALLOWED for option in options):
            errors.append(f"{name}: no allowed license in {expression!r}")
    if errors:
        print("license policy violations:")
        print("\n".join(f"  - {error}" for error in errors))
        return 1
    print(f"license policy passed for {len(packages)} runtime packages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
