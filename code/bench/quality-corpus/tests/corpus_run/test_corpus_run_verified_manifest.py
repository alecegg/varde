"""Behaviour tests for the verified corpus manifest of cd-networked-run."""

from __future__ import annotations

import json
import re
from pathlib import Path

from corpus.manifest import SPDX_LICENSES, load_manifest

QUALITY_CORPUS = Path(__file__).resolve().parents[2]
MANIFEST = QUALITY_CORPUS / "corpus" / "manifest.toml"
VERIFIED = QUALITY_CORPUS / "corpus" / "verified" / "verified.json"
PIN = re.compile(r"^[0-9a-f]{40}$")
TREE_DIGEST = re.compile(r"^[0-9a-f]{64}$")
LICENSE_FILE_PREFIXES = ("LICENSE", "COPYING", "MIT-LICENSE")
# EPL-2.0 is in the manifest's SPDX vocabulary but outside the permitted
# permissive set of the selection rules (MIT, BSD, Apache-2.0, ISC, MPL-2.0).
PERMISSIVE = SPDX_LICENSES - {"EPL-2.0"}
SCORED_ROLES = {"pairs", "calibration", "mutation-base"}
RELEASE_GROUPS = {
    "Python": ("Python",),
    "TypeScript/JavaScript": ("TypeScript", "JavaScript", "TSX"),
    "Java": ("Java",),
    "Go": ("Go",),
    "Rust": ("Rust",),
    "C#": ("C#",),
    "C++": ("C++",),
}


def _manifest() -> dict:
    return load_manifest(MANIFEST)


def _verified() -> dict:
    return json.loads(VERIFIED.read_text(encoding="utf-8"))


def _release_group(languages: list[str]) -> str:
    for group, members in RELEASE_GROUPS.items():
        if set(languages) & set(members):
            return group
    return languages[0]


def test_verified_entries_are_pinned_permissive_and_agree_with_the_manifest() -> None:
    data = _manifest()
    verified = _verified()
    by_name = {repo["name"]: repo for repo in data["repositories"]}
    entries = {entry["name"]: entry for entry in verified["repositories"]}
    expected = {name for name, repo in by_name.items() if repo["status"] == "verified"}
    assert set(entries) == expected
    assert verified["manifest_digest"] == data["manifest_digest"]
    for name, entry in entries.items():
        assert PIN.fullmatch(entry["pin_sha"]), name
        assert entry["pin_sha"] == by_name[name]["pin_sha"], name
        assert entry["spdx"] in PERMISSIVE, name
        assert entry["spdx"] == by_name[name]["spdx"], name
        assert entry["license_verified"] is True, name
        assert entry["license_file"].upper().startswith(LICENSE_FILE_PREFIXES), name
        assert TREE_DIGEST.fullmatch(entry["tree_digest"]), name
        assert entry["snapshot_bytes"] > 0 and entry["snapshot_files"] > 0, name
    assert len(expected) + len(verified["excluded"]) == len(data["repositories"])


def test_scored_roles_are_verified_and_exclusions_carry_a_reason() -> None:
    data = _manifest()
    entries = {entry["name"]: entry for entry in _verified()["repositories"]}
    for repo in data["repositories"]:
        assert len(repo["roles"]) <= 1, repo["name"]
        if SCORED_ROLES & set(repo["roles"]):
            assert repo["status"] == "verified", repo["name"]
            assert len(repo["roles"]) == 1, repo["name"]
            assert repo["name"] in entries, repo["name"]
            assert entries[repo["name"]]["license_verified"] is True, repo["name"]
        if repo["status"] == "unverified":
            assert repo["roles"] == [], repo["name"]
    excluded = {entry["name"]: entry for entry in _verified()["excluded"]}
    assert set(excluded) == {
        repo["name"] for repo in data["repositories"] if repo["status"] == "unverified"
    }
    for name, entry in excluded.items():
        assert entry["reason"].strip(), name


def test_license_corrections_and_validator_differences_are_reported() -> None:
    data = _manifest()
    verified = _verified()
    report = (VERIFIED.parent / "REPORT.md").read_text(encoding="utf-8")
    by_name = {repo["name"]: repo for repo in data["repositories"]}
    entries = {entry["name"]: entry for entry in verified["repositories"]}
    assert "## Declared SPDX corrected by the fetched license text" in report
    assert "## corpus/fetch.py license-check differences" in report
    for entry in verified["spdx_corrections"]:
        assert entry["declared"] != entry["verified"]
        assert by_name[entry["name"]]["spdx"] == entry["verified"]
        assert entries[entry["name"]]["spdx_corrected_from"] == entry["declared"]
        assert entry["name"] in report
    for entry in verified["validator_differences"]:
        assert entry["fetch_license_check"].strip()
        assert entries[entry["name"]]["license_verified"] is True
        assert entries[entry["name"]]["license_file"] == entry["license_file"]
        assert entry["name"] in report
    assert len(entries) + len(verified["excluded"]) == len(data["repositories"])


def test_verified_entries_record_a_hashed_license_text() -> None:
    for entry in _verified()["repositories"]:
        assert re.fullmatch(r"^[0-9a-f]{64}$", entry["license_text_sha256"])
        assert entry["spdx_declared"] in PERMISSIVE


def test_role_minimums_hold_for_every_release_language() -> None:
    """Each release language keeps two pairs, one mutation-base and one held-out."""
    data = _manifest()
    for group in RELEASE_GROUPS:
        repos = [
            repo
            for repo in data["repositories"]
            if _release_group(repo["languages"]) == group
        ]
        usable = [repo for repo in repos if repo["status"] == "verified"]
        roles = [role for repo in usable for role in repo["roles"]]
        assert roles.count("pairs") >= 2, group
        assert roles.count("mutation-base") >= 1, group
        if len(usable) >= 4:
            assert roles.count("held-out") >= 1, group
        others = set(roles) - {"pairs", "mutation-base", "held-out", "calibration"}
        assert not others, (group, others)


def test_candidate_languages_outside_the_release_set_hold_only_unscored_roles() -> None:
    data = _manifest()
    for repo in data["repositories"]:
        if _release_group(repo["languages"]) in RELEASE_GROUPS:
            continue
        assert set(repo["roles"]) <= {"calibration", "held-out"}, repo["name"]
