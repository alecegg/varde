#!/usr/bin/env python3
"""Generate a deterministic medium-sized Python and TypeScript repository."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def generate(root: Path, seed: int = 1729) -> dict[str, object]:
    if root.exists() and any(root.iterdir()):
        raise ValueError(f"fixture directory must be empty: {root}")
    root.mkdir(parents=True, exist_ok=True)
    (root / "README.md").write_text(
        "Generated medium index fixture.\n", encoding="utf-8"
    )
    source = root / "src"
    python_dir = source / "medium_py"
    typescript_dir = source / "medium_ts"
    python_dir.mkdir(parents=True)
    typescript_dir.mkdir(parents=True)
    (python_dir / "__init__.py").write_text("", encoding="utf-8")
    files: list[Path] = [root / "README.md", python_dir / "__init__.py"]
    for index in range(300):
        if index % 2 == 0:
            module_number = index // 2
            path = python_dir / f"module_{module_number:03}.py"
            dependency = module_number - 1
            import_line = (
                f"from .module_{dependency:03} import value as prior\n"
                if dependency >= 0
                else "prior = 0\n"
            )
            content = (
                f"# seed {seed}\n{import_line}value = {seed + index}\n"
                f"def calculate_{index}(amount: int) -> int:\n"
                "    return prior + amount + value\n"
            )
        else:
            module_number = index // 2
            path = typescript_dir / f"module_{module_number:03}.ts"
            dependency = module_number - 1
            import_line = (
                f"import {{ value as prior }} from './module_{dependency:03}';\n"
                if dependency >= 0
                else "const prior = 0;\n"
            )
            content = (
                f"// seed {seed}\n{import_line}export const value = {seed + index};\n"
                f"export function calculate{index}(amount: number): number {{\n"
                "  return prior + amount + value;\n}\n"
            )
        path.write_text(content, encoding="utf-8")
        files.append(path)
    main_path = source / "main.py"
    main_path.write_text(
        "from medium_py.module_000 import value\n\n"
        "def main() -> int:\n    return value\n",
        encoding="utf-8",
    )
    files.append(main_path)
    digest = hashlib.sha256()
    for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix().encode()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        data = path.read_bytes()
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return {"file_count": 300, "tree_hash": digest.hexdigest()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--seed", type=int, default=1729)
    args = parser.parse_args()
    print(json.dumps(generate(args.directory, args.seed), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
