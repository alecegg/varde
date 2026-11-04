"""Behaviour tests: REPORT.md counts must agree with the verified manifest."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

from corpus.manifest import load_manifest

QUALITY_CORPUS = Path(__file__).resolve().parents[2]
MANIFEST = QUALITY_CORPUS / "corpus" / "manifest.toml"
VERIFIED = QUALITY_CORPUS / "corpus" / "verified" / "verified.json"
REPORT = QUALITY_CORPUS / "corpus" / "verified" / "REPORT.md"
START = "<!-- counts:start -->"
END = "<!-- counts:end -->"
RELEASE_GROUPS = {
    "Python": ("Python",),
    "TypeScript/JavaScript": ("TypeScript", "JavaScript", "TSX"),
    "Java": ("Java",),
    "Go": ("Go",),
    "Rust": ("Rust",),
    "C#": ("C#",),
    "C++": ("C++",),
}


def _release_group(languages: list[str]) -> str:
    for group, members in RELEASE_GROUPS.items():
        if set(languages) & set(members):
            return group
    return languages[0]


def _tally(values: list[str]) -> dict[str, int]:
    tally: dict[str, int] = {}
    for value in values:
        tally[value] = tally.get(value, 0) + 1
    return dict(sorted(tally.items()))


def _manifest_counts() -> dict:
    repositories = load_manifest(MANIFEST)["repositories"]
    verified = [repo for repo in repositories if repo["status"] == "verified"]
    return {
        "total_candidates": len(repositories),
        "total_verified": len(verified),
        "total_excluded": len(repositories) - len(verified),
        "verified_by_language": _tally(
            [language for repo in verified for language in repo["languages"]]
        ),
        "verified_by_group": _tally(
            [_release_group(repo["languages"]) for repo in verified]
        ),
        "verified_by_role": _tally(
            [repo["roles"][0] if repo["roles"] else "none" for repo in verified]
        ),
        "calibration_by_group": _tally(
            [
                _release_group(repo["languages"])
                for repo in verified
                if repo["roles"] == ["calibration"]
            ]
        ),
        "candidates_by_group": _tally(
            [_release_group(repo["languages"]) for repo in repositories]
        ),
    }


def _reported_counts() -> dict:
    text = REPORT.read_text(encoding="utf-8")
    block = text.split(START, 1)[1].split(END, 1)[0]
    body = block.split("```toml", 1)[1].split("```", 1)[0]
    return tomllib.loads(body)


def test_report_counts_agree_with_the_manifest() -> None:
    counted = _manifest_counts()
    reported = _reported_counts()
    assert reported["total_candidates"] == counted["total_candidates"]
    assert reported["total_verified"] == counted["total_verified"]
    assert reported["total_excluded"] == counted["total_excluded"]
    for key in (
        "verified_by_language",
        "verified_by_group",
        "verified_by_role",
        "calibration_by_group",
        "candidates_by_group",
    ):
        assert reported[key] == counted[key], key


def test_report_names_every_verified_and_excluded_repository() -> None:
    text = REPORT.read_text(encoding="utf-8")
    verified = json.loads(VERIFIED.read_text(encoding="utf-8"))
    for entry in verified["repositories"]:
        assert entry["name"] in text, entry["name"]
    for entry in verified["excluded"]:
        assert entry["name"] in text, entry["name"]
        assert entry["reason"][:40] in text, entry["name"]


def test_reserved_calibration_repositories_are_verified_without_roles() -> None:
    manifest = load_manifest(MANIFEST)
    repositories = {repo["name"]: repo for repo in manifest["repositories"]}
    for name in (
        "psf/requests",
        "expressjs/express",
        "prettier/prettier",
        "typeorm/typeorm",
    ):
        assert repositories[name]["status"] == "verified"
        assert repositories[name]["roles"] == []
    calibration = json.loads(VERIFIED.read_text(encoding="utf-8"))["counts"][
        "calibration_by_group"
    ]
    assert calibration["Python"] >= 5
    assert calibration["TypeScript/JavaScript"] >= 5


def test_report_states_licenses_that_failed_and_counts_of_every_role() -> None:
    text = REPORT.read_text(encoding="utf-8")
    verified = json.loads(VERIFIED.read_text(encoding="utf-8"))
    assert "## Excluded candidates and license failures" in text
    for role, count in verified["counts"]["verified_by_role"].items():
        assert f"{role}={count}" in text, role
    assert f"{verified['counts']['total_verified']} verified of" in text
