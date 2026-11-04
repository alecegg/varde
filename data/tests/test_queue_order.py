from pathlib import Path

import pytest
from varde_data.queue_order import OrderMismatch, full_order, move_order, set_order


def test_full_order_accepts_permutation_only() -> None:
    assert full_order(["a", "b"], ["b", "a"]) == ["b", "a"]
    for bad in (["a"], ["a", "a"], ["a", "b", "c"], ["a", "c"]):
        with pytest.raises(OrderMismatch):
            full_order(["a", "b"], bad)


def test_set_order_persists_and_mismatch_leaves_file(tmp_path: Path) -> None:
    path = tmp_path / "order.json"
    categories = {"queue": ["a", "b", "c"]}
    assert set_order(path, categories, "queue", ["c", "a", "b"]) == {
        "queue": ["c", "a", "b"]
    }
    with pytest.raises(OrderMismatch):
        set_order(path, categories, "queue", ["a", "b"])
    assert move_order(path, categories, "queue", "b", "up")["queue"] == ["c", "b", "a"]
