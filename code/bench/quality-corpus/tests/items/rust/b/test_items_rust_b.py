"""Structure checks for the Rust (b) authoring items.

The items are data: every task directory holds one sensible decomposition, one
monolith, and four over-split variants of the same behaviour, plus the shared
behaviour test and the pair manifest. These checks read that data, run the
authoring tools over it, and keep the test module names unique.
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
ITEMS = ROOT / "items" / "rust" / "b"
TESTS = ROOT / "tests" / "items"
TOOLS = ROOT / "tools"
LOCK = TOOLS / "splits.lock"
RESTRICTED_ENV = "VARDE_GOLDEN_RESTRICTED"
VERSIONS = ("sensible", "monolith", "tiny", "padded", "sizematched", "namematched")
ALTS = ("alt-pipeline", "alt-table", "alt-class")
OVER_SPLIT = ("tiny", "padded", "sizematched", "namematched")
DEV_TASKS = {"invoice-aging", "reservation-calendar"}
PILOT_TASKS = {"order-quote", "clinic-booking", "shift-pay", "rental-quote"}
RESTRICTED_TASKS = {"price-order", "retry-policy", "scoreboard", "shipping-quote"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def store_root() -> Path:
    """The restricted golden store: the configured one, else the tools' default."""
    configured = os.environ.get(RESTRICTED_ENV)
    if configured:
        return Path(configured).expanduser()
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import place_item; print(place_item.DEFAULT_RESTRICTED)",
        ],
        cwd=TOOLS,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr[-400:]
    return Path(result.stdout.strip())


def restricted_root() -> Path:
    root = store_root() / "test-restricted"
    if not root.is_dir():
        pytest.skip(f"the restricted store is unavailable: {root}")
    return root


def restricted_item(task: str) -> Path:
    item = next(iter(sorted(restricted_root().glob(f"*/{task}-rust"))), None)
    assert item is not None, f"missing restricted item for {task}"
    return item


def item_files(item: Path) -> list[Path]:
    return sorted(
        path
        for path in item.iterdir()
        if path.is_file() and path.name != ".varde-split.json"
    )


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


def dev_items() -> list[Path]:
    assert ITEMS.is_dir(), f"repository items directory is missing: {ITEMS}"
    return sorted(path for path in ITEMS.iterdir() if path.is_dir())


def locked_splits() -> dict[str, str]:
    payload = json.loads(LOCK.read_text())
    return dict(payload["assignments"])


def assert_versions(item: Path, task: str) -> None:
    names = {path.name for path in item_files(item)}
    for version in VERSIONS:
        assert f"{version}.rs" in names, (task, version)
    assert "behaviour_test.rs" in names, task
    assert "pair.json" in names, task
    hashes = {digest(item / f"{version}.rs") for version in VERSIONS}
    assert len(hashes) == len(VERSIONS), task


def assert_pairs(item: Path, task: str) -> None:
    payload = json.loads((item / "pair.json").read_text())
    assert payload["task"] == task, task
    assert payload["language"] == "rust", task
    assert len(payload["pair_group_id"]) == 24, task
    int(payload["pair_group_id"], 16)
    pairs = payload["pairs"]
    assert len(pairs) >= len(VERSIONS) - 1, task
    rights = {pair["right"] for pair in pairs}
    assert {f"{version}.rs" for version in VERSIONS[1:]} <= rights, task
    assert rights <= {f"{version}.rs" for version in VERSIONS[1:]} | {
        "alt-pipeline.rs",
        "alt-table.rs",
        "alt-class.rs",
    }, task
    for pair in pairs:
        assert pair["left"] == "sensible.rs", (task, pair["right"])
        assert pair["left_role"] == "sensible", (task, pair["right"])
        if pair["right_role"] == "alt-good":
            assert pair["preference_neutral"] is True
            assert pair["right"] in {"alt-pipeline.rs", "alt-table.rs", "alt-class.rs"}
        else:
            expected_role = (
                "over-monolith" if pair["right"] == "monolith.rs" else "over-split"
            )
            assert pair["right_role"] == expected_role, (task, pair["right"])
        for key in ("pair_id", "left_id", "right_id"):
            assert len(pair[key]) == 24, (task, pair["right"], key)
            int(pair[key], 16)
    for key in ("pair_id", "right_id"):
        values = [pair[key] for pair in pairs]
        assert len(set(values)) == len(values), (task, key)
    left_ids = {pair["left_id"] for pair in pairs}
    assert len(left_ids) == 1, task


def assert_pilot_pair_metadata(item: Path) -> None:
    payload = json.loads((item / "pair.json").read_text())
    assert set(payload) == {"pair_group_id", "task", "language", "pairs"}
    assert len(payload["pair_group_id"]) == 24
    int(payload["pair_group_id"], 16)
    assert payload["task"] == item.name
    assert payload["language"] == "rust"
    assert isinstance(payload["pairs"], list)
    expected_rights = {f"{version}.rs" for version in VERSIONS if version != "sensible"}
    if item.name in {"order-quote", "clinic-booking", "shift-pay", "rental-quote"}:
        expected_rights |= {"alt-pipeline.rs", "alt-table.rs", "alt-class.rs"}
    assert {pair["right"] for pair in payload["pairs"]} == expected_rights
    for pair in payload["pairs"]:
        keys = {
            "pair_id",
            "left_id",
            "right_id",
            "left",
            "right",
            "left_role",
            "right_role",
        }
        alt = pair.get("right_role") == "alt-good"
        assert set(pair) == keys | ({"preference_neutral"} if alt else set())
        if alt:
            assert pair["preference_neutral"] is True
            assert pair["left_role"] == "sensible"
            assert pair["right"] in {"alt-pipeline.rs", "alt-table.rs", "alt-class.rs"}
        else:
            assert "preference_neutral" not in pair
        for field in ("pair_id", "left_id", "right_id"):
            assert len(pair[field]) == 24
            int(pair[field], 16)
        assert pair["left"] == "sensible.rs"
        assert (item / pair["left"]).is_file()
        assert (item / pair["right"]).is_file()


def test_rust_toolchain_is_available() -> None:
    assert shutil.which("cargo"), "the rust toolchain (cargo) is required"


def test_repo_items_are_the_known_dev_tasks() -> None:
    assert {item.name for item in dev_items()} == DEV_TASKS | PILOT_TASKS


def test_repo_items_have_complete_versions() -> None:
    for item in dev_items():
        assert_versions(item, item.name)


def test_repo_pairs_describe_sensible_against_each_version() -> None:
    for item in dev_items():
        if item.name in PILOT_TASKS:
            assert_pilot_pair_metadata(item)
            assert_pairs(item, item.name)
            continue
        assert_pairs(item, item.name)


def test_repo_items_match_the_locked_split() -> None:
    assignments = locked_splits()
    for item in dev_items():
        assert assignments[item.name] == "dev", item.name


def test_repo_items_pass_spec_behaviour_and_hygiene() -> None:
    for item in dev_items():
        if item.name in PILOT_TASKS:
            profile = tomllib.loads((item / "spec-profile.toml").read_text())
            assert profile["profile"] == "layered"
        spec = run_tool("item_spec_check.py", item)
        assert not findings(spec), (item.name, findings(spec))
        assert spec.returncode == 0, (item.name, spec.stderr[-400:])
        behaviour = run_tool("behaviour_runner.py", item)
        assert behaviour.returncode == 0, (item.name, behaviour.stdout[-400:])
        hygiene = run_tool("hygiene.py", item)
        assert hygiene.returncode == 0, (item.name, hygiene.stdout[-400:])


def test_restricted_items_are_complete_and_outside_the_repository() -> None:
    assignments = locked_splits()
    for task in sorted(RESTRICTED_TASKS):
        item = restricted_item(task)
        assert not item.resolve().is_relative_to(ROOT.resolve()), task
        marker = json.loads((item / ".varde-split.json").read_text())
        assert marker == {"task_id": task, "split": assignments[task]}, task
        assert_versions(item, task)
        assert_pairs(item, task)


def test_restricted_items_pass_spec_behaviour_and_hygiene() -> None:
    for task in sorted(RESTRICTED_TASKS):
        item = restricted_item(task)
        spec = run_tool("item_spec_check.py", item)
        assert not findings(spec), (task, findings(spec))
        assert spec.returncode == 0, (task, spec.stderr[-400:])
        behaviour = run_tool("behaviour_runner.py", item)
        assert behaviour.returncode == 0, (task, behaviour.stdout[-400:])
        hygiene = run_tool("hygiene.py", item)
        assert hygiene.returncode == 0, (task, hygiene.stdout[-400:])


def test_item_test_modules_have_unique_basenames() -> None:
    basenames: dict[str, Path] = {}
    for path in sorted(TESTS.rglob("test_items_*.py")):
        assert path.name not in basenames, (path, basenames[path.name])
        basenames[path.name] = path
        language = (
            path.parent.parent.name if path.parent.name == "b" else path.parent.name
        )
        assert language in path.name, (path, language)
