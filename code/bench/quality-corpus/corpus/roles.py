"""Check that corpus roles do not overlap protected repository sets."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from manifest import ManifestError, load_manifest


def protected_repositories(directory: Path) -> set[str]:
    """Read repo names and URLs reserved by call-resolution manifests."""
    protected: set[str] = set()
    if not directory.exists():
        return protected
    for path in sorted(directory.glob("*.toml")):
        try:
            content = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ManifestError(
                f"cannot read protected repository file {path}: {exc}"
            ) from exc
        _collect_repo_ids(content, protected)
    return protected


def _collect_repo_ids(value: Any, found: set[str]) -> None:
    if isinstance(value, dict):
        for key in ("name", "url", "repo", "repository"):
            item = value.get(key)
            if isinstance(item, str):
                found.add(item.rstrip("/"))
        for item in value.values():
            _collect_repo_ids(item, found)
    elif isinstance(value, list):
        for item in value:
            _collect_repo_ids(item, found)


def check_roles(manifest_path: Path, protected_dir: Path) -> list[str]:
    """Return calibration-role conflicts with protected repository manifests."""
    manifest = load_manifest(manifest_path)
    protected = protected_repositories(protected_dir)
    errors = []
    for repo in manifest["repositories"]:
        if "calibration" not in repo["roles"]:
            continue
        identities = {repo["name"], repo["url"].rstrip("/")}
        if identities & protected:
            errors.append(
                f"{repo['name']}: calibration role conflicts with "
                "call-resolution corpus"
            )
    return errors


def main() -> int:
    """Validate roles against this checkout's call-resolution corpus."""
    root = Path(__file__).resolve().parents[2]
    manifest = Path(__file__).with_name("manifest.toml")
    conflicts = check_roles(manifest, root / "call-resolution" / "repos")
    for conflict in conflicts:
        print(conflict)
    return int(bool(conflicts))


if __name__ == "__main__":
    raise SystemExit(main())
