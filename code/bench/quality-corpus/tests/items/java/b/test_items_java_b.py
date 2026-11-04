"""Structure checks for the Java (b) authoring items.

Data validation only: item counts, declared versions, differing sides, pair
manifests, and the restricted items living outside the repository. The
behaviour test itself is exercised through the shared runner, never by reading
its text.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from place_item import restricted_root

ROOT = Path(__file__).resolve().parents[4]
ITEMS = ROOT / "items" / "java" / "b"
TOOLS = ROOT / "tools"
BANK = json.loads((ROOT / "taskbank" / "bank.json").read_text())
SUBSET = set(BANK["language_subsets"]["java"])
EXPECTED_SPLITS = {
    "csv-summary": "regression",
    "price-order": "test-restricted",
    "retry-policy": "test-restricted",
    "shipment-state": "test-restricted",
    "inventory-adjustment": "test-restricted",
    "text-template": "test-restricted",
}
VERSIONS = ("sensible", "monolith", "tiny", "padded", "sizematched", "namematched")
EXPECTED_FILES = {f"{version}.java" for version in VERSIONS} | {
    "behaviour_test.java",
    "pair.json",
}
PILOT_TASKS = {"order-quote", "clinic-booking"}


def tasks_with_split(split: str) -> list[str]:
    return sorted(task for task, value in EXPECTED_SPLITS.items() if value == split)


def item_files(item: Path) -> list[Path]:
    return sorted(
        path
        for path in item.iterdir()
        if path.is_file() and path.name != ".varde-split.json"
    )


def check_versions(item: Path, task: str, split: str) -> None:
    names = {path.name for path in item_files(item)}
    expected = EXPECTED_FILES | (
        {"spec-profile.toml"} if task in PILOT_TASKS else set()
    )
    assert names == expected, (task, sorted(names))
    payloads = {(item / f"{version}.java").read_bytes() for version in VERSIONS}
    assert len(payloads) == len(VERSIONS), task
    assert (item / "behaviour_test.java").stat().st_size > 0, task
    marker = item / ".varde-split.json"
    if split == "test-restricted":
        assert json.loads(marker.read_text()) == {"task_id": task, "split": split}
    else:
        assert not marker.exists(), task


def check_pair(item: Path, task: str) -> None:
    payload = json.loads((item / "pair.json").read_text())
    assert payload["task"] == task, task
    assert payload["language"] == "java", task
    assert payload["part"] == "b", task
    assert len(payload["pair_group_id"]) == 24, task
    int(payload["pair_group_id"], 16)
    pairs = payload["pairs"]
    assert {pair["right"] for pair in pairs} == {
        f"{version}.java" for version in VERSIONS[1:]
    }, task
    assert {pair["left"] for pair in pairs} == {"sensible.java"}, task
    roles = {pair["right"]: pair["right_role"] for pair in pairs}
    assert roles["monolith.java"] == "over-monolith", task
    assert {role for name, role in roles.items() if name != "monolith.java"} == {
        "over-split"
    }, task
    for key in ("pair_id", "right_id"):
        values = [pair[key] for pair in pairs]
        assert len(set(values)) == len(values), (task, key)
    for value in [payload["pair_group_id"]] + [
        pair[key] for pair in pairs for key in ("pair_id", "left_id", "right_id")
    ]:
        assert len(value) == 24, task
        int(value, 16)


def check_pilot_pair_metadata(item: Path, task: str) -> None:
    payload = json.loads((item / "pair.json").read_text())
    assert set(payload) == {"pair_group_id", "task", "language", "part", "pairs"}
    assert payload["task"] == task
    assert payload["language"] == "java"
    assert payload["part"] == "b"
    assert isinstance(payload["pairs"], list)
    assert {pair["right"] for pair in payload["pairs"]} == {
        f"{version}.java" for version in VERSIONS[1:]
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
        assert pair["left"] == "sensible.java"
        assert (item / pair["left"]).is_file()
        assert (item / pair["right"]).is_file()


def restricted_items() -> dict[str, Path]:
    base = restricted_root() / "test-restricted"
    if not base.is_dir():
        return {}
    found = {}
    for marker in sorted(base.rglob(".varde-split.json")):
        record = json.loads(marker.read_text())
        task = record.get("task_id")
        pair = marker.parent / "pair.json"
        if task not in EXPECTED_SPLITS or not pair.is_file():
            continue
        if json.loads(pair.read_text()).get("language") != "java":
            continue
        found[task] = marker.parent
    return found


def all_items() -> list[Path]:
    items = [
        ITEMS / task for task in tasks_with_split("regression") + sorted(PILOT_TASKS)
    ]
    found = restricted_items()
    items.extend(
        found[task] for task in tasks_with_split("test-restricted") if task in found
    )
    return items


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


def java_toolchain() -> bool:
    return all(shutil.which(name) for name in ("javac", "java"))


def test_java_subset_matches_the_bank() -> None:
    assert set(EXPECTED_SPLITS) == SUBSET


def test_repository_items_cover_the_unrestricted_tasks() -> None:
    assert ITEMS.is_dir(), f"repository items directory is missing: {ITEMS}"
    directories = sorted(path.name for path in ITEMS.iterdir() if path.is_dir())
    assert directories == sorted(tasks_with_split("regression") + sorted(PILOT_TASKS))


def test_repository_items_have_complete_versions_and_pairs() -> None:
    for task in tasks_with_split("regression") + sorted(PILOT_TASKS):
        item = ITEMS / task
        check_versions(item, task, "regression")
        if task in PILOT_TASKS:
            with (item / "spec-profile.toml").open("rb") as profile_file:
                assert tomllib.load(profile_file)["profile"] == "layered"
            check_pilot_pair_metadata(item, task)
        check_pair(item, task)


def test_restricted_items_are_complete_and_outside_the_repository() -> None:
    if not (restricted_root() / "test-restricted").is_dir():
        pytest.skip(f"restricted store is absent: {restricted_root()}")
    found = restricted_items()
    assert sorted(found) == tasks_with_split("test-restricted")
    for task in tasks_with_split("test-restricted"):
        item = found[task]
        assert not item.resolve().is_relative_to(ROOT.resolve()), task
        assert not (ITEMS / task).exists(), task
        check_versions(item, task, "test-restricted")
        check_pair(item, task)


def test_items_pass_spec_and_hygiene() -> None:
    items = all_items()
    assert items, "no Java (b) items were found"
    for item in items:
        if item.name in PILOT_TASKS:
            with (item / "spec-profile.toml").open("rb") as profile_file:
                assert tomllib.load(profile_file)["profile"] == "layered"
        spec = run_tool("item_spec_check.py", item)
        assert not findings(spec), (item.name, findings(spec))
        assert spec.returncode == 0, (item.name, spec.stderr[-400:])
        hygiene = run_tool("hygiene.py", item)
        assert hygiene.returncode == 0, (item.name, hygiene.stdout[-400:])


def test_java_toolchain_is_available() -> None:
    assert java_toolchain(), "the java toolchain (javac and java) is required"


def test_items_pass_their_behaviour_tests() -> None:
    items = all_items()
    assert items, "no Java (b) items were found"
    for item in items:
        behaviour = run_tool("behaviour_runner.py", item)
        assert behaviour.returncode == 0, (item.name, behaviour.stdout[-400:])
