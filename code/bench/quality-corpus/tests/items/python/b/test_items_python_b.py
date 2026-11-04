"""Data checks for the python part b items: version files, pair metadata, and
bank cases."""

import ast
import hashlib
import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from place_item import restricted_root
from splits import assign

ROOT = Path(__file__).resolve().parents[4]
ITEMS = ROOT / "items" / "python" / "b"
BANK = ROOT / "taskbank" / "bank.json"
SPEC_CHECK = ROOT / "tools" / "item_spec_check.py"
VERSIONS = ("sensible", "monolith", "tiny", "padded", "sizematched", "namematched")
REPO_TASKS = ("csv-summary", "invoice-aging")
PILOT_TASKS = ("order-quote", "clinic-booking", "shift-pay", "rental-quote")
RESTRICTED_TASKS = ("scoreboard", "shipping-quote", "shipment-state", "text-template")
HEX_DIGITS = set("0123456789abcdef")


def task_digest(task: str) -> str:
    return hashlib.sha256(task.encode()).hexdigest()[:24]


def restricted_item(task: str) -> Path:
    return restricted_root() / assign(task) / task_digest(task) / f"{task}-python"


def bank_cases() -> dict[str, list]:
    tasks = json.loads(BANK.read_text())["tasks"]
    return {task["id"]: task["cases"] for task in tasks}


def behaviour_cases(item: Path) -> list:
    module = ast.parse((item / "behaviour_test.py").read_text())
    for node in module.body:
        if (
            isinstance(node, ast.Assign)
            and getattr(node.targets[0], "id", "") == "CASES"
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"behaviour test declares no CASES: {item}")


def version_paths(item: Path) -> list[Path]:
    return [item / f"{name}.py" for name in VERSIONS]


def assert_six_distinct_versions(item: Path) -> None:
    paths = version_paths(item)
    missing = [str(path) for path in paths if not path.is_file()]
    assert not missing, missing
    digests = {hashlib.sha256(path.read_bytes()).digest() for path in paths}
    assert len(digests) == len(paths)


def assert_opaque_ids(entry: dict) -> None:
    for field in ("pair_id", "left_id", "right_id"):
        value = str(entry[field])
        assert len(value) >= 24
        assert set(value) <= HEX_DIGITS


def assert_pair_metadata(item: Path, task: str) -> None:
    pair = json.loads((item / "pair.json").read_text())
    assert pair["pair_group_id"] == task_digest(task)
    assert pair["task"] == task
    assert pair["language"] == "python"
    rights = []
    for entry in pair["pairs"]:
        assert entry["left"] == "sensible.py"
        rights.append(entry["right"])
        assert_opaque_ids(entry)
    others = [f"{name}.py" for name in VERSIONS if name != "sensible"]
    assert sorted(rights) == sorted(others)


def assert_pilot_pair_metadata(item: Path) -> None:
    pair = json.loads((item / "pair.json").read_text())
    assert set(pair) == {"pair_group_id", "task", "language", "pairs"}
    assert len(pair["pair_group_id"]) >= 24
    assert set(pair["pair_group_id"]) <= HEX_DIGITS
    assert pair["task"] == item.name
    assert pair["language"] == "python"
    assert isinstance(pair["pairs"], list)
    for entry in pair["pairs"]:
        keys = {
            "pair_id",
            "left_id",
            "right_id",
            "left",
            "right",
            "left_role",
            "right_role",
        }
        alt = entry.get("right_role") == "alt-good"
        assert set(entry) == keys | ({"preference_neutral"} if alt else set())
        if alt:
            assert entry["preference_neutral"] is True
            assert entry["left_role"] == "sensible"
            assert entry["left"] == "sensible.py"
            assert entry["right"] in {
                "alt-pipeline.py",
                "alt-table.py",
                "alt-class.py",
            }
        else:
            assert "preference_neutral" not in entry
        assert_opaque_ids(entry)
        assert (item / entry["left"]).is_file()
        assert (item / entry["right"]).is_file()


def assert_bank_cases_verbatim(item: Path, task: str) -> None:
    cases = bank_cases()[task]
    assert behaviour_cases(item) == [
        (case["input"], case["expected"]) for case in cases
    ]


def assert_item(item: Path, task: str) -> None:
    assert_six_distinct_versions(item)
    assert_pair_metadata(item, task)
    assert_bank_cases_verbatim(item, task)


def test_repository_items_hold_six_distinct_versions() -> None:
    found = sorted(path.name for path in ITEMS.iterdir() if path.is_dir())
    assert found == sorted(REPO_TASKS + PILOT_TASKS)
    for task in REPO_TASKS:
        assert_item(ITEMS / task, task)
    for task in PILOT_TASKS:
        item = ITEMS / task
        assert_six_distinct_versions(item)
        assert_pilot_pair_metadata(item)
        with (item / "spec-profile.toml").open("rb") as profile_file:
            assert tomllib.load(profile_file)["profile"] == "layered"
        result = subprocess.run(  # noqa: S603 - Runs the Python fixture in a child process.
            [sys.executable, str(SPEC_CHECK), "--items", str(item), "--check"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr


def test_item_spec_check_finds_no_violations() -> None:
    for task in REPO_TASKS:
        result = subprocess.run(  # noqa: S603 - Runs the Python fixture in a child process.
            [sys.executable, str(SPEC_CHECK), "--items", str(ITEMS / task), "--check"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr


def test_restricted_items_hold_six_distinct_versions() -> None:
    root = restricted_root()
    if not root.is_dir():
        pytest.skip(f"restricted golden store is not available: {root}")
    for task in RESTRICTED_TASKS:
        item = restricted_item(task)
        assert item.is_dir(), item
        assert_item(item, task)
