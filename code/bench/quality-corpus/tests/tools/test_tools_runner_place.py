import hashlib
import json
import subprocess
import sys
from pathlib import Path

import behaviour_runner
import pytest
from behaviour_runner import run_item
from place_item import audit_repo, place

TOOLS = Path(__file__).resolve().parents[2] / "tools"


def make_python_pair(root: Path, different: bool = False) -> Path:
    item = root / "pair"
    item.mkdir(parents=True)
    versions = ("sensible", "monolith", "tiny", "padded", "sizematched", "namematched")
    for version in versions:
        answer = 41 if different and version == "namematched" else 42
        (item / f"{version}.py").write_text(f"def answer(): return {answer}\n")
    (item / "behaviour_test.py").write_text(
        "import solution\nassert solution.answer() == 42\n"
    )
    return item


def test_runner_runs_shared_test_against_both_python_versions(tmp_path: Path) -> None:
    assert run_item(make_python_pair(tmp_path)) == []
    failures = run_item(make_python_pair(tmp_path / "different", different=True))
    assert len(failures) == 1
    assert failures[0]["kind"] == "failed"


def make_declared_python_pair(root: Path, different: bool = False) -> Path:
    item = root / "declared-pair"
    item.mkdir(parents=True)
    (item / "a.py").write_text(
        "def answer(): return 41\n" if different else "def answer(): return 42\n"
    )
    (item / "b.py").write_text("def answer(): return 42\n")
    (item / "pair.json").write_text(json.dumps({"left": "a.py", "right": "b.py"}))
    (item / "behaviour_test.py").write_text(
        "import solution\nassert solution.answer() == 42\n"
    )
    return item


def test_runner_checks_two_declared_pair_sides(tmp_path: Path) -> None:
    item = make_declared_python_pair(tmp_path)
    assert run_item(item) == []
    cli = subprocess.run(
        [
            sys.executable,
            str(TOOLS / "behaviour_runner.py"),
            "--items",
            str(item),
            "--check",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert cli.returncode == 0
    assert '"status": "passed"' in cli.stdout
    failures = run_item(
        make_declared_python_pair(tmp_path / "different", different=True)
    )
    assert len(failures) == 1
    assert failures[0]["kind"] == "failed"


def test_runner_rejects_missing_declared_pair_side(tmp_path: Path) -> None:
    item = make_declared_python_pair(tmp_path)
    (item / "a.py").unlink()
    findings = run_item(item)
    assert len(findings) == 1
    assert findings[0]["kind"] == "invalid_item"


def test_runner_rejects_fewer_than_two_declared_versions(tmp_path: Path) -> None:
    item = make_declared_python_pair(tmp_path)
    (item / "pair.json").write_text(json.dumps({"left": "a.py", "right": "a.py"}))
    findings = run_item(item)
    assert len(findings) == 1
    assert findings[0]["kind"] == "invalid_item"


def test_runner_checks_union_of_category_b_pair_versions(
    tmp_path: Path, monkeypatch
) -> None:
    item = tmp_path / "category-b"
    item.mkdir()
    pair_entries = [
        ("sensible.py", name)
        for name in (
            "monolith.py",
            "tiny.py",
            "padded.py",
            "sizematched.py",
            "namematched.py",
        )
    ]
    for name in {name for pair in pair_entries for name in pair}:
        (item / name).write_text("# solution\n")
    (item / "pair.json").write_text(
        json.dumps(
            {
                "part": "b",
                "pairs": [
                    {"pair_id": f"pair-{index}", "left": left, "right": right}
                    for index, (left, right) in enumerate(pair_entries)
                ],
            }
        )
    )
    test = item / "behaviour_test.py"
    test.write_text("pass\n")
    seen = []

    def passed(source: Path, shared_test: Path) -> tuple[str, str]:
        seen.append((source.name, shared_test.name))
        return "passed", ""

    monkeypatch.setattr(behaviour_runner, "run_version", passed)
    assert run_item(item) == []
    assert seen == [
        ("sensible.py", "behaviour_test.py"),
        ("monolith.py", "behaviour_test.py"),
        ("tiny.py", "behaviour_test.py"),
        ("padded.py", "behaviour_test.py"),
        ("sizematched.py", "behaviour_test.py"),
        ("namematched.py", "behaviour_test.py"),
    ]


def test_runner_rejects_non_object_pair_json(tmp_path: Path) -> None:
    item = make_declared_python_pair(tmp_path)
    (item / "pair.json").write_text("[]\n")
    findings = run_item(item)
    assert len(findings) == 1
    assert findings[0]["kind"] == "invalid_item"


def test_place_routes_dev_and_test_and_audit_finds_planted_test(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "code.py").write_text("pass\n")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    restricted = tmp_path / "restricted"
    monkeypatch.setenv("VARDE_GOLDEN_RESTRICTED", str(restricted))
    dev_path = place(source, "dev", "sample-task", repo / "items", repo)
    test_path = place(source, "test-restricted", "sample-test", repo / "items", repo)
    assert dev_path.is_relative_to(repo)
    assert test_path.is_relative_to(restricted)
    assert not test_path.is_relative_to(repo)
    monkeypatch.setenv("VARDE_GOLDEN_RESTRICTED", str(repo / "restricted"))
    with pytest.raises(ValueError):
        place(source, "test-restricted", "sample-test", repo / "items", repo)
    monkeypatch.setenv("VARDE_GOLDEN_RESTRICTED", str(restricted))
    task_hash = hashlib.sha256(b"sample-test").hexdigest()[:24]
    lock = tmp_path / "splits.lock"
    lock.write_text(
        json.dumps(
            {"assignments": {"sample-test": "test-restricted"}, "sha256": "unused"}
        )
    )
    planted = repo / "random-folder" / task_hash / ".varde-split.json"
    planted.parent.mkdir(parents=True)
    planted.write_text(
        json.dumps({"task_id": "sample-test", "split": "test-restricted"})
    )
    assert str(planted) in audit_repo(repo, lock)
    label = repo / "code" / "bench" / "quality-corpus" / "labels" / "labels.jsonl"
    label.parent.mkdir(parents=True)
    label.write_text('{"task_id":"sample-test"}\n')
    assert str(label) in audit_repo(repo, lock)
    audit_cli = subprocess.run(
        [
            sys.executable,
            str(TOOLS / "place_item.py"),
            "--audit-repo",
            "--repo-root",
            str(repo),
        ],
        check=False,
        capture_output=True,
    )
    assert audit_cli.returncode == 1
    label.unlink()
    planted.unlink()
    clean_audit = subprocess.run(
        [
            sys.executable,
            str(TOOLS / "place_item.py"),
            "--audit-repo",
            "--repo-root",
            str(repo),
        ],
        check=False,
        capture_output=True,
    )
    assert clean_audit.returncode == 0
    clean = tmp_path / "clean"
    clean.mkdir()
    assert audit_repo(clean, lock) == []


def test_clis_use_exit_codes_for_findings_and_missing_paths(tmp_path: Path) -> None:
    hygiene = TOOLS / "hygiene.py"
    runner = TOOLS / "behaviour_runner.py"
    place_cli = TOOLS / "place_item.py"
    export = TOOLS / "export_pairs.py"
    invalid = tmp_path / "invalid"
    invalid.mkdir()
    (invalid / "a.py").write_text("# monolith\npass\n")
    (invalid / "b.py").write_text("pass\n")
    (invalid / "behaviour_test.rs").write_text("// test split\n")

    def run(script: Path, *args: str) -> int:
        return subprocess.run(
            [sys.executable, str(script), *args], check=False, capture_output=True
        ).returncode

    hygiene_result = subprocess.run(
        [sys.executable, str(hygiene), "--items", str(invalid), "--check"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert hygiene_result.returncode == 1
    assert any(
        json.loads(line)["kind"] == "forbidden_text"
        for line in hygiene_result.stdout.splitlines()
    )
    clean = tmp_path / "clean-item"
    clean.mkdir()
    (clean / "a.py").write_text("def answer(): return 1\n")
    (clean / "b.py").write_text("def answer(): return 1\n")
    (clean / "behaviour_test.py").write_text(
        "import solution\nassert solution.answer() == 1\n"
    )
    assert run(hygiene, "--items", str(clean), "--check") == 0
    assert run(hygiene, "--items", str(tmp_path / "missing"), "--check") == 2
    assert run(runner, "--items", str(tmp_path / "missing"), "--check") == 2
    assert run(place_cli, "--item", str(invalid), "--split", "dev", "--task") == 2
    assert (
        run(
            export,
            "--items",
            str(tmp_path / "missing"),
            "--output",
            str(tmp_path / "out"),
        )
        == 2
    )
    assert run(place_cli, "--item", str(invalid), "--split", "dev", "--task") == 2

    missing = tmp_path / "blocked"
    missing.mkdir()
    for name in ("a", "b", "c", "d", "e", "f"):
        (missing / f"{name}.unknown").write_text("x\n")
    (missing / "behaviour_test.unknown").write_text("x\n")
    blocked = subprocess.run(
        [
            sys.executable,
            str(runner),
            "--items",
            str(missing),
            "--check",
            "--allow-missing-toolchain",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert blocked.returncode == 0
    records = [json.loads(line) for line in blocked.stdout.splitlines()]
    assert any(record.get("status") == "blocked" for record in records)
    rejected = subprocess.run(
        [sys.executable, str(runner), "--items", str(missing), "--check"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert rejected.returncode == 1
