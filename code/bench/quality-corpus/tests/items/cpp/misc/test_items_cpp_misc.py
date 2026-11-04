"""Validate the C++ misc golden items: counts, sides, aux cases and splits.

Behaviour is checked by ``tools/behaviour_runner.py``; this module checks the
item data only. The restricted store is read from ``VARDE_GOLDEN_RESTRICTED``
and the restricted checks skip when it is unavailable.
"""

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
ITEMS = ROOT / "items" / "cpp" / "misc"
HYGIENE = ROOT / "tools" / "hygiene.py"
AUX_TASKS = ROOT / "taskbank" / "aux-tasks.json"
STORE_ENV = "VARDE_GOLDEN_RESTRICTED"
STORE_SUFFIX = "-cpp"

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
ANCHOR_TASKS = ("anchor-ledger", "anchor-queue")
BASE_FILES = {"behaviour_test.cpp", "manifest.toml", "pair.json", "task.txt"}
SIDE_FILES = {"a": ("good.cpp", "bad.cpp"), "e": ("excellent.cpp", "poor.cpp")}
BANK = {task["id"]: task for task in json.loads(AUX_TASKS.read_text())["tasks"]}


def item_dirs(split: str) -> dict[str, Path]:
    """Return the item directories of one split, keyed by task id."""
    base = ITEMS if split == "dev" else restricted_store()
    found = {}
    for manifest_path in base.rglob("manifest.toml"):
        task = manifest_path.parent.name.removesuffix(STORE_SUFFIX)
        if task not in EXPECTED_SPLITS:
            continue
        manifest = tomllib.loads(manifest_path.read_text())
        if manifest.get("language") == "cpp":
            found[task] = manifest_path.parent
    return found


def restricted_store() -> Path:
    value = os.environ.get(STORE_ENV, "")
    if not value:
        pytest.skip(f"{STORE_ENV} is not set, so the restricted store is unavailable")
    root = Path(value).expanduser()
    if not root.is_dir():
        pytest.skip(f"the restricted store does not exist: {root}")
    return root


def render_int_list(values: list[int]) -> str:
    return "{" + ", ".join(str(value) for value in values) + "}"


def render_names(names: list[str]) -> str:
    return "{" + ", ".join(f'"{name}"' for name in names) + "}"


def render_jobs(jobs: list[dict]) -> str:
    entries = ", ".join(f'{{"{job["name"]}", {job["priority"]}}}' for job in jobs)
    return "{" + entries + "}"


def case_statement(task: str, case: dict) -> str:
    """Render one bank case in the form the shared behaviour test writes it."""
    inputs = case["input"]
    expected = case["expected"]
    if task == "structured-booking":
        call = f"bookingCharge({inputs['rate']}, {inputs['nights']}, {inputs['fee']})"
    elif task == "structured-allowance":
        expenses = render_int_list(inputs["expenses"])
        call = f"remainingAllowance({inputs['start']}, {expenses})"
    elif task == "structured-gratuity":
        return (
            f"checkAmount({expected['gratuity']}, {expected['total']}, "
            f"gratuityFor({inputs['bill']}, {inputs['percent']}));"
        )
    elif task == "structured-distance":
        return f"check({expected}, kilometresToMiles({inputs}));"
    elif task == "structured-cart-count":
        return f"check({expected}, totalUnits({render_int_list(inputs)}));"
    elif task == "structured-temperature":
        return f"check({expected}, celsiusToFahrenheit({inputs}));"
    elif task == "anchor-ledger":
        entries = render_int_list(inputs["entries"])
        call = f"balance({inputs['opening']}, {entries})"
    elif task == "anchor-queue":
        names = render_names(expected)
        jobs = render_jobs(inputs["jobs"])
        return f"checkNames({names}, {jobs}, {inputs['minimum']});"
    else:
        raise AssertionError(f"unknown task: {task}")
    return f"check({expected}, {call});"


def check_task_text(directory: Path, task: str) -> None:
    statement, domain = (directory / "task.txt").read_text().split("\n", 1)
    assert statement == BANK[task]["behaviour"]
    assert domain.strip() == f"Input domain: {BANK[task]['input_domain']}"


def check_cases(directory: Path, task: str) -> None:
    source = (directory / "behaviour_test.cpp").read_text()
    statements = [case_statement(task, case) for case in BANK[task]["cases"]]
    assert len(set(statements)) == len(statements)
    for statement in statements:
        assert statement in source, f"{task}: shared test lacks {statement}"


def check_hygiene(directory: Path) -> None:
    result = subprocess.run(  # noqa: S603 - Runs the configured compiler on the test fixture.
        [sys.executable, str(HYGIENE), "--items", str(directory), "--check"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"{directory}: {result.stdout}{result.stderr}"


def check_split(directory: Path, task: str, split: str) -> None:
    if split == "dev":
        assert directory.is_relative_to(ITEMS)
        assert not (directory / ".varde-split.json").exists()
        return
    assert not directory.is_relative_to(ROOT)
    assert directory.name == f"{task}{STORE_SUFFIX}"
    marker = json.loads((directory / ".varde-split.json").read_text())
    assert marker == {"task_id": task, "split": split}


def check_item(task: str, directory: Path, split: str) -> str:
    manifest = tomllib.loads((directory / "manifest.toml").read_text())
    pair = json.loads((directory / "pair.json").read_text())
    category = "e" if task in ANCHOR_TASKS else "a"
    assert manifest["category"] == category
    assert manifest["language"] == "cpp"
    assert pair["pair_group_id"] == manifest["pair_group_id"]
    assert len(pair["pair_group_id"]) == 24
    assert len(pair["pair_id"]) == 24
    assert "task" not in pair
    sides = SIDE_FILES[category]
    expected_files = BASE_FILES | set(sides)
    if split != "dev":
        expected_files.add(".varde-split.json")
    assert {path.name for path in directory.iterdir()} == expected_files
    assert (pair["left"], pair["right"]) == sides
    digests = {
        hashlib.sha256((directory / name).read_bytes()).digest() for name in sides
    }
    assert len(digests) == 2
    if category == "a":
        assert manifest["dominant_defect"] == EXPECTED_DEFECTS[task]
        assert pair["dominant_defect"] == EXPECTED_DEFECTS[task]
        assert (pair["left_role"], pair["right_role"]) == ("good", "bad")
    else:
        assert (pair["left_role"], pair["right_role"]) == ("excellent", "poor")
    check_task_text(directory, task)
    check_cases(directory, task)
    check_hygiene(directory)
    check_split(directory, task, split)
    return category


def test_cpp_toolchain_is_available() -> None:
    assert shutil.which("g++") or shutil.which("clang++"), (
        "the C++ toolchain (g++ or clang++) is required"
    )


@pytest.mark.parametrize("split", ("dev", "test-restricted"))
def test_cpp_misc_items_match_the_expected_layout(split: str) -> None:
    expected = {task for task, value in EXPECTED_SPLITS.items() if value == split}
    items = item_dirs(split)
    assert set(items) == expected
    categories = [check_item(task, items[task], split) for task in sorted(items)]
    anchors = [task for task in expected if task in ANCHOR_TASKS]
    assert len(anchors) == 1
    assert categories.count("a") == len(expected) - 1
    assert categories.count("e") == 1
