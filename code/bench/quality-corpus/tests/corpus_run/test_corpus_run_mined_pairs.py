"""Behaviour tests for the mined refactor-pair candidates of cd-networked-run."""

from __future__ import annotations

import json
import re
from pathlib import Path

from corpus.manifest import load_manifest

QUALITY_CORPUS = Path(__file__).resolve().parents[2]
MANIFEST = QUALITY_CORPUS / "corpus" / "manifest.toml"
MINED = QUALITY_CORPUS / "pairs" / "mined"
SHA = re.compile(r"^[0-9a-f]{40}$")
REQUIRED = (
    "repo",
    "pin_sha",
    "parent_sha",
    "child_sha",
    "changed_files",
    "changed_functions",
    "intent_evidence",
    "filters_passed",
    "language",
    "pair_group_id",
    "pair_group",
    "license",
)


def _pairs_repositories() -> dict[str, dict]:
    data = load_manifest(MANIFEST)
    return {
        repo["name"]: repo
        for repo in data["repositories"]
        if repo["roles"] == ["pairs"]
    }


def _records() -> list[tuple[Path, int, dict]]:
    found = []
    for path in sorted(MINED.glob("*/*.jsonl")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                found.append((path, number, json.loads(line)))
    return found


def test_mined_records_carry_provenance_and_license() -> None:
    pairs = _pairs_repositories()
    records = _records()
    assert records
    for path, number, record in records:
        where = f"{path}:{number}"
        for field in REQUIRED:
            assert record.get(field), f"{where}: missing {field}"
        assert record["repo"] in pairs, where
        repo = pairs[record["repo"]]
        assert SHA.fullmatch(record["pin_sha"]), where
        assert record["pin_sha"] == repo["pin_sha"], where
        assert record["license"] == repo["spdx"], where
        assert SHA.fullmatch(record["parent_sha"]), where
        assert SHA.fullmatch(record["child_sha"]), where
        assert record["language"] == path.parent.name, where
        assert all(
            isinstance(item, str) and item for item in record["changed_files"]
        ), where
        assert record["intent_evidence"]["message"].strip(), where
        group = record["pair_group"]
        assert group["kind"] == "refactor", where
        assert group["id"] == record["pair_group_id"], where
        assert group["repository"] == record["repo"], where
        assert group["samples"] == [
            f"{record['child_sha']}:before",
            f"{record['child_sha']}:after",
        ], where


def test_every_pairs_repository_has_a_mining_outcome() -> None:
    pairs = _pairs_repositories()
    summary = json.loads((MINED / "summary.json").read_text(encoding="utf-8"))
    outcomes = summary["repositories"]
    records_by_repo: dict[str, list[dict]] = {}
    for _, _, record in _records():
        records_by_repo.setdefault(record["repo"], []).append(record)
    assert set(outcomes) == set(pairs)
    for name, outcome in outcomes.items():
        assert outcome["pin_sha"] == pairs[name]["pin_sha"]
        records = records_by_repo.get(name, [])
        assert len(records) == outcome["accepted"]
        if outcome["status"] == "complete":
            assert records
        else:
            assert outcome["status"] == "time-capped, partial"
            assert outcome["accepted"] >= 0


def test_mined_summary_agrees_with_the_record_files() -> None:
    summary = json.loads((MINED / "summary.json").read_text(encoding="utf-8"))
    records = _records()
    assert summary["target_per_language"] == 6
    assert summary["pairs_repositories"] == len(_pairs_repositories())
    assert summary["completed_repositories"] == len(_pairs_repositories()) - 1
    assert summary["time_capped_repositories"] == 1
    for language, stats in summary["languages"].items():
        in_language = [
            record for path, _, record in records if path.parent.name == language
        ]
        assert stats["accepted"] == len(in_language), language
        assert stats["repositories"] == len({record["repo"] for record in in_language})
        assert stats["partial_repositories"] == sum(
            item["language"] == language and item["status"] == "time-capped, partial"
            for item in summary["repositories"].values()
        )
        assert stats["intent_matches"] >= stats["accepted"], language
        assert stats["commits_walked"] >= stats["intent_matches"], language
        for stage, counts in stats["filters"].items():
            assert 0 <= counts["passed"] <= counts["evaluated"] > 0, (
                f"{language}:{stage}"
            )
    assert sum(stats["accepted"] for stats in summary["languages"].values()) == len(
        records
    )


def test_reported_pair_counts_match_the_mined_records() -> None:
    report = (QUALITY_CORPUS / "corpus" / "verified" / "REPORT.md").read_text(
        encoding="utf-8"
    )
    summary = json.loads((MINED / "summary.json").read_text(encoding="utf-8"))
    for language, stats in summary["languages"].items():
        assert f"| {language} | {stats['repositories']} |" in report, language
        assert f"| {stats['accepted']} |" in report, language
    assert "## Category (c): mined refactor pairs" in report
    assert "Languages short of 6 pairs: none." in report
    assert "dotnet/roslyn" in summary["repositories"]
    assert "time-capped, partial" in report
