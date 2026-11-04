import json
import subprocess
import sys
from pathlib import Path

from hygiene import check, replace_opaque_ids
from splits import assign, assignments, lock_hash, write_lock

TOOLS = Path(__file__).resolve().parents[2] / "tools"


def test_assignments_are_order_independent_and_shared_across_languages(
    tmp_path: Path, monkeypatch
) -> None:
    first = assignments(["task-b", "task-a", "task-c"])
    assert assignments(["task-c", "task-a", "task-b"]) == first
    # Language is deliberately not an input to the assignment function.
    for language in ("python", "typescript", "java", "csharp", "go", "rust", "cpp"):
        assert assign("task-a", ["task-a", "task-b", "task-c"]) == first["task-a"], (
            language
        )
    lock = tmp_path / "splits.lock"
    write_lock(["task-a", "task-b", "task-c"], lock)
    monkeypatch.setattr("splits.LOCK", lock)
    assert assign("task-a") == first["task-a"]
    assert json.loads(lock.read_text())["sha256"] == lock_hash(first)
    assert any(
        split == "regression"
        for split in assignments([f"task-{i}" for i in range(100)]).values()
    )
    changed = dict(first)
    changed["task-a"] = "dev" if changed["task-a"] != "dev" else "regression"
    assert lock_hash(first) != lock_hash(changed)


def test_hygiene_checks_behaviour_test_and_rewrites_ids(tmp_path: Path) -> None:
    item = tmp_path / "item"
    item.mkdir()
    (item / "a.py").write_text(
        '"""This docstring is long enough to count."""\ndef a(): return 1\n'
    )
    (item / "b.py").write_text(
        '"""This docstring is long enough to count."""\ndef b(): return 1\n'
    )
    (item / "behaviour_test.ts").write_text("// monolith\n")
    (item / "task.txt").write_text("A simple calculation")
    findings = check(item)
    assert any(
        f.kind == "forbidden_text" and f.path.endswith("behaviour_test.ts")
        for f in findings
    )
    rewritten, mapping = replace_opaque_ids(
        {"pair_id": "visible-pair", "left_id": "left"}
    )
    assert rewritten["pair_id"] == mapping["visible-pair"]
    assert rewritten["left_id"] == mapping["left"]
    assert all(len(value) == 24 for value in mapping.values())
    (item / "a.py").write_text('label = "ordinary identifier"\n')
    (item / "b.py").write_text('label = "ordinary identifier"\n')
    (item / "behaviour_test.ts").write_text("const x = 1;\n")
    assert not any(f.kind == "forbidden_text" for f in check(item))
    (item / "b.py").write_text(
        '"""a long enough explanatory docstring for parity testing"""\n'
    )
    assert any(f.kind == "comment_parity" for f in check(item))


def test_rewrite_ids_cli_updates_pair_metadata(tmp_path: Path) -> None:
    item = tmp_path / "item"
    item.mkdir()
    pair = item / "pair.json"
    pair.write_text(json.dumps({"pair_id": "visible-pair", "left_id": "left"}))
    result = subprocess.run(
        [
            sys.executable,
            str(TOOLS / "hygiene.py"),
            "--items",
            str(item),
            "--rewrite-ids",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    mapping = json.loads(result.stdout)["rewritten_ids"]
    rewritten = json.loads(pair.read_text())
    assert rewritten["pair_id"] == mapping["visible-pair"]
    assert rewritten["left_id"] == mapping["left"]


def test_splits_cli_missing_lock_returns_usage_error(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(TOOLS / "splits.py"),
            "--check-lock",
            str(tmp_path / "missing"),
        ],
        check=False,
        capture_output=True,
    )
    assert result.returncode == 2


def test_splits_cli_check_lock_succeeds_and_rejects_mismatch(tmp_path: Path) -> None:
    tasks = tmp_path / "tasks.json"
    tasks.write_text(json.dumps(["task-a", "task-b"]))
    lock = tmp_path / "splits.lock"
    write = subprocess.run(
        [
            sys.executable,
            str(TOOLS / "splits.py"),
            "--write-lock",
            str(lock),
            "--tasks",
            str(tasks),
        ],
        check=False,
        capture_output=True,
    )
    assert write.returncode == 0
    success = subprocess.run(
        [sys.executable, str(TOOLS / "splits.py"), "--check-lock", str(lock)],
        check=False,
        capture_output=True,
    )
    assert success.returncode == 0
    payload = json.loads(lock.read_text())
    payload["assignments"]["task-a"] = "regression"
    lock.write_text(json.dumps(payload))
    mismatch = subprocess.run(
        [sys.executable, str(TOOLS / "splits.py"), "--check-lock", str(lock)],
        check=False,
        capture_output=True,
    )
    assert mismatch.returncode == 1
