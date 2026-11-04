"""Validate the rust misc golden items: counts, versions, aux cases and splits."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
ITEMS = ROOT / "items" / "rust" / "misc"
HYGIENE = ROOT / "tools" / "hygiene.py"
AUX_TASKS = ROOT / "taskbank" / "aux-tasks.json"
RESTRICTED_ENV = "VARDE_GOLDEN_RESTRICTED"
RESTRICTED_SUFFIX = "-rust"

EXPECTED_SPLITS = {
    "structured-booking": "test-restricted",
    "structured-allowance": "dev",
    "structured-gratuity": "dev",
    "structured-distance": "test-restricted",
    "structured-cart-count": "test-restricted",
    "structured-temperature": "dev",
    "anchor-ledger": "dev",
    "anchor-queue": "test-restricted",
}
EXPECTED_DEFECTS = {
    "structured-booking": "long-parameter-list",
    "structured-allowance": "copy-paste",
    "structured-gratuity": "unclear-names",
    "structured-distance": "deep-nesting",
    "structured-cart-count": "monolith",
    "structured-temperature": "mutable-flags",
}
DEV_TASKS = {task for task, split in EXPECTED_SPLITS.items() if split == "dev"}
RESTRICTED_TASKS = set(EXPECTED_SPLITS) - DEV_TASKS


def aux_cases() -> dict[str, list[dict]]:
    return {
        task["id"]: task["cases"] for task in json.loads(AUX_TASKS.read_text())["tasks"]
    }


def rust_task_directories(base: Path) -> dict[str, Path]:
    found = {}
    for manifest_path in base.rglob("manifest.toml"):
        name = manifest_path.parent.name
        task = name.removesuffix(RESTRICTED_SUFFIX)
        if task not in EXPECTED_SPLITS:
            continue
        if tomllib.loads(manifest_path.read_text()).get("language") == "rust":
            found[task] = manifest_path.parent
    return found


def restricted_store() -> Path:
    value = os.environ.get(RESTRICTED_ENV)
    if not value:
        pytest.skip(
            f"{RESTRICTED_ENV} is not set, so the restricted store is unavailable"
        )
    root = Path(value).expanduser()
    if not root.is_dir():
        pytest.skip(f"the restricted store does not exist: {root}")
    return root


def case_statement(task: str, case: dict) -> str:
    given = case["input"]
    expected = case["expected"]
    if task == "structured-booking":
        call = f"calculate({given['rate']}, {given['nights']}, {given['fee']})"
        result = str(expected)
    elif task == "structured-allowance":
        expenses = ", ".join(str(expense) for expense in given["expenses"])
        call = f"remaining({given['start']}, &[{expenses}])"
        result = str(expected)
    elif task == "structured-distance":
        call = f"miles({float(given)})"
        result = str(float(expected))
    elif task == "structured-cart-count":
        quantities = ", ".join(str(quantity) for quantity in given)
        call = f"unit_count(&[{quantities}])"
        result = str(expected)
    elif task == "structured-temperature":
        call = f"fahrenheit({float(given)})"
        result = str(float(expected))
    elif task == "structured-gratuity":
        call = f"gratuity({given['bill']}, {given['percent']})"
        result = f"({expected['gratuity']}, {expected['total']})"
    elif task == "anchor-ledger":
        entries = ", ".join(str(entry) for entry in given["entries"])
        call = f"balance({given['opening']}, &[{entries}])"
        result = str(expected)
    elif task == "anchor-queue":
        jobs = ", ".join(
            f'job("{job["name"]}", {job["priority"]})' for job in given["jobs"]
        )
        call = f"qualifying_names(&[{jobs}], {given['minimum']})"
        if expected:
            names = ", ".join(f'"{name}"' for name in expected)
            result = f"vec![{names}]"
        else:
            result = "Vec::<String>::new()"
    else:
        raise AssertionError(f"unknown task: {task}")
    return f"assert_eq!({call}, {result})"


def check_hygiene(directory: Path) -> None:
    result = subprocess.run(  # noqa: S603 - Runs the configured compiler on the test fixture.
        [sys.executable, str(HYGIENE), "--items", str(directory), "--check"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def validate_item(
    task: str, directory: Path, split: str, cases: dict
) -> tuple[str, dict]:
    manifest = tomllib.loads((directory / "manifest.toml").read_text())
    pair = json.loads((directory / "pair.json").read_text())
    category = manifest["category"]
    assert category == ("e" if task.startswith("anchor-") else "a")
    assert manifest["language"] == "rust"
    assert pair["pair_group_id"] == manifest["pair_group_id"]
    assert len(pair["pair_group_id"]) == 24
    assert len(pair["pair_id"]) == 24
    assert "task" not in pair
    sides = {"excellent.rs", "poor.rs"} if category == "e" else {"good.rs", "bad.rs"}
    assert {path.name for path in directory.glob("*.rs")} == sides | {
        "behaviour_test.rs"
    }
    assert {pair["left"], pair["right"]} == sides
    digests = {
        hashlib.sha256((directory / name).read_bytes()).digest() for name in sides
    }
    assert len(digests) == 2
    assert (directory / "task.txt").is_file()
    behaviour_test = (directory / "behaviour_test.rs").read_text()
    for case in cases[task]:
        statement = case_statement(task, case)
        assert statement in behaviour_test, statement
    check_hygiene(directory)
    if category == "a":
        assert manifest["dominant_defect"] == EXPECTED_DEFECTS[task]
    else:
        assert pair["left_role"] == "excellent"
        assert pair["right_role"] == "poor"
        assert pair["left"] == "excellent.rs"
        assert pair["right"] == "poor.rs"
        assert "dominant_defect" not in manifest
    if split == "test-restricted":
        record = json.loads((directory / ".varde-split.json").read_text())
        assert record == {"task_id": task, "split": split}
        assert not directory.is_relative_to(ROOT)
    return category, pair


def test_rust_toolchain_is_available() -> None:
    assert shutil.which("cargo"), "the rust toolchain (cargo) is required"


def test_rust_misc_public_items_match_the_expected_layout() -> None:
    cases = aux_cases()
    assert set(cases) == set(EXPECTED_SPLITS)
    public = rust_task_directories(ITEMS)
    assert set(public) == DEV_TASKS
    categories = [
        validate_item(task, public[task], "dev", cases)[0] for task in sorted(public)
    ]
    assert categories.count("a") == 3
    assert categories.count("e") == 1


def test_rust_misc_restricted_items_match_the_expected_layout() -> None:
    cases = aux_cases()
    store = restricted_store()
    restricted = rust_task_directories(store)
    assert set(restricted) == RESTRICTED_TASKS
    public = rust_task_directories(ITEMS)
    assert set(public) == DEV_TASKS
    checked = {
        task: validate_item(task, directory, EXPECTED_SPLITS[task], cases)
        for task, directory in {**public, **restricted}.items()
    }
    categories = [category for category, _ in checked.values()]
    assert categories.count("a") == 6
    assert categories.count("e") == 2
    assert len([pair for category, pair in checked.values() if category == "e"]) == 2
