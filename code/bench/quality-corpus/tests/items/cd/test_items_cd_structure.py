"""Report c/d item counts across repository and restricted split locations."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from place_item import restricted_root

ROOT = Path(__file__).resolve().parents[3]
LANGUAGES = ("python", "typescript", "java", "csharp", "go", "rust", "cpp")
CATEGORIES = {"c": 6, "d": 4}
REPO_ITEMS = ROOT / "items" / "_cd"


def records(root: Path, language: str, category: str) -> list[tuple[Path, dict]]:
    found = []
    if not root.is_dir():
        return found
    for pair_file in sorted(root.rglob("pair.json")):
        pair = json.loads(pair_file.read_text(encoding="utf-8"))
        if pair.get("language") == language and pair.get("category") == category:
            found.append((pair_file.parent, pair))
    return found


def test_repo_items_are_dev_or_regression_only() -> None:
    for language in LANGUAGES:
        for category in CATEGORIES:
            for item_dir, pair in records(
                REPO_ITEMS / language / category, language, category
            ):
                marker = json.loads((item_dir / ".varde-split.json").read_text())
                assert marker["split"] in {"dev", "regression"}, (
                    language,
                    category,
                    marker,
                )
                assert marker["task_id"] == pair["id"]


def test_counts_are_six_and_four_when_restricted_store_is_available() -> None:
    store = restricted_root()
    if not store.is_dir():
        pytest.skip(f"restricted golden store is absent: {store}")
    summary = []
    for language in LANGUAGES:
        counts = {}
        for category, expected in CATEGORIES.items():
            in_repo = records(REPO_ITEMS / language / category, language, category)
            in_store = records(store, language, category)
            all_items = in_repo + in_store
            counts[category] = len(all_items)
            assert len(all_items) == expected, (
                language,
                category,
                len(all_items),
                expected,
            )
            ids = [pair["id"] for _, pair in all_items]
            assert len(ids) == len(set(ids)), (language, category, "duplicate pair ids")
            for item_dir, pair in in_store:
                marker = json.loads((item_dir / ".varde-split.json").read_text())
                assert marker["split"] in {"test", "test-restricted", "test-2"}
                assert marker["task_id"] == pair["id"]
        summary.append((language, counts["c"], counts["d"]))
    assert summary == [(language, 6, 4) for language in LANGUAGES]


def test_item_ids_are_opaque_and_sides_are_present() -> None:
    roots = [REPO_ITEMS]
    store = restricted_root()
    if store.is_dir():
        roots.append(store)
    for root in roots:
        for pair_file in root.rglob("pair.json"):
            pair = json.loads(pair_file.read_text(encoding="utf-8"))
            if pair.get("category") not in CATEGORIES:
                continue
            assert len(pair["id"]) == 24
            assert all(ch in "0123456789abcdef" for ch in pair["id"])
            assert (pair_file.parent / pair["left"]).is_file()
            assert (pair_file.parent / pair["right"]).is_file()
