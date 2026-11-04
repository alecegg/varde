"""Fetch pinned corpus repositories and create immutable tree snapshots.

Every fetch leaves ``FETCH_HEAD`` and a local ``refs/heads/pinned`` ref on the
verified pin, so log and history walks start from a real ref.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from manifest import load_manifest

DENIED_LICENSES = (
    "GNU GENERAL PUBLIC LICENSE",
    "GNU AFFERO GENERAL PUBLIC LICENSE",
    "BUSINESS SOURCE LICENSE",
    "BUSL",
    "SERVER SIDE PUBLIC LICENSE",
    "SSPL",
)
LICENSE_MARKERS = {
    "BSD-2-Clause": (),
    "BSD-3-Clause": (),
    "MIT": (
        "MIT LICENSE",
        "PERMISSION IS HEREBY GRANTED",
        "FREE OF CHARGE",
        "THE SOFTWARE IS PROVIDED AS IS",
    ),
    "Apache-2.0": (
        "APACHE LICENSE",
        "VERSION 2.0",
        "TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION",
    ),
    "ISC": (
        "ISC LICENSE",
        "PERMISSION TO USE, COPY, MODIFY, AND/OR DISTRIBUTE",
        "THE SOFTWARE IS PROVIDED AS IS",
    ),
    "MPL-2.0": ("MOZILLA PUBLIC LICENSE", "VERSION 2.0"),
    "EPL-2.0": ("ECLIPSE PUBLIC LICENSE", "VERSION 2.0"),
    "curl": ("COPYRIGHT AND PERMISSION NOTICE", "THE CURL LICENSE"),
}
PINNED_REF = "refs/heads/pinned"
FULL_HISTORY_ROLES = frozenset({"history", "pairs"})


class FetchError(RuntimeError):
    """Raised when a pinned repository cannot be verified or snapshotted."""


def check_license(text: str, expected_spdx: str) -> None:
    """Check a repository's LICENSE text for prohibited or mismatched families."""
    upper = text.upper()
    if any(term in upper for term in DENIED_LICENSES):
        raise FetchError(
            "LICENSE text contains a prohibited GPL, AGPL, BUSL, or SSPL license"
        )
    markers = LICENSE_MARKERS.get(expected_spdx)
    if markers is None:
        raise FetchError(f"unsupported or unverified SPDX license: {expected_spdx}")
    if expected_spdx in {"BSD-2-Clause", "BSD-3-Clause"}:
        source_clause = "REDISTRIBUTIONS OF SOURCE CODE" in upper
        binary_clause = "REDISTRIBUTIONS IN BINARY FORM" in upper
        endorsement_clause = "NEITHER THE NAME" in upper
        if expected_spdx == "BSD-2-Clause":
            matches = source_clause and binary_clause and not endorsement_clause
        else:
            matches = source_clause and binary_clause and endorsement_clause
    else:
        matches = all(marker in upper for marker in markers)
    if not matches:
        raise FetchError(f"LICENSE text does not identify {expected_spdx}")


def _git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise FetchError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout.strip()


def tree_digest(repository: Path, revision: str = PINNED_REF) -> str:
    """Hash the canonical recursive tree listing at the pinned revision."""
    listing = _git(repository, "ls-tree", "-r", "--full-tree", revision)
    return hashlib.sha256(listing.encode()).hexdigest()


def _fetch_commit(
    repository: Path, url: str, sha: str, depth: int | None = None
) -> None:
    """Fetch one commit, optionally limiting its ancestry to ``depth``."""
    command = ["fetch", "--filter=blob:none"]
    if depth is not None:
        command.append(f"--depth={depth}")
    _git(repository, *command, url, sha)
    actual = _git(repository, "rev-parse", "FETCH_HEAD")
    if actual != sha:
        raise FetchError(f"fetched {actual}, expected {sha}")


def needs_full_history(repo: dict[str, Any]) -> bool:
    """Return whether an entry needs commit ancestry or history cutoffs.

    One full-history role is enough, and a cutoff cannot be checked without
    ancestry.
    """
    if set(repo["roles"]) & FULL_HISTORY_ROLES:
        return True
    return bool(repo["history_cutoffs"])


def _fetch_full_history(checkout: Path, repo: dict[str, Any]) -> None:
    """Fetch the pin's full ancestry and every history cutoff."""
    if _git(checkout, "rev-parse", "--is-shallow-repository") == "true":
        _git(
            checkout,
            "fetch",
            "--unshallow",
            "--filter=blob:none",
            repo["url"],
            repo["pin_sha"],
        )
    else:
        _git(checkout, "fetch", "--filter=blob:none", repo["url"])
    for cutoff in repo["history_cutoffs"]:
        _fetch_commit(checkout, repo["url"], cutoff)


def _fetch_pin(checkout: Path, repo: dict[str, Any]) -> None:
    """Leave FETCH_HEAD on the pin, shallow unless roles need ancestry."""
    if not needs_full_history(repo):
        _fetch_commit(checkout, repo["url"], repo["pin_sha"], depth=1)
        return
    _fetch_commit(checkout, repo["url"], repo["pin_sha"])
    _fetch_full_history(checkout, repo)
    _fetch_commit(checkout, repo["url"], repo["pin_sha"])


def _license_text(repository: Path, revision: str) -> str:
    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"):
        result = subprocess.run(
            ["git", "-C", str(repository), "show", f"{revision}:{name}"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout
    raise FetchError("pinned repository has no root LICENSE or COPYING file")


def _open_checkout(cache: Path, name: str) -> Path:
    """Return the cache checkout for an entry, initializing it if needed."""
    checkout = cache / name.replace("/", "__")
    checkout.mkdir(parents=True, exist_ok=True)
    if not (checkout / ".git").exists():
        _git(checkout, "init", "--quiet")
    return checkout


def _check_pin_unchanged(
    checkout: Path, name: str, pin_sha: str, tree_hash: str
) -> None:
    """Fail when a cached pin's recorded tree digest no longer matches."""
    metadata_path = checkout / ".varde-corpus.json"
    if not metadata_path.exists():
        return
    previous = json.loads(metadata_path.read_text(encoding="utf-8"))
    if previous.get("pin_sha") == pin_sha and previous.get("tree_digest") != tree_hash:
        raise FetchError(
            f"{name}: pinned tree changed; upstream may have been force-moved"
        )


def _extract_snapshot(checkout: Path, revision: str, snapshot: Path) -> None:
    """Extract a revision's tree into ``snapshot`` through a temporary tar file."""
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=snapshot.parent, delete=False) as archive:
        archive_path = Path(archive.name)
    try:
        result = subprocess.run(
            ["git", "-C", str(checkout), "archive", "--format=tar", revision],
            check=True,
            capture_output=True,
        )
        archive_path.write_bytes(result.stdout)
        snapshot.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["tar", "-xf", str(archive_path), "-C", str(snapshot)], check=True
        )
    finally:
        archive_path.unlink(missing_ok=True)


def fetch_repository(
    repo: dict[str, Any], cache: Path, snapshot_root: Path
) -> dict[str, str]:
    """Fetch one exact commit, check its license, and archive its tree."""
    if repo["status"] != "verified" or not re.fullmatch(
        r"[0-9a-f]{40,64}", repo["pin_sha"]
    ):
        raise FetchError(f"{repo['name']}: candidate is not pinned and verified")
    checkout = _open_checkout(cache, repo["name"])
    _fetch_pin(checkout, repo)
    actual = _git(checkout, "rev-parse", "FETCH_HEAD")
    _git(checkout, "update-ref", PINNED_REF, actual)
    tree_hash = tree_digest(checkout, actual)
    _check_pin_unchanged(checkout, repo["name"], actual, tree_hash)
    check_license(_license_text(checkout, actual), repo["spdx"])
    _extract_snapshot(checkout, actual, snapshot_root / repo["name"].replace("/", "__"))
    record = {
        "url": repo["url"],
        "pin_sha": actual,
        "tree_digest": tree_hash,
        "history_cutoffs": repo["history_cutoffs"],
    }
    (checkout / ".varde-corpus.json").write_text(
        json.dumps(record, sort_keys=True) + "\n", encoding="utf-8"
    )
    return record


def fetch_all(
    manifest_path: Path, cache: Path, snapshot_root: Path
) -> list[dict[str, str]]:
    """Fetch every verified manifest entry into cache and snapshots."""
    manifest = load_manifest(manifest_path)
    cache.mkdir(parents=True, exist_ok=True)
    snapshot_root.mkdir(parents=True, exist_ok=True)
    return [
        fetch_repository(repo, cache, snapshot_root)
        for repo in manifest["repositories"]
        if repo["status"] == "verified"
    ]


def main() -> int:
    """Fetch the manifest into the configured external cache."""
    manifest_path = Path(__file__).with_name("manifest.toml")
    cache = Path(
        os.environ.get("VARDE_BENCH_CACHE", Path.home() / ".cache" / "varde" / "bench")
    )
    with tempfile.TemporaryDirectory(prefix="varde-corpus-snapshots-") as snapshots:
        records = fetch_all(manifest_path, cache, Path(snapshots))
    for record in records:
        print(f"{record['pin_sha']} {record['tree_digest']} {record['url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
