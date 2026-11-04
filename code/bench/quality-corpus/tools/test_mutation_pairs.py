# ruff: noqa: S101
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import mutation_pairs  # noqa: E402, RUF100

PYTHON_SOURCE = (
    "def add(a, b):\n    return a + b\n\n\n"
    "def pick(items, key):\n    for item in items:\n        if item == key:\n"
    "            return item\n    return None\n"
)


def _facts() -> dict:
    return {
        "contract": "facts-1",
        "path": "src/a.py",
        "language": "python",
        "module": "src",
        "tokens": 1200,
        "structure_confidence": "normal",
        "functions": [
            {
                "id": "src/a.py::work",
                "line": 4,
                "tokens": 120,
                "cognitive": 10,
                "params": 1,
                "depth": 1,
                "fan_out": 1,
                "tree_size": 1,
                "name_issues": [],
                "exempt_role": None,
                "fragment_scope": None,
            }
        ],
    }


def _item(item_id: str = "p1:b", split: str = "dev", language: str = "python") -> dict:
    return {
        "id": item_id,
        "language": language,
        "split": split,
        "text": PYTHON_SOURCE,
    }


def test_one_pair_per_operator_with_worse_mutated_side():
    pairs = mutation_pairs.pairs_for_item(_item(), _facts())
    assert [pair["mutation"] for pair in pairs] == [
        name for name, _ in mutation_pairs.OPERATORS
    ]
    assert len(pairs) == 7
    for pair in pairs:
        assert pair["worse"] == "mutated"
        assert pair["original"] == _facts()
        assert pair["mutated"] != pair["original"]
        assert pair["id"] == f"p1:b#{pair['mutation']}"


def test_source_facts_are_not_modified():
    facts = _facts()
    original = copy.deepcopy(facts)
    mutation_pairs.pairs_for_item(_item(), facts)
    assert facts == original


def test_item_without_functions_gives_no_pairs():
    facts = _facts()
    facts["functions"] = []
    assert mutation_pairs.pairs_for_item(_item(), facts) == []


@pytest.mark.parametrize("split", ["test-restricted", "regression"])
def test_non_dev_item_raises(split: str):
    with pytest.raises(ValueError, match="not dev"):
        mutation_pairs.pairs_for_item(_item(split=split), _facts())


def test_non_dev_split_request_raises():
    with pytest.raises(ValueError, match="dev split only"):
        mutation_pairs.require_allowed_splits(frozenset({"dev", "test-restricted"}))
    mutation_pairs.require_allowed_splits(frozenset({"dev"}))


def test_build_pairs_is_deterministic_sorted_and_per_language():
    items = [
        _item("b2:b"),
        _item("a1:a"),
        _item("c3:a", language="csharp"),
    ]
    languages = frozenset({"python"})
    first, skipped = mutation_pairs.build_pairs(items, languages)
    second, _ = mutation_pairs.build_pairs(list(reversed(items)), languages)
    assert skipped == []
    assert mutation_pairs.jsonl(first) == mutation_pairs.jsonl(second)
    ids = [pair["id"] for pair in first]
    assert ids == sorted(ids)
    assert {pair["language"] for pair in first} == {"python"}
    assert {pair["item_id"] for pair in first} == {"a1:a", "b2:b"}


def test_main_writes_pairs_for_a_dev_dataset(tmp_path: Path):
    dataset = tmp_path / "dataset"
    dataset.mkdir()
    rows = [{"record_type": "items", "schema_version": 1}, _item("p1:a")]
    rows.append(_item("p9:a", split="test-restricted"))
    (dataset / "items.jsonl").write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8"
    )
    out = tmp_path / "mutation-pairs.jsonl"
    argv = ["mutation_pairs.py", "--dataset", str(dataset), "--out", str(out)]
    old = sys.argv
    sys.argv = argv
    try:
        assert mutation_pairs.main() == 0
    finally:
        sys.argv = old
    written = [json.loads(line) for line in out.read_text().splitlines()]
    assert {row["item_id"] for row in written} == {"p1:a"}
    assert {row["mutation"] for row in written} == {
        name for name, _ in mutation_pairs.OPERATORS
    }
