"""Structure checks for the TypeScript misc golden items.

Data validation only: item counts, declared versions, differing sides, and the
auxiliary bank cases appearing verbatim in each shared behaviour test.
"""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

import pytest
from place_item import restricted_root

ROOT = Path(__file__).resolve().parents[4]
ITEMS = ROOT / "items" / "typescript" / "misc"
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
IMPORT = re.compile(r'import \{ (\w+) \} from "\./solution\.ts";')


def tasks_with_split(split: str) -> list[str]:
    return sorted(task for task, value in EXPECTED_SPLITS.items() if value == split)


def render(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(render(item) for item in value) + "]"
    if isinstance(value, dict):
        pairs = (f"{key}: {render(item)}" for key, item in value.items())
        return "{ " + ", ".join(pairs) + " }"
    raise TypeError(f"unsupported case value: {value!r}")


def case_line(entry: str, case: dict) -> str:
    case_input = case["input"]
    args = (
        ", ".join(render(value) for value in case_input.values())
        if isinstance(case_input, dict)
        else render(case_input)
    )
    expected = case["expected"]
    call = f"{entry}({args})"
    if isinstance(expected, list | dict):
        return f"assert.deepStrictEqual({call}, {render(expected)});"
    return f"assert.equal({call}, {render(expected)});"


def check_task_text(directory: Path, task: str) -> None:
    bank_task = BANK[task]
    statement, domain = (directory / "task.txt").read_text().split("\n", 1)
    assert statement == bank_task["behaviour"]
    assert domain.strip() == f"Input domain: {bank_task['input_domain']}"


def check_behaviour_test(directory: Path, task: str) -> None:
    text = (directory / "behaviour_test.ts").read_text()
    match = IMPORT.search(text)
    assert match is not None, "behaviour test must import the solution entry point"
    cases = BANK[task]["cases"]
    for case in cases:
        assert case_line(match.group(1), case) in text
    assert text.count("assert.") == len(cases)


def check_item(directory: Path, task: str, split: str) -> None:
    manifest = tomllib.loads((directory / "manifest.toml").read_text())
    pair = json.loads((directory / "pair.json").read_text())
    assert manifest["language"] == "typescript"
    assert pair["pair_group_id"] == manifest["pair_group_id"]
    assert len(pair["pair_group_id"]) == 24
    assert len(pair["pair_id"]) == 24
    assert {"left_id", "right_id"} <= set(pair)
    assert "task" not in pair

    category = manifest["category"]
    assert category == ("e" if task.startswith("anchor-") else "a")
    sides = {"excellent.ts", "poor.ts"} if category == "e" else {"good.ts", "bad.ts"}
    assert {path.name for path in directory.glob("*.ts")} == sides | {
        "behaviour_test.ts"
    }
    assert {pair["left"], pair["right"]} == sides
    payloads = {(directory / name).read_bytes() for name in sides}
    assert len(payloads) == 2

    roles = ("excellent", "poor") if category == "e" else ("good", "bad")
    assert (pair["left_role"], pair["right_role"]) == roles
    assert (pair["left"], pair["right"]) == tuple(f"{role}.ts" for role in roles)
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
        if tomllib.loads(manifest_path.read_text()).get("language") != "typescript":
            continue
        found.append((task, marker.parent))
    return found


def test_typescript_misc_repo_items_are_complete() -> None:
    expected = tasks_with_split("dev")
    directories = {path.name: path for path in ITEMS.iterdir() if path.is_dir()}
    assert sorted(directories) == expected
    categories = []
    for task in expected:
        check_item(directories[task], task, "dev")
        manifest = tomllib.loads((directories[task] / "manifest.toml").read_text())
        categories.append(manifest["category"])
    assert sorted(categories) == ["a", "a", "a", "e"]


def test_typescript_misc_restricted_items_are_complete() -> None:
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
