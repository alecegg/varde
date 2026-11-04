"""Add pinned local C# dev repos to the dev set without touching the test split.

Runs the Roslyn exporter on dev repos cloned under a local reference root (no
fetch), pools their sites with the existing dev records, and resamples only the
dev split. Test records, restricted files and test manifests are never written.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import tomllib
from pathlib import Path

from export_repositories import _verify_license
from pipeline import sample_by_role, verification_stub, write_jsonl
from tools import prepare_csharp_references, run_csharp


def csharp_roles(repos: list[dict[str, str]]) -> dict[str, str]:
    return {row["name"]: row["role"] for row in repos if row["language"] == "csharp"}


def pooled_records(
    existing: list[dict], exported: list[dict], roles: dict[str, str]
) -> list[dict]:
    """Existing dev records plus new exports, kept only for repos with a role."""
    return [row for row in existing + exported if row["repo"] in roles]


def git_output(repo: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603 - Fixed read-only git queries on a pinned local clone.
        ["git", "-C", str(repo), *args],  # noqa: S607
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def verify_pin(entry: dict[str, str], checkout: Path) -> None:
    if git_output(checkout, "rev-parse", "HEAD").strip() != entry["sha"]:
        raise ValueError(f"pin mismatch for {entry['name']}")
    if git_output(checkout, "status", "--porcelain").strip():
        raise ValueError(f"dirty checkout for {entry['name']}")
    text = git_output(checkout, "show", f"{entry['sha']}:{entry['license_file']}")
    _verify_license(text, entry["license"], entry["license_first_nonblank_line"])


def export_repo(entry: dict[str, str], checkout: Path, env_root: Path) -> Path:
    verify_pin(entry, checkout)
    output = env_root / "records" / f"csharp-{checkout.name}.jsonl"
    source = checkout / entry["source_root"]
    references = prepare_csharp_references(checkout, source, env_root)
    run_csharp(entry["name"], checkout, source, output, env_root, references=references)
    return output


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--repo-manifest", type=Path, default=root / "repos/java-csharp.toml"
    )
    parser.add_argument("--reference-root", type=Path, required=True)
    parser.add_argument("--env-root", type=Path, required=True)
    parser.add_argument("--dev-dir", type=Path, default=root / "data/dev/java-csharp")
    parser.add_argument("--add", nargs="+", required=True, help="repo names to export")
    parser.add_argument(
        "--skip",
        nargs="*",
        default=[],
        help="repos too large to evaluate; drop their sites",
    )
    parser.add_argument("--seed", type=int, default=1701)
    args = parser.parse_args()
    repos = tomllib.loads(args.repo_manifest.read_text())["repo"]
    roles = {
        name: role
        for name, role in csharp_roles(repos).items()
        if name not in args.skip
    }
    exported: list[dict] = []
    for entry in repos:
        if entry["name"] in args.add:
            checkout = args.reference_root / entry["name"].split("/")[1]
            exported += read_jsonl(export_repo(entry, checkout, args.env_root))
    dev_path = args.dev_dir / "csharp.jsonl"
    pool = pooled_records(read_jsonl(dev_path), exported, roles)
    samples, _ = sample_by_role(pool, roles, seed=args.seed, size=300)
    write_jsonl(dev_path, samples["dev"])
    stubs = [
        verification_stub(r) for r in samples["dev"] if r["ground_truth"] == "unknown"
    ]
    write_jsonl(args.dev_dir / "csharp-human-review.jsonl", stubs)


if __name__ == "__main__":
    main()
