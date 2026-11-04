"""Stage only pinned source roots for the offline ground-truth exporters."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tarfile
import tomllib
from pathlib import Path


def stage_repositories(
    manifest_path: Path, cache_root: Path, checkout_root: Path
) -> None:
    manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    for repo in manifest["repo"]:
        alias = repo["checkout_alias"]
        source = cache_root / alias
        if not (source / ".git").exists():
            _clone(repo["url"], repo["pin_sha"], source)
        _pin(source, repo["pin_sha"])
        destination = checkout_root / alias
        if destination.exists():
            shutil.rmtree(destination)
        destination.mkdir(parents=True)
        paths = [*repo["source_roots"], *repo.get("config_files", [])]
        _extract(source, repo["pin_sha"], paths, destination)


def _clone(url: str, pin_sha: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "git",
            "clone",
            "--filter=blob:none",
            "--depth=1",
            "--no-checkout",
            url,
            str(destination),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(destination), "fetch", "--depth=1", "origin", pin_sha],
        check=True,
        capture_output=True,
        text=True,
    )


def _pin(source: Path, pin_sha: str) -> None:
    current = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if current != pin_sha:
        subprocess.run(
            ["git", "-C", str(source), "fetch", "--depth=1", "origin", pin_sha],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "-C", str(source), "checkout", "--detach", pin_sha],
            check=True,
            capture_output=True,
            text=True,
        )


def _extract(source: Path, pin_sha: str, paths: list[str], destination: Path) -> None:
    process = subprocess.Popen(
        ["git", "-C", str(source), "archive", "--format=tar", pin_sha, *paths],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if process.stdout is None:
        raise RuntimeError("git archive did not provide a source stream")
    with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
        archive.extractall(destination, filter="data")
    stderr = (
        process.stderr.read().decode("utf-8", errors="replace")
        if process.stderr
        else ""
    )
    status = process.wait()
    if status:
        raise RuntimeError(f"git archive failed for {pin_sha}: {stderr.strip()}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--checkout-root", type=Path, required=True)
    args = parser.parse_args()
    stage_repositories(args.manifest, args.cache_root, args.checkout_root)
    print(f"staged pinned source roots to {args.checkout_root}")


if __name__ == "__main__":
    main()
