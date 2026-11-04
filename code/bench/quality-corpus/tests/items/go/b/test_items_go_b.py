"""Structure checks for the Go (b) authoring items."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from place_item import restricted_root as store_root

ROOT = Path(__file__).resolve().parents[4]
ITEMS = ROOT / "items" / "go" / "b"
TOOLS = ROOT / "tools"
TASKS = ROOT / "taskbank" / "bank.json"
VERSIONS = ("sensible", "monolith", "tiny", "padded", "sizematched", "namematched")
PILOT_TASKS = {"order-quote", "clinic-booking"}
EXPECTED_SPLITS = {
    "price-order": "test-restricted",
    "shipping-quote": "test-restricted",
    "csv-summary": "regression",
    "shipment-state": "test-restricted",
    "inventory-adjustment": "test-restricted",
    "reservation-calendar": "dev",
    "order-quote": "dev",
    "clinic-booking": "dev",
}
REPO_SPLITS = {"regression", "dev"}
ITEM_FILES = {"behaviour_test.go", "pair.json"} | {f"{v}.go" for v in VERSIONS}
LOCK = TOOLS / "splits.lock"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def restricted_root() -> Path:
    return store_root() / "test-restricted"


def restricted_item(task: str) -> Path | None:
    base = restricted_root()
    if not base.is_dir():
        return None
    return next(iter(sorted(base.glob(f"*/{task}-go"))), None)


def repo_item(task: str) -> Path | None:
    item = ITEMS / task
    return item if item.is_dir() else None


def item_for(task: str) -> Path | None:
    split = EXPECTED_SPLITS[task]
    return repo_item(task) if split in REPO_SPLITS else restricted_item(task)


def item_files(item: Path) -> set[str]:
    return {path.name for path in item.iterdir() if path.name != ".varde-split.json"}


def bank() -> dict:
    return {task["id"]: task for task in json.loads(TASKS.read_text())["tasks"]}


def require_toolchain() -> None:
    if shutil.which("go") is None:
        pytest.skip("go toolchain unavailable on PATH")


def require_store() -> None:
    if not restricted_root().is_dir():
        pytest.skip(f"restricted store unavailable: {restricted_root()}")


def run_tool(name: str, item: Path) -> subprocess.CompletedProcess:
    command = [sys.executable, str(TOOLS / name), "--items", str(item), "--check"]
    return subprocess.run(command, check=False, capture_output=True, text=True)  # noqa: S603 - Runs the Go tool on the test fixture.


def findings(result: subprocess.CompletedProcess) -> list[dict]:
    parsed = []
    for line in result.stdout.splitlines():
        if line.startswith("{"):
            record = json.loads(line)
            if "kind" in record:
                parsed.append(record)
    return parsed


def test_go_items_are_in_their_locked_splits() -> None:
    require_store()
    for task, split in EXPECTED_SPLITS.items():
        item = item_for(task)
        assert item is not None, f"missing item for {task} ({split})"
        inside_repo = item.resolve().is_relative_to(ITEMS.parent.parent.resolve())
        assert inside_repo == (split in REPO_SPLITS), (task, split, item)
        if split not in REPO_SPLITS:
            marker = json.loads((item / ".varde-split.json").read_text())
            assert marker == {"task_id": task, "split": split}, (task, marker)


def test_go_items_have_complete_versions() -> None:
    require_store()
    for task in EXPECTED_SPLITS:
        item = item_for(task)
        assert item is not None, task
        expected_files = ITEM_FILES | (
            {"spec-profile.toml"} if task in PILOT_TASKS else set()
        )
        if task in {"order-quote", "clinic-booking"}:
            expected_files |= {"alt-pipeline.go", "alt-table.go", "alt-class.go"}
        assert item_files(item) == expected_files, (task, sorted(item_files(item)))
        hashes = {digest(item / f"{version}.go") for version in VERSIONS}
        assert len(hashes) == len(VERSIONS), task


def test_go_pair_files_describe_sensible_against_each_version() -> None:
    require_store()
    for task in EXPECTED_SPLITS:
        item = item_for(task)
        assert item is not None, task
        payload = json.loads((item / "pair.json").read_text())
        if task in PILOT_TASKS:
            assert_pilot_pair_metadata(item)
            continue
        assert payload["task"] == task, task
        assert payload["pair_group"] == task, task
        assert payload["language"] == "go", task
        assert payload["part"] == "b", task
        rights = {pair["right"] for pair in payload["pairs"]}
        assert rights == {f"{version}.go" for version in VERSIONS[1:]}, task
        for pair in payload["pairs"]:
            assert pair["left"] == "sensible.go", task
            assert len(pair["pair_id"]) == 24, (task, pair["pair_id"])
            int(pair["pair_id"], 16)


def assert_pilot_pair_metadata(item: Path) -> None:
    payload = json.loads((item / "pair.json").read_text())
    assert set(payload) == {"pair_group_id", "task", "language", "part", "pairs"}
    assert len(payload["pair_group_id"]) == 24
    int(payload["pair_group_id"], 16)
    assert payload["task"] == item.name
    assert payload["language"] == "go"
    assert payload["part"] == "b"
    expected_rights = {f"{version}.go" for version in VERSIONS if version != "sensible"}
    if item.name in {"order-quote", "clinic-booking"}:
        expected_rights |= {"alt-pipeline.go", "alt-table.go", "alt-class.go"}
    assert {pair["right"] for pair in payload["pairs"]} == expected_rights
    for pair in payload["pairs"]:
        alt = pair["right_role"] == "alt-good"
        fields = {
            "pair_id",
            "left_id",
            "right_id",
            "left",
            "right",
            "left_role",
            "right_role",
        }
        assert set(pair) == fields | ({"preference_neutral"} if alt else set())
        for field in ("pair_id", "left_id", "right_id"):
            assert len(pair[field]) == 24
            int(pair[field], 16)
        assert pair["left"] == "sensible.go"
        assert pair["left_role"] == "sensible"
        if alt:
            assert item.name in {"order-quote", "clinic-booking"}
            assert pair["right"] in {"alt-pipeline.go", "alt-table.go", "alt-class.go"}
            assert pair["preference_neutral"] is True
        else:
            expected_role = (
                "over-monolith" if pair["right"] == "monolith.go" else "over-split"
            )
            assert pair["right_role"] == expected_role
        assert (item / pair["left"]).is_file()
        assert (item / pair["right"]).is_file()


def test_go_items_pass_spec_behaviour_and_hygiene() -> None:
    require_toolchain()
    require_store()
    for task in EXPECTED_SPLITS:
        item = item_for(task)
        assert item is not None, task
        if task in PILOT_TASKS:
            with (item / "spec-profile.toml").open("rb") as profile_file:
                profile = tomllib.load(profile_file)
                assert profile["profile"] == "layered"
                if task in {"order-quote", "clinic-booking"}:
                    assert profile["alts"] == ["alt-pipeline", "alt-table", "alt-class"]
        spec = run_tool("item_spec_check.py", item)
        remaining = findings(spec)
        assert not remaining, (task, remaining[:4])
        assert spec.returncode == 0, (task, spec.stderr[-400:])
        behaviour = run_tool("behaviour_runner.py", item)
        assert behaviour.returncode == 0, (
            task,
            behaviour.stdout[-400:],
            behaviour.stderr[-400:],
        )
        hygiene = run_tool("hygiene.py", item)
        assert hygiene.returncode == 0, (task, hygiene.stdout[-400:])


def test_authored_task_list_matches_the_language_subset() -> None:
    subsets = json.loads(TASKS.read_text())["language_subsets"]
    assert set(EXPECTED_SPLITS) - PILOT_TASKS == set(subsets["go"])


def test_pilots_are_assigned_to_the_dev_split() -> None:
    assignments = json.loads(LOCK.read_text())["assignments"]
    assert {task: assignments[task] for task in PILOT_TASKS} == dict.fromkeys(
        PILOT_TASKS, "dev"
    )
