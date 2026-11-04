"""Check that the parser versions documented for extraction match uv.lock."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def locked_versions(lockfile: Path) -> dict[str, str]:
    text = lockfile.read_text(encoding="utf-8")
    packages = re.split(r"(?=\[\[package\]\])", text)
    result: dict[str, str] = {}
    for package in packages:
        name = re.search(r'^name = "([^"]+)"$', package, re.MULTILINE)
        version = re.search(r'^version = "([^"]+)"$', package, re.MULTILINE)
        if name and version:
            result[name.group(1)] = version.group(1)
    return result


def documented_versions(document: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in document.read_text(encoding="utf-8").splitlines():
        cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
        if len(cells) == 2 and cells[0] and cells[1]:
            result[cells[0]] = cells[1]
    return result


def check(document: Path, lockfile: Path) -> list[str]:
    locked = locked_versions(lockfile)
    documented = documented_versions(document)
    errors = []
    for package in ("tree-sitter", "tree-sitter-language-pack", "ast-grep-py"):
        if package not in documented:
            errors.append(f"{document}: missing {package}")
        elif documented[package] != locked.get(package):
            errors.append(
                f"{package}: documented {documented[package]}, locked {locked.get(package)}"
            )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path)
    parser.add_argument("--lock", type=Path, default=Path("uv.lock"))
    args = parser.parse_args(argv)
    errors = check(args.document, args.lock)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("parser versions match uv.lock")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
