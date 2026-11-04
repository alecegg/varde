"""The committed split lock lives beside the tools; every consumer resolves it there."""

import json
import os
import subprocess
import sys
from pathlib import Path

import splits
from place_item import place

TOOLS = Path(__file__).resolve().parents[2] / "tools"
REPO = TOOLS.parents[3]
COMMITTED_LOCK = TOOLS / "splits.lock"


def make_item(root: Path) -> Path:
    item = root / "item"
    item.mkdir()
    (item / "task.txt").write_text("A simple calculation\n")
    return item


def place_cli(args: list[str], restricted: Path) -> subprocess.CompletedProcess:
    environment = {**os.environ, "VARDE_GOLDEN_RESTRICTED": str(restricted)}
    return subprocess.run(  # noqa: S603 - Runs the lock-path CLI in a controlled child process.
        [sys.executable, str(TOOLS / "place_item.py"), *args],
        check=False,
        capture_output=True,
        env=environment,
    )


def test_assign_reads_the_committed_lock_beside_the_tools() -> None:
    assert COMMITTED_LOCK.is_file()
    assert splits.LOCK.resolve() == COMMITTED_LOCK.resolve()
    assert splits.assign("price-order") == "test-restricted"


def test_splits_cli_check_lock_defaults_to_the_committed_lock() -> None:
    result = subprocess.run(  # noqa: S603 - Runs the lock-path CLI in a controlled child process.
        [sys.executable, str(TOOLS / "splits.py"), "--check-lock"],
        check=False,
        capture_output=True,
        cwd=REPO,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert b"split lock: ok" in result.stdout


def test_locked_test_task_routes_to_the_restricted_store(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    restricted = tmp_path / "restricted"
    result = place_cli(
        [
            "--item",
            str(make_item(tmp_path)),
            "--task",
            "price-order",
            "--split",
            "locked",
            "--repo-root",
            str(repo),
        ],
        restricted,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    placed = list(restricted.rglob("task.txt"))
    assert len(placed) == 1
    record = json.loads((placed[0].parent / ".varde-split.json").read_text())
    assert record == {"task_id": "price-order", "split": "test-restricted"}
    assert placed[0].is_relative_to(restricted / "test-restricted")


def test_locked_dev_task_routes_to_the_items_directory(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    restricted = tmp_path / "restricted"
    items = tmp_path / "items"
    result = place_cli(
        [
            "--item",
            str(make_item(tmp_path)),
            "--task",
            "anchor-ledger",
            "--split",
            "locked",
            "--repo-root",
            str(repo),
            "--repo-items",
            str(items),
        ],
        restricted,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    matches = list(items.rglob("task.txt"))
    assert len(matches) == 1
    assert matches[0].is_relative_to(items / "dev")
    record = json.loads((matches[0].parent / ".varde-split.json").read_text())
    assert record == {"task_id": "anchor-ledger", "split": "dev"}
    assert not restricted.exists()


def test_place_uses_the_committed_lock_for_locked_splits(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("VARDE_GOLDEN_RESTRICTED", str(tmp_path / "restricted"))
    repo = tmp_path / "repo"
    repo.mkdir()
    placed = place(
        make_item(tmp_path),
        splits.assign("price-order"),
        "price-order",
        repo / "items",
        repo,
    )
    assert placed.is_relative_to(tmp_path / "restricted")
