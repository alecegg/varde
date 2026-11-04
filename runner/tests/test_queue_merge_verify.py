from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "queue_merge_verify.py"
SPEC = importlib.util.spec_from_file_location("queue_merge_verify", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_queue_row_snapshot_comparison_accepts_identical_rows() -> None:
    snapshot = {"queue_items": [("q", "item", "claimed", 2)]}

    MODULE.assert_queue_rows_equal(
        snapshot, {"queue_items": [("q", "item", "claimed", 2)]}
    )


def test_queue_row_snapshot_comparison_names_changed_table() -> None:
    with pytest.raises(AssertionError, match="queue_items"):
        MODULE.assert_queue_rows_equal(
            {"queue_items": [("q", "item", "claimed", 2)]},
            {"queue_items": [("q", "item", "queued", 1)]},
        )
