"""Structure checks for the Java misc golden items.

Data validation only: item counts, declared versions, differing sides, and the
auxiliary bank cases appearing verbatim in each shared behaviour test.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest
from place_item import restricted_root

ROOT = Path(__file__).resolve().parents[4]
ITEMS = ROOT / "items" / "java" / "misc"
BANK = {
    entry["id"]: entry
    for entry in json.loads((ROOT / "taskbank" / "aux-tasks.json").read_text())["tasks"]
}
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
SIDES = {"a": ("good.java", "bad.java"), "e": ("excellent.java", "poor.java")}


def tasks_with_split(split: str) -> list[str]:
    return sorted(task for task, value in EXPECTED_SPLITS.items() if value == split)


def render_int_array(values: list[int]) -> str:
    return "new int[] {" + ", ".join(str(value) for value in values) + "}"


def render_jobs(jobs: list[dict]) -> str:
    return ", ".join(
        f'new solution.Job("{job["name"]}", {job["priority"]})' for job in jobs
    )


def case_line(task: str, case: dict) -> str:
    """Render one bank case as it appears in the shared behaviour test."""
    inputs = case["input"]
    expected = case["expected"]
    if task == "structured-booking":
        args = f"{inputs['rate']}, {inputs['nights']}, {inputs['fee']}"
        return f"check({expected}, solution.solution({args}));"
    if task == "structured-allowance":
        args = f"{inputs['start']}, {render_int_array(inputs['expenses'])}"
        return f"check({expected}, solution.solution({args}));"
    if task == "structured-gratuity":
        return (
            f"checkAmount({expected['gratuity']}, {expected['total']}, "
            f"{inputs['bill']}, {inputs['percent']});"
        )
    if task in {"structured-distance", "structured-temperature"}:
        return f"check({expected}, solution.solution({inputs}));"
    if task == "structured-cart-count":
        return f"check({expected}, solution.solution({render_int_array(inputs)}));"
    if task == "anchor-ledger":
        args = f"{inputs['opening']}, {render_int_array(inputs['entries'])}"
        return f"check({expected}, solution.solution({args}));"
    if task == "anchor-queue":
        names = ", ".join(f'"{name}"' for name in expected)
        jobs = f", {render_jobs(inputs['jobs'])}" if inputs["jobs"] else ""
        return f"checkNames({inputs['minimum']}, List.of({names}){jobs});"
    raise ValueError(f"unknown bank task: {task}")


def check_task_text(directory: Path, task: str) -> None:
    bank_task = BANK[task]
    statement, domain = (directory / "task.txt").read_text().split("\n", 1)
    assert statement == bank_task["behaviour"]
    assert domain.strip() == f"Input domain: {bank_task['input_domain']}"


def check_behaviour_test(directory: Path, task: str) -> None:
    text = (directory / "behaviour_test.java").read_text()
    lines = [case_line(task, case) for case in BANK[task]["cases"]]
    assert len(set(lines)) == len(lines)
    for line in lines:
        assert line in text, f"{task}: shared test lacks bank case {line}"


def check_item(directory: Path, task: str, split: str) -> None:
    manifest = tomllib.loads((directory / "manifest.toml").read_text())
    pair = json.loads((directory / "pair.json").read_text())
    category = "e" if task.startswith("anchor-") else "a"
    assert manifest["category"] == category
    assert manifest["language"] == "java"
    assert pair["pair_group_id"] == manifest["pair_group_id"]
    assert len(pair["pair_group_id"]) == 24
    assert len(pair["pair_id"]) == 24
    assert {"left_id", "right_id"} <= set(pair)
    assert "task" not in pair

    sides = set(SIDES[category])
    assert {path.name for path in directory.glob("*.java")} == sides | {
        "behaviour_test.java"
    }
    assert {pair["left"], pair["right"]} == sides
    payloads = {(directory / name).read_bytes() for name in sides}
    assert len(payloads) == 2

    roles = ("excellent", "poor") if category == "e" else ("good", "bad")
    assert (pair["left_role"], pair["right_role"]) == roles
    assert (pair["left"], pair["right"]) == tuple(f"{role}.java" for role in roles)
    if category == "a":
        assert manifest["dominant_defect"] == EXPECTED_DEFECTS[task]
        assert pair["dominant_defect"] == EXPECTED_DEFECTS[task]

    marker = directory / ".varde-split.json"
    if split == "test-restricted":
        assert json.loads(marker.read_text()) == {"task_id": task, "split": split}
    else:
        assert not marker.exists()

    check_task_text(directory, task)
    check_behaviour_test(directory, task)


def restricted_items(base: Path) -> list[tuple[str, Path]]:
    found = []
    for marker in sorted(base.rglob(".varde-split.json")):
        task = json.loads(marker.read_text()).get("task_id")
        manifest_path = marker.parent / "manifest.toml"
        if task not in EXPECTED_SPLITS or not manifest_path.is_file():
            continue
        if tomllib.loads(manifest_path.read_text()).get("language") != "java":
            continue
        found.append((task, marker.parent))
    return found


def test_java_misc_repo_items_are_complete() -> None:
    expected = tasks_with_split("dev")
    directories = {path.name: path for path in ITEMS.iterdir() if path.is_dir()}
    assert sorted(directories) == expected
    categories = []
    for task in expected:
        check_item(directories[task], task, "dev")
        manifest = tomllib.loads((directories[task] / "manifest.toml").read_text())
        categories.append(manifest["category"])
    assert sorted(categories) == ["a", "a", "a", "e"]


def test_java_misc_restricted_items_are_complete() -> None:
    base = restricted_root()
    if not base.is_dir():
        pytest.skip(f"restricted store is absent: {base}")
    expected = tasks_with_split("test-restricted")
    entries = restricted_items(base)
    tasks = [task for task, _ in entries]
    assert len(set(tasks)) == len(tasks)
    assert sorted(tasks) == expected
    found = dict(entries)
    categories = []
    for task in expected:
        directory = found[task]
        assert not directory.is_relative_to(ROOT)
        assert not (ITEMS / task).exists()
        check_item(directory, task, "test-restricted")
        manifest = tomllib.loads((directory / "manifest.toml").read_text())
        categories.append(manifest["category"])
    assert sorted(categories) == ["a", "a", "a", "e"]
