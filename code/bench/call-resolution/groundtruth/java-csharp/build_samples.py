"""Build dev records and hash the external frozen sets from compiler JSONL."""

from __future__ import annotations

import json
import tomllib
from collections.abc import Iterable
from pathlib import Path

from pipeline import (
    CALL_CLASSES,
    sample_by_role,
    verification_stub,
    write_jsonl,
    write_manifest,
)


def build_samples(
    manifest_path: Path,
    raw_paths: Iterable[Path],
    dev_dir: Path,
    restricted_dir: Path,
    test_manifest_path: Path,
    *,
    seed: int,
) -> None:
    """Write 300 compiler-grounded sites per language to each required split."""
    manifest = tomllib.loads(manifest_path.read_text())
    repo_rows = manifest["repo"]
    role_by_language = {
        language: {
            row["name"]: row["role"] for row in repo_rows if row["language"] == language
        }
        for language in ("java", "csharp")
    }
    records_by_language = {language: [] for language in role_by_language}
    for path in raw_paths:
        for line in path.read_text().splitlines():
            record = json.loads(line)
            records_by_language[record["language"]].append(record)

    hashes: dict[str, str] = {}
    coverage: dict[str, object] = {}
    for language, roles in role_by_language.items():
        samples, report = sample_by_role(
            records_by_language[language], roles, seed=seed, size=300
        )
        coverage[language] = report
        dev_records = samples["dev"]
        dev_path = dev_dir / f"{language}.jsonl"
        write_jsonl(dev_path, dev_records)
        review_stubs = [
            verification_stub(record)
            for record in dev_records
            if record["ground_truth"] == "unknown"
        ]
        if review_stubs:
            write_jsonl(dev_dir / f"{language}-human-review.jsonl", review_stubs)

        test_path = restricted_dir / f"{language}.jsonl"
        digest = write_jsonl(test_path, samples["test"])
        hashes[test_path.name] = digest
        test_stubs = [
            verification_stub(record)
            for record in samples["test"]
            if record["ground_truth"] == "unknown"
        ]
        if test_stubs:
            stub_path = restricted_dir / f"{language}-human-review.jsonl"
            hashes[stub_path.name] = write_jsonl(stub_path, test_stubs)
    write_manifest(test_manifest_path, hashes, coverage, 300 // len(CALL_CLASSES))
