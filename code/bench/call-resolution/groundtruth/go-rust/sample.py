"""Write balanced dev sets and protected test sets plus content hashes."""

from __future__ import annotations

import argparse
import hashlib
import json
import tomllib
from collections import Counter
from pathlib import Path
from typing import Any

from export import class_quotas, sample_sites

ROOT = Path(__file__).resolve().parents[2]
REPO_MANIFEST = ROOT / "repos" / "go-rust.toml"
DEV_ROOT = ROOT / "data" / "dev" / "go-rust"
TEST_MANIFEST = ROOT / "data" / "test-manifest-go-rust.json"
PLAN_NOTES = Path(
    "/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-17-quality-score-build/qs-call-audit/notes"
)


def repo_roles(path: Path = REPO_MANIFEST) -> dict[str, str]:
    with path.open("rb") as stream:
        repos = tomllib.load(stream)["repo"]
    return {repo["name"]: repo["role"] for repo in repos}


def review_stubs(sites: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unresolved = [
        site
        for site in sites
        if site["call_class"] in {"dynamic", "higher_order"}
        or site["ground_truth"] == "unknown"
    ]
    return [
        {
            "site": {
                key: site[key]
                for key in ("repo", "file", "line", "call_name", "call_class")
            },
            "reviewers": [
                {"reviewer": "reviewer-a", "ground_truth": None, "rationale": None},
                {"reviewer": "reviewer-b", "ground_truth": None, "rationale": None},
            ],
            "agreement": None,
            "adjudication": None,
        }
        for site in unresolved
    ]


def jsonl_bytes(sites: list[dict[str, Any]]) -> bytes:
    return "".join(
        json.dumps(site, sort_keys=True, separators=(",", ":")) + "\n" for site in sites
    ).encode()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def sample_all(
    candidates: list[dict[str, Any]],
    restricted_root: Path,
    seed: int,
    languages: list[str],
) -> dict[str, Any]:
    roles = repo_roles()
    manifest: dict[str, Any] = {"schema_version": 1, "seed": seed, "sets": []}
    if TEST_MANIFEST.is_file():
        manifest = json.loads(TEST_MANIFEST.read_text())
        manifest["sets"] = [
            item for item in manifest["sets"] if item["language"] not in languages
        ]
    dev_counts: dict[str, int] = {}
    dev_classes: dict[str, dict[str, int]] = {}
    dev_shortfalls: dict[str, dict[str, int]] = {}
    for language in languages:
        dev = sample_sites(candidates, roles, language, "dev", seed)
        test = sample_sites(candidates, roles, language, "test-only", seed)
        if any(not isinstance(site.get("call_name"), str) for site in dev + test):
            raise ValueError(f"{language} sample is missing a call_name")
        dev_content = jsonl_bytes(dev)
        test_content = jsonl_bytes(test)
        test_stubs = json_bytes(review_stubs(test))
        dev_path = DEV_ROOT / f"{language}.jsonl"
        restricted_path = restricted_root / f"{language}-test.jsonl"
        restricted_stubs = restricted_root / f"{language}-review-stubs.json"
        write(dev_path, dev_content)
        dev_counts[language] = len(dev)
        dev_classes[language] = class_counts(dev)
        dev_shortfalls[language] = class_shortfalls(dev)
        write(restricted_path, test_content)
        write(restricted_stubs, test_stubs)
        manifest["sets"].append(
            {
                "language": language,
                "path": f"notes/restricted/call-audit/go-rust/{language}-test.jsonl",
                "target_sites": len(dev),
                "sites": len(test),
                "class_counts": class_counts(test),
                "class_shortfalls": class_shortfalls(test),
                "sha256": hashlib.sha256(test_content).hexdigest(),
                "review_stubs_path": (
                    f"notes/restricted/call-audit/go-rust/{language}-review-stubs.json"
                ),
                "review_stubs_sha256": hashlib.sha256(test_stubs).hexdigest(),
            }
        )
    manifest_content = json_bytes(manifest)
    write(TEST_MANIFEST, manifest_content)
    return {
        "dev_counts": dev_counts,
        "dev_class_counts": dev_classes,
        "dev_class_shortfalls": dev_shortfalls,
        "test_manifest_sha256": hashlib.sha256(manifest_content).hexdigest(),
    }


def class_counts(sites: list[dict[str, Any]]) -> dict[str, int]:
    """Report achieved class counts so quota shortfalls stay visible."""
    return dict(sorted(Counter(site["call_class"] for site in sites).items()))


def class_shortfalls(sites: list[dict[str, Any]], target: int = 300) -> dict[str, int]:
    """Report how far each class fell short of its ``target`` quota."""
    counts = Counter(site["call_class"] for site in sites)
    quotas = class_quotas(target)
    return {
        kind: quotas[kind] - counts.get(kind, 0)
        for kind in quotas
        if counts.get(kind, 0) < quotas[kind]
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidates", type=Path)
    parser.add_argument(
        "--restricted-root",
        type=Path,
        default=PLAN_NOTES / "restricted" / "call-audit" / "go-rust",
    )
    parser.add_argument("--seed", type=int, default=1701)
    parser.add_argument("--language", choices=("go", "rust"), action="append")
    args = parser.parse_args()
    candidates = [
        json.loads(line) for line in args.candidates.read_text().splitlines() if line
    ]
    languages = args.language or ["go", "rust"]
    print(
        json.dumps(
            sample_all(candidates, args.restricted_root, args.seed, languages),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
