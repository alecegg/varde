"""Verify protected test-set and review-stub hashes without loading their labels."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def verify_manifest(manifest_path: Path, notes_root: Path) -> list[str]:
    manifest = json.loads(manifest_path.read_text())
    failures: list[str] = []
    for item in manifest["sets"]:
        for path_key, hash_key in (
            ("path", "sha256"),
            ("review_stubs_path", "review_stubs_sha256"),
        ):
            relative = Path(item[path_key]).relative_to("notes")
            artifact = notes_root / relative
            if not artifact.is_file():
                failures.append(f"missing {item[path_key]}")
                continue
            actual = hashlib.sha256(artifact.read_bytes()).hexdigest()
            if actual != item[hash_key]:
                failures.append(f"hash mismatch {item[path_key]}")
    return failures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("notes_root", type=Path)
    args = parser.parse_args()
    failures = verify_manifest(args.manifest, args.notes_root)
    if failures:
        raise SystemExit("\n".join(failures))
    print("protected artifacts match sha256 manifest")


if __name__ == "__main__":
    main()
