# ruff: noqa: S101
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import anchor_set  # noqa: E402, RUF100

ASSIGNMENTS = {
    "anchor-ledger": "dev",
    "anchor-queue": "test-restricted",
    "clinic-booking": "dev",
    "csv-summary": "regression",
    "price-order": "test-restricted",
}


def _write(folder: Path, name: str, text: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_text(text, encoding="utf-8")


@pytest.fixture
def items(tmp_path: Path) -> Path:
    root = tmp_path / "items"
    for language, suffix in (("python", ".py"), ("typescript", ".ts")):
        for task in ("anchor-ledger", "anchor-queue"):
            folder = root / language / "misc" / task
            _write(folder, f"excellent{suffix}", f"# {task} excellent\n")
            _write(folder, f"poor{suffix}", f"# {task} poor\n")
            _write(folder, "manifest.toml", 'category = "e"\n')
        for task in ("clinic-booking", "csv-summary", "price-order"):
            folder = root / language / "b" / task
            _write(folder, f"sensible{suffix}", f"# {task} sensible\n")
            _write(folder, f"monolith{suffix}", f"# {task} monolith\n")
            _write(folder, f"tiny{suffix}", f"# {task} tiny\n")
    return root


def test_anchors_are_dev_couples_only(items: Path):
    rows = anchor_set.build_anchors(items, ["python", "typescript"], ASSIGNMENTS)
    assert {row["split"] for row in rows} == {"dev"}
    assert {row["task"] for row in rows} == {"anchor-ledger", "clinic-booking"}
    assert not any("queue" in row["path"] or "price" in row["path"] for row in rows)
    assert not any("csv-summary" in row["path"] for row in rows)


def test_each_couple_has_one_excellent_and_one_poor(items: Path):
    rows = anchor_set.build_anchors(items, ["python"], ASSIGNMENTS)
    couples: dict[str, list[str]] = {}
    for row in rows:
        couples.setdefault(row["couple"], []).append(row["role"])
    assert couples
    assert all(sorted(roles) == ["excellent", "poor"] for roles in couples.values())
    by_id = {row["id"]: row for row in rows}
    assert by_id["python:clinic-booking:excellent"]["path"].endswith("sensible.py")
    assert by_id["python:clinic-booking:poor"]["path"].endswith("monolith.py")
    assert by_id["python:anchor-ledger:excellent"]["source"] == "corpus-e"


def test_provenance_fields_and_text_hash(items: Path):
    row = anchor_set.build_anchors(items, ["python"], ASSIGNMENTS)[0]
    for field in (
        "id",
        "language",
        "task",
        "couple",
        "role",
        "source",
        "path",
        "sha256",
    ):
        assert row[field]
    assert row["text"].startswith("# ")


def test_unlisted_task_is_skipped_not_read(items: Path):
    rows = anchor_set.build_anchors(items, ["python"], {"anchor-ledger": "dev"})
    assert {row["task"] for row in rows} == {"anchor-ledger"}


def test_output_is_deterministic_and_sorted(items: Path, tmp_path: Path):
    languages = ["typescript", "python"]
    first = anchor_set.jsonl(anchor_set.build_anchors(items, languages, ASSIGNMENTS))
    second = anchor_set.jsonl(anchor_set.build_anchors(items, languages, ASSIGNMENTS))
    assert first == second
    ids = [json.loads(line)["id"] for line in first.splitlines()]
    assert ids == sorted(ids)


def test_real_corpus_has_no_test_restricted_anchor():
    assignments = anchor_set.load_assignments()
    rows = anchor_set.build_anchors(
        anchor_set.ITEMS, anchor_set.DEFAULT_LANGUAGES.split(","), assignments
    )
    assert rows
    assert all(assignments[row["task"]] == "dev" for row in rows)
    languages = {row["language"] for row in rows}
    assert languages == {"python", "typescript", "csharp"}
