"""Create development data, external frozen samples, and audit manifests."""

from __future__ import annotations

import argparse
import json
import tomllib
from collections import Counter
from pathlib import Path

from export import export_all
from gt_python_ts import (
    review_stubs,
    stratified_samples,
    write_jsonl,
    write_test_manifest,
)

DEFAULT_RESTRICTED_ROOT = Path(
    "/Users/alec/source/agent-memory/projects/varde-py/working/plans/"
    "2026-10-17-quality-score-build/qs-call-audit/notes/restricted/"
    "call-audit/python-ts"
)


def generate(args: argparse.Namespace) -> dict[str, object]:
    manifest = tomllib.loads(args.manifest.read_text(encoding="utf-8"))
    seed = int(manifest["sample_seed"])
    repositories = manifest["repo"]
    records = export_all(
        manifest,
        args.checkout_root,
        args.python_tool,
        args.typescript_module,
        args.node,
    )
    samples, notes = stratified_samples(records, seed=seed, n_per_language=300)
    by_repo_role = {
        (repo["language"], repo["repo"]): repo["role"] for repo in repositories
    }

    development = {}
    frozen = {}
    summary: dict[str, object] = {"seed": seed, "languages": {}}
    for language, splits in samples.items():
        _assert_roles(language, splits, by_repo_role)
        if len(splits["dev"]) != 300 or len(splits["test"]) != 300:
            raise ValueError(f"{language} did not produce two 300-site samples")
        development[language] = splits["dev"]
        frozen[language] = splits["test"]
        counts = Counter(record["call_class"] for record in splits["dev"])
        unknown = Counter(
            record["call_class"]
            for record in splits["dev"]
            if record["ground_truth"] == "unknown"
        )
        external = Counter(
            record["call_class"]
            for record in splits["dev"]
            if record["ground_truth"] == "external"
        )
        resolution = {
            call_class: {
                "resolved": counts[call_class]
                - unknown[call_class]
                - external[call_class],
                "external": external[call_class],
                "unknown": unknown[call_class],
            }
            for call_class in sorted(counts)
        }
        summary["languages"][language] = {
            "dev_sites": len(splits["dev"]),
            "dev_repositories": sorted({record["repo"] for record in splits["dev"]}),
            "dev_call_classes": dict(sorted(counts.items())),
            "dev_unknown_dynamic_and_higher_order": {
                call_class: unknown[call_class]
                for call_class in ("dynamic", "higher_order")
            },
            "dev_resolution_by_class": resolution,
            "sample_composition": notes[language],
        }

    data_root = args.repo_root / "code/bench/call-resolution/data/dev/python-ts"
    test_files = {}
    for language in ("python", "typescript"):
        write_jsonl(data_root / f"{language}.jsonl", development[language])
        test_path = args.restricted_root / f"{language}.jsonl"
        write_jsonl(test_path, frozen[language])
        test_files[language] = test_path

    stubs = {language: review_stubs(development[language]) for language in development}
    (data_root / "verification-stubs.json").write_text(
        json.dumps(stubs, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (data_root / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    write_test_manifest(
        args.repo_root / "code/bench/call-resolution/data/test-manifest-python-ts.json",
        args.restricted_root,
        test_files,
        {language: len(records) for language, records in frozen.items()},
    )
    return summary


def _assert_roles(language, splits, by_repo_role) -> None:
    expected = {
        "dev": {
            repo
            for (repo_language, repo), role in by_repo_role.items()
            if repo_language == language and role == "dev"
        },
        "test": {
            repo
            for (repo_language, repo), role in by_repo_role.items()
            if repo_language == language and role == "test-only"
        },
    }
    for split, records in splits.items():
        actual = {record["repo"] for record in records}
        if actual != expected[split]:
            raise ValueError(
                f"{language} {split} repositories do not match the pinned roles"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--checkout-root", type=Path, required=True)
    parser.add_argument("--python-tool", type=Path, required=True)
    parser.add_argument("--typescript-module", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--restricted-root", type=Path, default=DEFAULT_RESTRICTED_ROOT)
    parser.add_argument("--node", default="node")
    args = parser.parse_args()
    summary = generate(args)
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
