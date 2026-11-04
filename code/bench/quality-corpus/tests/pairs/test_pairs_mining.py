from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from fetch import fetch_repository
from pairs import mine
from pairs.mine import MiningError, mine_repository, precision_sample

MIT_LICENSE = (
    "MIT License\n"
    "Permission is hereby granted, free of charge, to any person obtaining a copy.\n"
    "THE SOFTWARE IS PROVIDED AS IS.\n"
)


def _git(path: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(path), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _init(path: Path, files: dict[str, str]) -> str:
    path.mkdir()
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    for name, source in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source)
    _git(path, "add", ".")
    _git(path, "commit", "-qm", "initial")
    return _git(path, "rev-parse", "HEAD")


def _commit(path: Path, message: str, files: dict[str, str]) -> str:
    for name, source in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source)
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", message)
    return _git(path, "rev-parse", "HEAD")


def _python_pair(
    path: Path,
    message: str,
    after: str,
    before: str = "def calculate(x):\n    return x\n",
) -> tuple[str, str]:
    parent = _init(path, {"module.py": before})
    child = _commit(path, message, {"module.py": after})
    return parent, child


def _bare_remote(tmp_path: Path) -> tuple[Path, str]:
    """Return a bare remote holding one intent refactor commit and its pin."""
    source = tmp_path / "source"
    _init(
        source,
        {
            "LICENSE": MIT_LICENSE,
            "module.py": "def calculate(x):\n    return x\n",
        },
    )
    pin = _commit(
        source,
        "Simplify calculation for readability",
        {"module.py": "def calculate(x):\n    return x + 1\n"},
    )
    remote = tmp_path / "remote.git"
    subprocess.run(
        ["git", "clone", "--quiet", "--bare", str(source), str(remote)], check=True
    )
    return remote, pin


def _refless_clone(tmp_path: Path, remote: Path, pin: str) -> Path:
    """Clone by fetch only, which leaves no local branch ref behind."""
    clone = tmp_path / "refless"
    clone.mkdir()
    _git(clone, "init", "-q")
    _git(clone, "fetch", str(remote), pin)
    return clone


def _records(path: Path, **kwargs: object) -> list[dict]:
    return [
        json.loads(line)
        for line in mine_repository(path, "owner/project", "Python", **kwargs)
    ]


def test_records_pair_provenance_and_all_filter_evidence(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    parent, child = _python_pair(
        repo,
        "Simplify calculation for readability",
        "def calculate(x):\n    result = x + 1\n    return result\n",
    )
    record = _records(repo)[0]
    assert (record["parent_sha"], record["child_sha"]) == (parent, child)
    assert record["changed_functions"] == ["calculate"]
    assert record["pair_group_id"] == record["pair_group"]["id"]
    assert record["pair_group"] == {
        "id": record["pair_group_id"],
        "repository": "owner/project",
        "kind": "refactor",
        "samples": [f"{child}:before", f"{child}:after"],
    }
    assert record["filters_passed"] == [
        "developer_intent",
        "not_revert",
        "not_merge",
        "source_file_limit",
        "function_limit",
        "no_public_feature_addition",
        "parse_before_after",
        "not_generated",
        "null_detector",
    ]


def test_each_intent_wording_is_accepted(tmp_path: Path) -> None:
    for i, wording in enumerate(
        ("Simplify", "Extract function", "Flatten", "Improve readability")
    ):
        repo = tmp_path / f"intent-{i}"
        _python_pair(
            repo, wording, "def calculate(x):\n    result = x + 1\n    return result\n"
        )
        assert len(_records(repo)) == 1


def test_linked_issue_supplies_intent_and_missing_issue_does_not(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "issue"
    _python_pair(repo, "Fix #42", "def calculate(x):\n    return x + 1\n")
    assert _records(repo, issue_text={"42": "Simplify calculation for readability"})[0][
        "intent_evidence"
    ]["linked_issues"]
    assert _records(repo) == []


def test_revert_commit_is_excluded(tmp_path: Path) -> None:
    repo = tmp_path / "revert"
    _python_pair(
        repo,
        'Revert "Simplify calculation for readability"\n\n'
        "This reverts commit 0123456789abcdef0123456789abcdef01234567.",
        "def calculate(x):\n    return x + 1\n",
    )
    assert _records(repo) == []


def test_generated_file_is_excluded(tmp_path: Path) -> None:
    repo = tmp_path / "generated"
    _python_pair(
        repo,
        "Simplify generated code",
        "# @generated\ndef calculate(x):\n    return x + 1\n",
    )
    assert _records(repo) == []


def test_feature_adding_commit_is_excluded(tmp_path: Path) -> None:
    repo = tmp_path / "feature"
    _python_pair(
        repo,
        "Simplify and add feature",
        "def calculate(x):\n    return x + 1\n\ndef new_api():\n    return 2\n",
    )
    assert _records(repo) == []


def test_genuine_two_parent_merge_is_excluded(tmp_path: Path) -> None:
    repo = tmp_path / "merge"
    _init(repo, {"module.py": "def calculate(x):\n    return x\n"})
    _git(repo, "checkout", "-qb", "feature")
    _commit(
        repo,
        "Simplify calculation",
        {"module.py": "def calculate(x):\n    return x + 1\n"},
    )
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "parallel", {"other.py": "def other():\n    return 1\n"})
    merge_sha = _git(
        repo, "merge", "--no-ff", "-m", "Merge feature simplify branch", "feature"
    )
    mined = _records(repo)
    assert len(mined) == 1
    assert mined[0]["child_sha"] != merge_sha


def test_file_limit_includes_five_and_excludes_six(tmp_path: Path) -> None:
    for count, accepted in ((5, True), (6, False)):
        repo = tmp_path / f"files-{count}"
        before = {f"m{i}.py": f"def f{i}():\n    return 0\n" for i in range(count)}
        after = {f"m{i}.py": f"def f{i}():\n    return 1\n" for i in range(count)}
        _init(repo, before)
        _commit(repo, "Simplify calculations", after)
        assert bool(_records(repo)) is accepted


def test_function_limit_includes_six_and_excludes_seven(tmp_path: Path) -> None:
    for count, accepted in ((6, True), (7, False)):
        repo = tmp_path / f"functions-{count}"
        before = "\n".join(f"def f{i}():\n    return 0" for i in range(count)) + "\n"
        after = "\n".join(f"def f{i}():\n    return 1" for i in range(count)) + "\n"
        _python_pair(repo, "Simplify functions", after, before)
        assert bool(_records(repo)) is accepted


def test_unparseable_before_or_after_is_excluded(tmp_path: Path) -> None:
    for i, (before, after) in enumerate(
        (
            ("def broken(:\n", "def broken(:\n    pass\n"),
            ("def f():\n    return 1\n", "def broken(:\n"),
        )
    ):
        repo = tmp_path / f"parse-{i}"
        _python_pair(repo, "Simplify broken function", after, before)
        assert _records(repo) == []


def test_detector_accept_receives_pair_and_marks_filter(tmp_path: Path) -> None:
    repo = tmp_path / "detector"
    _python_pair(
        repo,
        "Extract function",
        "def calculate(x):\n    return helper(x)\n\ndef helper(x):\n    return x + 1\n",
    )
    seen = []

    def accept(*args: object) -> bool:
        seen.append(args)
        return True

    record = _records(repo, detector=accept)[0]
    assert len(seen) == 1
    assert seen[0][0] == repo.resolve()
    assert seen[0][1] == record["parent_sha"]
    assert seen[0][2] == record["child_sha"]
    assert seen[0][3] == ["module.py"]
    assert "detector_confirmed" in record["filters_passed"]


def test_detector_rejects_pair_without_record(tmp_path: Path) -> None:
    repo = tmp_path / "detector-reject"
    _python_pair(
        repo,
        "Extract function",
        "def calculate(x):\n    return helper(x)\n\ndef helper(x):\n    return x + 1\n",
    )

    assert _records(repo, detector=lambda *_args: False) == []


def test_language_suffix_and_offline_syntax_fallback(tmp_path: Path) -> None:
    repo = tmp_path / "java"
    _init(
        repo,
        {
            "A.java": "class A { int f() { return 0; } }\n",
            "other.py": "def f():\n    return 0\n",
        },
    )
    _commit(
        repo,
        "Simplify method",
        {
            "A.java": "class A { int f() { return 1; } }\n",
            "other.py": "def f():\n    return 1\n",
        },
    )
    lines = mine_repository(repo, "owner/project", "Java")
    assert len(lines) == 1
    assert json.loads(lines[0])["changed_functions"] == ["f"]

    broken = tmp_path / "broken-java"
    _init(broken, {"A.java": "class A { int f() { return 0; } }\n"})
    _commit(broken, "Simplify method", {"A.java": "class A { int f() { return 1; }\n"})
    assert mine_repository(broken, "owner/project", "Java") == []


def test_comment_only_change_does_not_claim_functions_changed(tmp_path: Path) -> None:
    repo = tmp_path / "comment"
    _python_pair(
        repo,
        "Simplify comments",
        "# clearer comment\ndef calculate(x):\n    return x\n",
    )
    assert _records(repo) == []


def test_mining_a_fetched_clone_walks_the_pinned_ref(tmp_path: Path) -> None:
    remote, pin = _bare_remote(tmp_path)
    record = fetch_repository(
        {
            "name": "owner/project",
            "url": str(remote),
            "spdx": "MIT",
            "languages": ["Python"],
            "pin_sha": pin,
            "history_cutoffs": [],
            "roles": ["pairs"],
            "status": "verified",
        },
        tmp_path / "cache",
        tmp_path / "snapshots",
    )
    clone = tmp_path / "cache" / "owner__project"

    mined = [
        json.loads(line) for line in mine_repository(clone, "owner/project", "Python")
    ]

    assert record["pin_sha"] == pin
    assert [item["child_sha"] for item in mined] == [pin]


def test_mining_a_refless_clone_needs_an_explicit_revision(tmp_path: Path) -> None:
    remote, pin = _bare_remote(tmp_path)
    clone = _refless_clone(tmp_path, remote, pin)

    assert _git(clone, "for-each-ref", "refs/heads") == ""
    with pytest.raises(MiningError, match="no local branch refs"):
        mine_repository(clone, "owner/project", "Python")
    named = mine_repository(clone, "owner/project", "Python", revision=pin)
    assert [json.loads(line)["child_sha"] for line in named] == [pin]


def test_mine_cli_exits_one_with_a_message_for_a_refless_clone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    remote, pin = _bare_remote(tmp_path)
    clone = _refless_clone(tmp_path, remote, pin)
    monkeypatch.setattr(sys, "argv", ["mine.py", str(clone), "owner/project", "Python"])

    assert mine.main() == 1
    assert "no local branch refs" in capsys.readouterr().err


def test_precision_sample_is_stable_stratified_and_without_replacement() -> None:
    python = [{"language": "Python", "id": f"p{i}"} for i in range(45)]
    java = [{"language": "Java", "id": f"j{i}"} for i in range(8)]
    sampled = precision_sample(python + java, seed=9)
    assert sampled == precision_sample(python + java, seed=9)
    assert len(sampled["Python"]) == 40
    assert len(sampled["Java"]) == 8
    assert (
        len({record["id"] for records in sampled.values() for record in records}) == 48
    )
