"""Structure checks for the Go misc golden items: six pairs and two anchors.

Behaviour itself is verified by ``tools/behaviour_runner.py``; this file checks the
item data only: the split each task belongs to, the expected versions, distinct
sides, and that every shared behaviour test encodes the task bank's cases.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
REPO_ROOT = ROOT.parents[2]
ITEMS = ROOT / "items" / "go" / "misc"
HYGIENE = ROOT / "tools" / "hygiene.py"
AUX_TASKS = ROOT / "taskbank" / "aux-tasks.json"
LOCK_CANDIDATES = (ROOT / "tools" / "splits.lock", ROOT / "splits.lock")
STORE_ENV = "VARDE_GOLDEN_RESTRICTED"
RESTRICTED_SUFFIX = "-go"
SPLIT_MARKER = ".varde-split.json"
OPAQUE_ID = re.compile(r"[0-9a-f]{24}")

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
SIDES = {"a": ("good.go", "bad.go"), "e": ("excellent.go", "poor.go")}
BASE_FILES = {"behaviour_test.go", "manifest.toml", "pair.json", "task.txt"}
INPUT_LAYOUT = {
    "structured-booking": (("rate", "number"), ("nights", "number"), ("fee", "number")),
    "structured-allowance": (("start", "number"), ("expenses", "int-list")),
    "structured-gratuity": (("bill", "number"), ("percent", "number")),
    "structured-distance": (("kilometres", "number"),),
    "structured-cart-count": (("quantities", "int-list"),),
    "structured-temperature": (("celsius", "number"),),
    "anchor-ledger": (("opening", "number"), ("entries", "int-list")),
    "anchor-queue": (("jobs", "job-list"), ("minimum", "number")),
}
BANK = {task["id"]: task for task in json.loads(AUX_TASKS.read_text())["tasks"]}


def item_dirs(split: str) -> dict[str, Path]:
    """Return the item directories of one split, keyed by task id."""
    if split == "dev":
        return language_items(ITEMS)
    return language_items(store_root())


def language_items(base: Path) -> dict[str, Path]:
    items = {}
    for manifest_path in base.rglob("manifest.toml"):
        manifest = tomllib.loads(manifest_path.read_text())
        if manifest.get("language") != "go":
            continue
        task = manifest_path.parent.name.removesuffix(RESTRICTED_SUFFIX)
        if task in EXPECTED_SPLITS:
            items[task] = manifest_path.parent
    return items


def store_root() -> Path:
    configured = os.environ.get(STORE_ENV, "")
    root = Path(configured) if configured else None
    if root is None or not root.is_dir():
        pytest.skip(f"{STORE_ENV} is unset or missing: restricted store unavailable")
    return root


def render_value(kind: str, value: object) -> str:
    if kind == "number":
        return repr(value)
    if kind == "int-list":
        return "[]int{" + ", ".join(repr(item) for item in value) + "}"
    if kind == "string-list":
        return "[]string{" + ", ".join(json.dumps(item) for item in value) + "}"
    if kind == "job-list":
        rendered = ", ".join(
            f"{{name: {json.dumps(job['name'])}, priority: {job['priority']}}}"
            for job in value
        )
        return "[]job{" + rendered + "}"
    raise ValueError(f"unknown bank field kind: {kind}")


def case_line(task: str, case: dict) -> str:
    """Render one bank case in the form the shared behaviour test writes it."""
    inputs = case["input"]
    expected = case["expected"]
    layout = INPUT_LAYOUT[task]
    if isinstance(inputs, dict):
        fields = [(name, kind, inputs[name]) for name, kind in layout]
    else:
        name, kind = layout[0]
        fields = [(name, kind, inputs)]
    if task == "structured-gratuity":
        fields.append(("wantGratuity", "number", expected["gratuity"]))
        fields.append(("wantTotal", "number", expected["total"]))
    elif task == "anchor-queue":
        fields.append(("want", "string-list", expected))
    else:
        fields.append(("want", "number", expected))
    rendered = ", ".join(
        f"{name}: {render_value(kind, value)}" for name, kind, value in fields
    )
    return "{" + rendered + "},"


@pytest.mark.parametrize("split", ("dev", "test-restricted"))
def test_go_misc_items_are_on_the_locked_split(split: str) -> None:
    expected = {task for task, assigned in EXPECTED_SPLITS.items() if assigned == split}
    assert set(item_dirs(split)) == expected


def test_go_misc_lock_agrees_with_the_expected_splits() -> None:
    lock = next((path for path in LOCK_CANDIDATES if path.is_file()), None)
    if lock is None:
        pytest.skip("no splits.lock in this checkout")
    assignments = json.loads(lock.read_text())["assignments"]
    assert {task: assignments[task] for task in EXPECTED_SPLITS} == EXPECTED_SPLITS


@pytest.mark.parametrize("split", ("dev", "test-restricted"))
def test_go_misc_items_have_expected_metadata(split: str) -> None:
    items = item_dirs(split)
    expected = {task for task, assigned in EXPECTED_SPLITS.items() if assigned == split}
    assert set(items) == expected
    for task, directory in items.items():
        check_item(task, directory, split)


def check_item(task: str, directory: Path, split: str) -> None:
    manifest = tomllib.loads((directory / "manifest.toml").read_text())
    pair = json.loads((directory / "pair.json").read_text())
    category = "e" if task in ANCHOR_TASKS else "a"
    assert manifest["category"] == category
    assert manifest["language"] == "go"
    assert manifest["pair_group_id"] == pair["pair_group_id"]
    assert OPAQUE_ID.fullmatch(pair["pair_group_id"])
    assert OPAQUE_ID.fullmatch(pair["pair_id"])
    assert OPAQUE_ID.fullmatch(pair["left_id"])
    assert OPAQUE_ID.fullmatch(pair["right_id"])
    excellent, poor = SIDES[category]
    if category == "a":
        assert manifest["dominant_defect"] == EXPECTED_DEFECTS[task]
        assert pair["dominant_defect"] == EXPECTED_DEFECTS[task]
        assert pair["left_role"] == "good"
        assert pair["right_role"] == "bad"
    else:
        assert manifest["left_role"] == "excellent"
        assert manifest["right_role"] == "poor"
        assert pair["left_role"] == "excellent"
        assert pair["right_role"] == "poor"
    assert (pair["left"], pair["right"]) == (excellent, poor)
    expected_files = BASE_FILES | {excellent, poor}
    if split != "dev":
        expected_files.add(SPLIT_MARKER)
    assert {path.name for path in directory.iterdir()} == expected_files
    digests = set()
    for name in (excellent, poor):
        digests.add(hashlib.sha256((directory / name).read_bytes()).digest())
    assert len(digests) == 2
    if split == "dev":
        assert directory.is_relative_to(ITEMS)
    else:
        assert not directory.is_relative_to(REPO_ROOT)
        marker = json.loads((directory / SPLIT_MARKER).read_text())
        assert marker == {"task_id": task, "split": split}


@pytest.mark.parametrize("split", ("dev", "test-restricted"))
def test_go_misc_behaviour_tests_encode_the_bank_cases(split: str) -> None:
    for task, directory in item_dirs(split).items():
        source = (directory / "behaviour_test.go").read_text()
        lines = [case_line(task, case) for case in BANK[task]["cases"]]
        assert len(set(lines)) == len(lines)
        for line in lines:
            assert line in source, f"{task}: shared test lacks bank case {line}"
        task_text = (directory / "task.txt").read_text()
        assert BANK[task]["behaviour"] in task_text
        assert BANK[task]["input_domain"] in task_text


@pytest.mark.parametrize("split", ("dev", "test-restricted"))
def test_go_misc_items_pass_hygiene(split: str) -> None:
    for directory in item_dirs(split).values():
        result = subprocess.run(  # noqa: S603 - Runs the Go tool on the test fixture.
            [sys.executable, str(HYGIENE), "--items", str(directory), "--check"],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"{directory}: {result.stdout}{result.stderr}"
