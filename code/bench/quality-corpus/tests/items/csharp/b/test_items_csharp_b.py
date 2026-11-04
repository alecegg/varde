"""Structure checks for the C# (b) authoring items."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from place_item import restricted_root
from splits import assign

ROOT = Path(__file__).resolve().parents[4]
ITEMS = ROOT / "items" / "csharp" / "b"
TOOLS = ROOT / "tools"
TASKS = ROOT / "taskbank" / "bank.json"
TIERS = ROOT / "taskbank" / "tiers.json"
VERSIONS = ("sensible", "monolith", "tiny", "padded", "sizematched", "namematched")
EXPECTED_SPLITS = {
    "price-order": "test-restricted",
    "shipping-quote": "test-restricted",
    "retry-policy": "test-restricted",
    "inventory-adjustment": "test-restricted",
    "reservation-calendar": "dev",
    "invoice-aging": "dev",
    "order-quote": "dev",
    "clinic-booking": "dev",
}
REPO_SPLITS = {"regression", "dev"}
PILOT_TASKS = set(json.loads(TIERS.read_text())["tiers"]["rich"]) & set(EXPECTED_SPLITS)
ITEM_FILES = {"behaviour_test.cs", "pair.json"} | {
    f"{version}.cs" for version in VERSIONS
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def task_digest(task: str) -> str:
    return hashlib.sha256(task.encode()).hexdigest()[:24]


def repo_tasks() -> list[str]:
    return [task for task, split in EXPECTED_SPLITS.items() if split in REPO_SPLITS]


def restricted_tasks() -> list[str]:
    return [task for task, split in EXPECTED_SPLITS.items() if split not in REPO_SPLITS]


def restricted_item(task: str) -> Path:
    return restricted_root() / assign(task) / task_digest(task) / f"{task}-csharp"


def item_for(task: str) -> Path:
    if task in repo_tasks():
        return ITEMS / task
    return restricted_item(task)


def require_store() -> None:
    if not restricted_root().is_dir():
        pytest.skip(f"restricted golden store unavailable: {restricted_root()}")


def item_files(item: Path) -> set[str]:
    return {path.name for path in item.iterdir() if path.name != ".varde-split.json"}


def bank() -> dict:
    return json.loads(TASKS.read_text())


def require_toolchain() -> None:
    if shutil.which("dotnet") is None:
        pytest.skip("dotnet toolchain unavailable on PATH")


def run_tool(name: str, item: Path) -> subprocess.CompletedProcess:
    command = [sys.executable, str(TOOLS / name), "--items", str(item), "--check"]
    return subprocess.run(command, check=False, capture_output=True, text=True)  # noqa: S603 - Runs the configured compiler on the test fixture.


def findings(result: subprocess.CompletedProcess) -> list[dict]:
    parsed = []
    for line in result.stdout.splitlines():
        if line.startswith("{"):
            record = json.loads(line)
            if "kind" in record:
                parsed.append(record)
    return parsed


def check_versions(item: Path, task: str) -> None:
    expected = ITEM_FILES | ({"spec-profile.toml"} if task in PILOT_TASKS else set())
    assert item_files(item) == expected, (task, sorted(item_files(item)))
    hashes = {digest(item / f"{version}.cs") for version in VERSIONS}
    assert len(hashes) == len(VERSIONS), task


def assert_pilot_pair_metadata(item: Path) -> None:
    payload = json.loads((item / "pair.json").read_text())
    assert set(payload) == {"pair_group_id", "task", "language", "part", "pairs"}
    assert len(payload["pair_group_id"]) == 24
    int(payload["pair_group_id"], 16)
    assert payload["task"] == item.name
    assert payload["language"] == "csharp"
    assert payload["part"] == "b"
    assert {pair["right"] for pair in payload["pairs"]} == {
        f"{version}.cs" for version in VERSIONS if version != "sensible"
    }
    left_ids = set()
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
        assert pair["left"] == "sensible.cs"
        assert pair["left_role"] == "sensible"
        assert pair["right_role"] == (
            "over-monolith" if pair["right"] == "monolith.cs" else "over-split"
        )
        assert (item / pair["left"]).is_file()
        assert (item / pair["right"]).is_file()
        left_ids.add(pair["left_id"])
    assert len(left_ids) == 1
    assert len({pair["right_id"] for pair in payload["pairs"]}) == len(VERSIONS) - 1


def check_pair_file(item: Path, task: str) -> None:
    if task in PILOT_TASKS:
        assert_pilot_pair_metadata(item)
        return
    payload = json.loads((item / "pair.json").read_text())
    assert payload["task"] == task, task
    assert payload["pair_group"] == task, task
    assert payload["language"] == "csharp", task
    assert payload["part"] == "b", task
    rights = [pair["right"] for pair in payload["pairs"]]
    assert sorted(rights) == sorted(f"{version}.cs" for version in VERSIONS[1:]), task
    for pair in payload["pairs"]:
        assert pair["left"] == "sensible.cs", task
        assert len(pair["pair_id"]) == 24, (task, pair["pair_id"])
        int(pair["pair_id"], 16)


def check_tools(item: Path, task: str) -> None:
    spec = run_tool("item_spec_check.py", item)
    assert not findings(spec), (task, findings(spec)[:4])
    assert spec.returncode == 0, (task, spec.stdout[-400:], spec.stderr[-400:])
    behaviour = run_tool("behaviour_runner.py", item)
    assert behaviour.returncode == 0, (task, behaviour.stdout[-400:])
    hygiene = run_tool("hygiene.py", item)
    assert hygiene.returncode == 0, (task, hygiene.stdout[-400:])


def test_the_expected_splits_are_the_locked_language_subset() -> None:
    subsets = bank()["language_subsets"]
    assert set(EXPECTED_SPLITS) - PILOT_TASKS == set(subsets["csharp"]) - PILOT_TASKS
    for task, split in EXPECTED_SPLITS.items():
        assert assign(task) == split, (task, assign(task))
    assert repo_tasks() and restricted_tasks()


def test_repository_items_hold_the_complete_version_set() -> None:
    found = sorted(path.name for path in ITEMS.iterdir() if path.is_dir())
    assert found == sorted(repo_tasks())
    for task in repo_tasks():
        item = ITEMS / task
        check_versions(item, task)
        check_pair_file(item, task)
        if task in PILOT_TASKS:
            with (item / "spec-profile.toml").open("rb") as profile_file:
                assert tomllib.load(profile_file)["profile"] == "layered"


def test_restricted_items_hold_the_complete_version_set() -> None:
    require_store()
    store = restricted_root().resolve()
    for task in restricted_tasks():
        item = restricted_item(task)
        assert item.is_dir(), item
        assert item.resolve().is_relative_to(store), item
        assert item.resolve().parent.name == task_digest(task), item
        assert item.resolve().parent.parent.name == assign(task), item
        marker = json.loads((item / ".varde-split.json").read_text())
        assert marker == {"task_id": task, "split": assign(task)}, (task, marker)
        check_versions(item, task)
        check_pair_file(item, task)


def test_repository_items_pass_spec_behaviour_and_hygiene() -> None:
    require_toolchain()
    for task in repo_tasks():
        check_tools(ITEMS / task, task)


def test_restricted_items_pass_spec_behaviour_and_hygiene() -> None:
    require_store()
    require_toolchain()
    for task in restricted_tasks():
        check_tools(restricted_item(task), task)
