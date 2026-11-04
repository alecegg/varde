"""Behavior tests for manifest validation and repository role checks."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
from fetch import (
    FetchError,
    check_license,
    fetch_repository,
    needs_full_history,
    tree_digest,
)
from manifest import ManifestError, compute_manifest_digest, validate_manifest
from roles import check_roles


def _repo(
    name: str = "owner/project", roles: list[str] | None = None
) -> dict[str, object]:
    return {
        "name": name,
        "url": f"https://example.invalid/{name}.git",
        "spdx": "MIT",
        "languages": ["Python"],
        "pin_sha": "a" * 40,
        "history_cutoffs": [],
        "roles": roles or [],
        "status": "verified",
    }


def _manifest(*repos: dict[str, object]) -> dict[str, object]:
    data: dict[str, object] = {"repositories": list(repos), "pair_groups": []}
    data["manifest_digest"] = compute_manifest_digest(data)
    return data


def _git(directory: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(directory), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _local_bare_repo(tmp_path: Path) -> tuple[Path, str, str]:
    source = tmp_path / "source"
    source.mkdir()
    _git(source, "init", "--quiet")
    _git(source, "config", "user.email", "test@example.invalid")
    _git(source, "config", "user.name", "Corpus Test")
    (source / "LICENSE").write_text(
        "MIT License\n"
        "Permission is hereby granted, free of charge, to any person obtaining "
        "a copy.\n"
        "THE SOFTWARE IS PROVIDED AS IS.\n",
        encoding="utf-8",
    )
    (source / "sample.py").write_text("value = 1\n", encoding="utf-8")
    _git(source, "add", ".")
    _git(source, "commit", "--quiet", "-m", "initial")
    cutoff = _git(source, "rev-parse", "HEAD")
    (source / "history.txt").write_text("second commit\n", encoding="utf-8")
    _git(source, "add", "history.txt")
    _git(source, "commit", "--quiet", "-m", "second")
    pin = _git(source, "rev-parse", "HEAD")
    bare = tmp_path / "remote.git"
    subprocess.run(
        ["git", "clone", "--quiet", "--bare", str(source), str(bare)], check=True
    )
    return bare, pin, cutoff


def test_corpus_manifest_rejects_invalid_pin_license_and_overlapping_roles() -> None:
    invalid_pin = _repo()
    invalid_pin["pin_sha"] = "deadbeef"
    with pytest.raises(ManifestError, match="pin_sha"):
        validate_manifest(_manifest(invalid_pin))

    invalid_spdx = _repo()
    invalid_spdx["spdx"] = "NOT-A-LICENSE"
    with pytest.raises(ManifestError, match="SPDX"):
        validate_manifest(_manifest(invalid_spdx))

    overlapping = _repo(roles=["calibration", "pairs"])
    with pytest.raises(ManifestError, match="disjoint"):
        validate_manifest(_manifest(overlapping))


def test_corpus_fetch_pins_revision_records_tree_and_archives_snapshot(
    tmp_path: Path,
) -> None:
    remote, pin, cutoff = _local_bare_repo(tmp_path)
    repo = _repo()
    repo.update(
        url=str(remote),
        pin_sha=pin,
        history_cutoffs=[cutoff],
        roles=["history"],
    )
    cache = tmp_path / "cache"
    snapshots = tmp_path / "snapshots"

    record = fetch_repository(repo, cache, snapshots)

    clone = cache / "owner__project"
    assert _git(clone, "rev-parse", "FETCH_HEAD") == pin
    assert _git(clone, "rev-parse", cutoff) == cutoff
    assert _git(clone, "rev-parse", "--is-shallow-repository") == "false"
    assert record["tree_digest"] == tree_digest(clone)
    assert len(record["tree_digest"]) == hashlib.sha256().digest_size * 2
    assert (snapshots / "owner__project" / "sample.py").read_text() == "value = 1\n"


def test_corpus_fetch_points_a_local_ref_at_the_pin(tmp_path: Path) -> None:
    remote, pin, _ = _local_bare_repo(tmp_path)
    repo = _repo(roles=["pairs"])
    repo.update(url=str(remote), pin_sha=pin)

    fetch_repository(repo, tmp_path / "cache", tmp_path / "snapshots")

    clone = tmp_path / "cache" / "owner__project"
    assert _git(clone, "rev-parse", "refs/heads/pinned") == pin
    assert _git(clone, "rev-list", "--count", "refs/heads/pinned") == "2"


@pytest.mark.parametrize("role", ["calibration", "held-out", "mutation-base"])
def test_corpus_fetch_fetches_only_the_pin_for_tip_only_roles(
    tmp_path: Path, role: str
) -> None:
    remote, pin, _ = _local_bare_repo(tmp_path)
    repo = _repo(roles=[role])
    repo.update(url=str(remote), pin_sha=pin)

    record = fetch_repository(repo, tmp_path / "cache", tmp_path / "snapshots")

    clone = tmp_path / "cache" / "owner__project"
    assert record["pin_sha"] == pin
    assert record["tree_digest"] == tree_digest(clone)
    assert _git(clone, "rev-parse", "--is-shallow-repository") == "true"
    assert _git(clone, "rev-list", "--count", "refs/heads/pinned") == "1"


def test_corpus_fetch_restores_full_history_when_roles_change(tmp_path: Path) -> None:
    remote, pin, cutoff = _local_bare_repo(tmp_path)
    repo = _repo(roles=["calibration"])
    repo.update(url=str(remote), pin_sha=pin)
    cache = tmp_path / "cache"
    fetch_repository(repo, cache, tmp_path / "snapshots-shallow")

    repo["roles"] = ["history"]
    repo["history_cutoffs"] = [cutoff]
    record = fetch_repository(repo, cache, tmp_path / "snapshots-full")

    clone = cache / "owner__project"
    assert record["tree_digest"] == tree_digest(clone)
    assert _git(clone, "rev-parse", "--is-shallow-repository") == "false"
    assert _git(clone, "rev-list", "--count", "refs/heads/pinned") == "2"


def test_corpus_fetch_treats_mixed_roles_as_full_history() -> None:
    assert needs_full_history({**_repo(), "roles": ["calibration", "history"]})
    assert needs_full_history({**_repo(), "history_cutoffs": ["b" * 40]})
    assert not needs_full_history({**_repo(), "roles": ["calibration"]})


def test_corpus_fetch_allows_a_new_pin_for_cached_upstream(tmp_path: Path) -> None:
    remote, first_pin, _ = _local_bare_repo(tmp_path)
    repo = _repo()
    repo.update(url=str(remote), pin_sha=first_pin)
    cache = tmp_path / "cache"
    fetch_repository(repo, cache, tmp_path / "snapshots-first")

    source = tmp_path / "source"
    (source / "sample.py").write_text("value = 3\n", encoding="utf-8")
    _git(source, "add", "sample.py")
    _git(source, "commit", "--quiet", "-m", "third")
    second_pin = _git(source, "rev-parse", "HEAD")
    _git(source, "push", str(remote), "HEAD:refs/heads/master")
    repo["pin_sha"] = second_pin

    record = fetch_repository(repo, cache, tmp_path / "snapshots-second")

    assert record["pin_sha"] == second_pin
    assert _git(cache / "owner__project", "rev-parse", "FETCH_HEAD") == second_pin


@pytest.mark.parametrize("roles", [["history"], ["calibration"]])
def test_corpus_fetch_detects_a_tree_digest_change_for_the_same_pin(
    tmp_path: Path, roles: list[str]
) -> None:
    remote, pin, _ = _local_bare_repo(tmp_path)
    repo = _repo(roles=roles)
    repo.update(url=str(remote), pin_sha=pin)
    cache = tmp_path / "cache"
    fetch_repository(repo, cache, tmp_path / "snapshots-first")
    metadata = cache / "owner__project" / ".varde-corpus.json"
    record = json.loads(metadata.read_text(encoding="utf-8"))
    record["tree_digest"] = "0" * 64
    metadata.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(FetchError, match="pinned tree changed"):
        fetch_repository(repo, cache, tmp_path / "snapshots-second")


@pytest.mark.parametrize(
    "text",
    [
        "GNU GENERAL PUBLIC LICENSE Version 3",
        "GNU AFFERO GENERAL PUBLIC LICENSE",
        "Business Source License (BUSL)",
        "Server Side Public License (SSPL)",
    ],
)
def test_corpus_license_check_rejects_restricted_license_text(text: str) -> None:
    with pytest.raises(FetchError, match="prohibited"):
        check_license(text, "MIT")


def test_corpus_license_check_requires_declared_license_signature() -> None:
    with pytest.raises(FetchError, match="does not identify MIT"):
        check_license("A BSD license that mentions MIT in a note.", "MIT")


def test_corpus_license_check_distinguishes_bsd_two_and_three_clause() -> None:
    bsd_two = (
        "Redistributions of source code must retain the copyright notice.\n"
        "Redistributions in binary form must reproduce the notice.\n"
    )
    bsd_three = (
        bsd_two + "Neither the name of the copyright holder may endorse products.\n"
    )

    check_license(bsd_two, "BSD-2-Clause")
    check_license(bsd_three, "BSD-3-Clause")
    with pytest.raises(FetchError, match="BSD-3-Clause"):
        check_license(bsd_two, "BSD-3-Clause")
    with pytest.raises(FetchError, match="BSD-2-Clause"):
        check_license(bsd_three, "BSD-2-Clause")


def test_corpus_roles_reject_calibration_repositories_reserved_elsewhere(
    tmp_path: Path,
) -> None:
    repo = _repo(roles=["calibration"])
    manifest_data = _manifest(repo)
    manifest_path = tmp_path / "manifest.toml"
    manifest_path.write_text(
        'manifest_digest = "' + str(manifest_data["manifest_digest"]) + '"\n'
        "pair_groups = []\n"
        '[[repositories]]\nname = "owner/project"\nurl = "https://example.invalid/owner/project.git"\n'
        'spdx = "MIT"\nlanguages = ["Python"]\npin_sha = "' + "a" * 40 + '"\n'
        'history_cutoffs = []\nroles = ["calibration"]\nstatus = "verified"\n',
        encoding="utf-8",
    )
    protected = tmp_path / "reserved"
    protected.mkdir()
    (protected / "repo.toml").write_text(
        '[[repos]]\nname = "owner/project"\n', encoding="utf-8"
    )

    conflicts = check_roles(manifest_path, protected)

    assert conflicts == [
        "owner/project: calibration role conflicts with call-resolution corpus"
    ]


def test_corpus_roles_allow_missing_protected_repository_directory(
    tmp_path: Path,
) -> None:
    data = _manifest(_repo(roles=["calibration"]))
    manifest_path = tmp_path / "manifest.toml"
    manifest_path.write_text(
        'manifest_digest = "' + str(data["manifest_digest"]) + '"\n'
        "pair_groups = []\n"
        '[[repositories]]\nname = "owner/project"\nurl = "https://example.invalid/owner/project.git"\n'
        'spdx = "MIT"\nlanguages = ["Python"]\npin_sha = "' + "a" * 40 + '"\n'
        'history_cutoffs = []\nroles = ["calibration"]\nstatus = "verified"\n',
        encoding="utf-8",
    )

    assert check_roles(manifest_path, tmp_path / "not-created") == []


def test_corpus_manifest_digest_changes_when_repository_data_changes() -> None:
    first = _manifest(_repo())
    changed_repo = _repo()
    changed_repo["spdx"] = "Apache-2.0"
    second = _manifest(changed_repo)

    assert first["manifest_digest"] != second["manifest_digest"]


def test_corpus_manifest_records_a_redirected_from_note() -> None:
    redirected = _repo()
    redirected["redirected_from"] = "old/name"

    data = _manifest(redirected)

    validate_manifest(data)
    assert data["manifest_digest"] != _manifest(_repo())["manifest_digest"]


def test_corpus_manifest_rejects_an_empty_redirected_from_note() -> None:
    redirected = _repo()
    redirected["redirected_from"] = ""

    with pytest.raises(ManifestError, match="redirected_from"):
        validate_manifest(_manifest(redirected))


def test_corpus_manifest_accepts_task_and_refactor_pair_groups() -> None:
    data: dict[str, object] = {
        "repositories": [_repo(roles=["pairs"])],
        "pair_groups": [
            {
                "id": "task-compare",
                "repository": "owner/project",
                "kind": "task",
                "samples": ["split", "monolith"],
            },
            {
                "id": "refactor-compare",
                "repository": "owner/project",
                "kind": "refactor",
                "samples": ["before", "after"],
            },
        ],
    }
    data["manifest_digest"] = compute_manifest_digest(data)

    validate_manifest(data)

    no_groups = _manifest(_repo(roles=["pairs"]))
    assert data["manifest_digest"] != no_groups["manifest_digest"]


def test_corpus_manifest_requires_pairs_role_for_pair_groups() -> None:
    data: dict[str, object] = {
        "repositories": [_repo()],
        "pair_groups": [
            {
                "id": "task-compare",
                "repository": "owner/project",
                "kind": "task",
                "samples": ["split", "monolith"],
            }
        ],
    }
    data["manifest_digest"] = compute_manifest_digest(data)

    with pytest.raises(ManifestError, match="must hold the pairs role"):
        validate_manifest(data)


def test_corpus_manifest_rejects_pair_groups_with_unknown_repositories() -> None:
    data = _manifest(_repo())
    data["pair_groups"] = [
        {
            "id": "bad-pair",
            "repository": "unknown/project",
            "kind": "task",
            "samples": ["a", "b"],
        }
    ]
    data["manifest_digest"] = compute_manifest_digest(data)

    with pytest.raises(ManifestError, match="unknown repository"):
        validate_manifest(data)
