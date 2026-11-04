"""Check the C++ category-(b) items and their locked split placement."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

from place_item import restricted_root as store_root

ROOT = Path(__file__).resolve().parents[4]
ITEMS = ROOT / "items" / "cpp" / "b"
TOOLS = ROOT / "tools"
TASKS = ROOT / "taskbank" / "bank.json"
LOCK = TOOLS / "splits.lock"
VERSIONS = ("sensible", "monolith", "tiny", "padded", "sizematched", "namematched")
PILOT_TASKS = {"order-quote", "clinic-booking"}
EXPECTED_SPLITS = {
    "price-order": "test-restricted",
    "csv-summary": "regression",
    "text-template": "test-restricted",
    "inventory-adjustment": "test-restricted",
    "reservation-calendar": "dev",
    "scoreboard": "test-restricted",
    "order-quote": "dev",
    "clinic-booking": "dev",
}
ITEM_FILES = {"behaviour_test.cpp", "pair.json"} | {
    f"{version}.cpp" for version in VERSIONS
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def item_files(item: Path) -> set[str]:
    return {
        path.name
        for path in item.iterdir()
        if path.name not in {".varde-split.json", "manual"}
    }


def restricted_root() -> Path:
    return store_root() / "test-restricted"


def restricted_item(task: str) -> Path | None:
    base = restricted_root()
    if not base.is_dir():
        return None
    return next(iter(sorted(base.glob(f"*/{task}-cpp"))), None)


def repo_item(task: str) -> Path | None:
    item = ITEMS / task
    return item if item.is_dir() else None


def item_for(task: str) -> Path | None:
    if EXPECTED_SPLITS[task] in {"dev", "regression"}:
        return repo_item(task)
    return restricted_item(task)


def run_tool(name: str, item: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - Runs the configured compiler on the test fixture.
        [sys.executable, str(TOOLS / name), "--items", str(item), "--check"],
        check=False,
        capture_output=True,
        text=True,
        cwd=TOOLS,
    )


def assignments() -> dict[str, str]:
    return json.loads(LOCK.read_text())["assignments"]


def bank_subset() -> set[str]:
    bank = json.loads(TASKS.read_text())
    return set(bank["language_subsets"]["cpp"])


def test_cpp_toolchain_is_available() -> None:
    assert shutil.which("g++") or shutil.which("clang++"), (
        "the C++ toolchain is required"
    )


def test_cpp_b_tasks_match_the_language_subset_and_splits() -> None:
    assert set(EXPECTED_SPLITS) - PILOT_TASKS == bank_subset()
    locked = assignments()
    for task, split in EXPECTED_SPLITS.items():
        assert locked[task] == split, task
        item = item_for(task)
        assert item is not None, f"missing {task} item in {split}"
        in_repo = item.resolve().is_relative_to(ITEMS.parent.parent.resolve())
        assert in_repo == (split in {"dev", "regression"}), (task, split, item)
        if split == "test-restricted":
            marker = json.loads((item / ".varde-split.json").read_text())
            assert marker == {"task_id": task, "split": split}, (task, marker)


def test_cpp_b_items_have_all_distinct_versions_and_pair_metadata() -> None:
    for task in EXPECTED_SPLITS:
        item = item_for(task)
        assert item is not None, task
        expected_files = ITEM_FILES | (
            {"spec-profile.toml"} if task in PILOT_TASKS else set()
        )
        assert item_files(item) >= expected_files, (task, sorted(item_files(item)))
        assert len({digest(item / f"{version}.cpp") for version in VERSIONS}) == len(
            VERSIONS
        ), task
        if task in PILOT_TASKS:
            assert_pilot_pair_metadata(item)
            continue
        pair = json.loads((item / "pair.json").read_text())
        assert pair["task"] == task
        assert pair.get("pair_group", pair.get("pair_group_id")), task
        assert (pair["language"], pair["part"]) == ("cpp", "b")
        assert {record["right"] for record in pair["pairs"]} == {
            f"{version}.cpp" for version in VERSIONS[1:]
        }
        for record in pair["pairs"]:
            assert record["left"] == "sensible.cpp", task
            assert len(record["pair_id"]) == 24, task
            int(record["pair_id"], 16)


def assert_pilot_pair_metadata(item: Path) -> None:
    payload = json.loads((item / "pair.json").read_text())
    assert set(payload) == {"pair_group_id", "task", "language", "part", "pairs"}
    assert len(payload["pair_group_id"]) == 24
    int(payload["pair_group_id"], 16)
    assert payload["task"] == item.name
    assert (payload["language"], payload["part"]) == ("cpp", "b")
    assert {pair["right"] for pair in payload["pairs"]} == {
        f"{version}.cpp" for version in VERSIONS if version != "sensible"
    }
    for pair in payload["pairs"]:
        assert set(pair) == {
            "pair_id",
            "left_id",
            "right_id",
            "left",
            "right",
            "left_role",
            "right_role",
        }
        for field in ("pair_id", "left_id", "right_id"):
            assert len(pair[field]) == 24
            int(pair[field], 16)
        assert pair["left"] == "sensible.cpp"
        assert pair["left_role"] == "sensible"
        expected_role = (
            "over-monolith" if pair["right"] == "monolith.cpp" else "over-split"
        )
        assert pair["right_role"] == expected_role
        assert (item / pair["left"]).is_file()
        assert (item / pair["right"]).is_file()


def test_cpp_b_items_pass_spec_behaviour_and_hygiene() -> None:
    for task in EXPECTED_SPLITS:
        item = item_for(task)
        assert item is not None, task
        if task in PILOT_TASKS:
            with (item / "spec-profile.toml").open("rb") as profile_file:
                assert tomllib.load(profile_file)["profile"] == "layered"
        for tool in ("item_spec_check.py", "behaviour_runner.py", "hygiene.py"):
            result = run_tool(tool, item)
            assert result.returncode == 0, (
                task,
                tool,
                result.stdout[-600:],
                result.stderr[-600:],
            )
