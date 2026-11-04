"""Structure checks for the TypeScript (b) authoring items."""

import hashlib
import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
ITEMS = ROOT / "items" / "typescript" / "b"
TOOLS = ROOT / "tools"
RESTRICTED = Path(
    "/Users/alec/source/agent-memory/projects/varde-py/working/plans/2026-10-17-quality-score-build/"
    "qs-golden-corpus/notes/restricted/golden"
)
VERSIONS = ("sensible", "monolith", "tiny", "padded", "sizematched", "namematched")
PILOT_TASKS = ("order-quote", "clinic-booking", "shift-pay", "rental-quote")
HEX_DIGITS = set("0123456789abcdef")
EXPECTED_SPLITS = {
    "invoice-aging": "dev",
    "price-order": "test-restricted",
    "retry-policy": "test-restricted",
    "shipment-state": "test-restricted",
    "text-template": "test-restricted",
    "scoreboard": "test-restricted",
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def restricted_root() -> Path:
    return RESTRICTED / "test-restricted"


def restricted_item(task: str) -> Path | None:
    base = restricted_root()
    if not base.is_dir():
        return None
    return next(iter(sorted(base.glob(f"*/{task}-typescript"))), None)


def item_files(item: Path) -> list[Path]:
    return sorted(
        path
        for path in item.iterdir()
        if path.is_file() and path.name != ".varde-split.json"
    )


def run_tool(name: str, item: Path) -> subprocess.CompletedProcess:
    command = [sys.executable, str(TOOLS / name), "--items", str(item), "--check"]
    return subprocess.run(command, check=False, capture_output=True, text=True)  # noqa: S603 - Runs the configured TypeScript tool on the test fixture.


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
    items = sorted(path for path in ITEMS.iterdir() if path.is_dir())
    assert items, f"no repository items under {ITEMS}"
    return items


def assert_pilot_pair_metadata(item: Path) -> None:
    payload = json.loads((item / "pair.json").read_text())
    assert set(payload) == {"pair_group_id", "task", "language", "part", "pairs"}
    assert len(payload["pair_group_id"]) >= 24
    assert set(payload["pair_group_id"]) <= HEX_DIGITS
    assert payload["task"] == item.name
    assert payload["language"] == "typescript"
    assert payload["part"] == "b"
    assert isinstance(payload["pairs"], list)
    expected_rights = {f"{version}.ts" for version in VERSIONS if version != "sensible"}
    expected_rights.update(
        pair["right"]
        for pair in payload["pairs"]
        if pair.get("right_role") == "alt-good"
    )
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
            assert pair["left"] == "sensible.ts"
            assert pair["right"] in {
                "alt-pipeline.ts",
                "alt-table.ts",
                "alt-class.ts",
            }
        else:
            assert "preference_neutral" not in pair
        for field in ("pair_id", "left_id", "right_id"):
            assert len(pair[field]) >= 24
            assert set(pair[field]) <= HEX_DIGITS
        assert pair["left"] == "sensible.ts"
        assert (item / pair["left"]).is_file()
        assert (item / pair["right"]).is_file()


def test_repo_items_are_known_dev_tasks() -> None:
    names = {item.name for item in dev_items()}
    assert names == {
        task for task, split in EXPECTED_SPLITS.items() if split == "dev"
    } | set(PILOT_TASKS), names


def test_dev_items_have_complete_versions() -> None:
    for item in dev_items():
        names = {path.name for path in item_files(item)}
        for version in VERSIONS:
            assert f"{version}.ts" in names, (item.name, version)
        assert "behaviour_test.ts" in names, item.name
        assert "pair.json" in names, item.name
        hashes = {digest(item / f"{version}.ts") for version in VERSIONS}
        assert len(hashes) == len(VERSIONS), item.name


def test_dev_pairs_describe_sensible_against_each_version() -> None:
    for item in dev_items():
        payload = json.loads((item / "pair.json").read_text())
        if item.name in PILOT_TASKS:
            assert_pilot_pair_metadata(item)
            continue
        assert payload["task"] == item.name, item.name
        assert payload["pair_group"] == item.name, item.name
        assert payload["language"] == "typescript", item.name
        assert payload["part"] == "b", item.name
        rights = {pair["right"] for pair in payload["pairs"]}
        assert rights == {f"{version}.ts" for version in VERSIONS[1:]}, item.name
        for pair in payload["pairs"]:
            assert pair["left"] == "sensible.ts", item.name
            assert len(pair["pair_id"]) == 24, (item.name, pair["pair_id"])
            int(pair["pair_id"], 16)


def test_dev_items_pass_spec_behaviour_and_hygiene() -> None:
    for item in dev_items():
        if item.name in PILOT_TASKS:
            with (item / "spec-profile.toml").open("rb") as profile_file:
                assert tomllib.load(profile_file)["profile"] == "layered"
        spec = run_tool("item_spec_check.py", item)
        assert not findings(spec), (item.name, findings(spec))
        assert spec.returncode == 0, (item.name, spec.stderr[-400:])
        behaviour = run_tool("behaviour_runner.py", item)
        assert behaviour.returncode == 0, (item.name, behaviour.stderr[-400:])
        hygiene = run_tool("hygiene.py", item)
        assert hygiene.returncode == 0, (item.name, hygiene.stdout[-400:])


def test_restricted_items_are_complete_and_outside_the_repository() -> None:
    if not restricted_root().is_dir():
        pytest.skip(f"restricted store unavailable: {restricted_root()}")
    for task, split in EXPECTED_SPLITS.items():
        if split != "test-restricted":
            continue
        item = restricted_item(task)
        assert item is not None, (
            f"missing restricted item for {task} in {restricted_root()}"
        )
        assert not item.resolve().is_relative_to(ROOT.resolve()), task
        marker = json.loads((item / ".varde-split.json").read_text())
        assert marker == {"task_id": task, "split": split}, task
        names = {path.name for path in item_files(item)}
        for version in VERSIONS:
            assert f"{version}.ts" in names, (task, version)
        assert "behaviour_test.ts" in names, task


def test_restricted_items_pass_spec_and_behaviour() -> None:
    if not restricted_root().is_dir():
        pytest.skip(f"restricted store unavailable: {restricted_root()}")
    for task, split in EXPECTED_SPLITS.items():
        if split != "test-restricted":
            continue
        item = restricted_item(task)
        assert item is not None, (
            f"missing restricted item for {task} in {restricted_root()}"
        )
        spec = run_tool("item_spec_check.py", item)
        assert not findings(spec), (task, findings(spec))
        assert spec.returncode == 0, (task, spec.stderr[-400:])
        behaviour = run_tool("behaviour_runner.py", item)
        assert behaviour.returncode == 0, (task, behaviour.stderr[-400:])
