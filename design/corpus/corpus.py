"""Calibration corpus tool: pin hashes into manifest.json and fetch third-party pages.

Usage (from the repository root):
    python design/corpus/corpus.py fetch DEST   # download, verify hashes
    python design/corpus/corpus.py pin [--memory-root DIR]   # refresh sha256

Third-party files are never committed; only URL, commit, licence and sha256 are.
Run `fetch` into a directory outside the repository (for example
/tmp/claude-501/design-corpus). Maintainer tool; not part of the shipped package.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path

MANIFEST = Path(__file__).with_name("manifest.json")
Fetch = Callable[[str], bytes]


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def raw_url(repo: str, commit: str, path: str) -> str:
    return f"https://raw.githubusercontent.com/{repo}/{commit}/{path}"


def http_fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:  # noqa: S310
        return response.read()


def source_paths(page: dict) -> list[str]:
    return [page["path"], *page["companions"]]


def pin_page(page: dict, fetch: Fetch) -> None:
    """Fill page['sha256'] (path -> sha256) from the pinned commit."""
    page["sha256"] = {
        path: sha256_hex(fetch(raw_url(page["repo"], page["commit"], path)))
        for path in source_paths(page)
    }


def fetch_page(page: dict, dest: Path, fetch: Fetch) -> list[str]:
    """Write the page files under dest/<id>/ and return paths whose hash differs."""
    mismatched = []
    for path in source_paths(page):
        data = fetch(raw_url(page["repo"], page["commit"], path))
        target = dest / page["id"] / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        if sha256_hex(data) != page["sha256"].get(path):
            mismatched.append(path)
    return mismatched


def pin_varde_pages(manifest: dict, memory_root: Path) -> None:
    pages = sorted((memory_root / manifest["varde"]["root"]).rglob("*.html"))
    base = memory_root / manifest["varde"]["root"]
    manifest["varde"]["pages"] = {
        str(p.relative_to(base)): sha256_hex(p.read_bytes()) for p in pages
    }


def load() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def save(manifest: dict) -> None:
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    fetch_cmd = sub.add_parser("fetch")
    fetch_cmd.add_argument("dest", type=Path)
    pin_cmd = sub.add_parser("pin")
    pin_cmd.add_argument("--memory-root", type=Path)
    args = parser.parse_args(argv)
    manifest = load()
    if args.command == "pin":
        for page in manifest["third_party"]:
            pin_page(page, http_fetch)
        if args.memory_root:
            pin_varde_pages(manifest, args.memory_root)
        save(manifest)
        return 0
    bad = [
        f"{page['id']}: {path}"
        for page in manifest["third_party"]
        for path in fetch_page(page, args.dest, http_fetch)
    ]
    print("\n".join(bad) if bad else "all hashes match")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
