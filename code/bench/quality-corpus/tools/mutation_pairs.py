"""Build the Q4 mutation-pair set from dev-split dataset items (no model calls).

Each dev item's extracted facts are mutated by the harness operators
(`code/tests/quality_score/harness/mutations.py`); the original and the mutated
facts form one pair whose construction label is "the mutated side is worse".
Writes deterministic `mutation-pairs.jsonl` (sorted by pair id, no timestamps).
Only the `dev` split is accepted; other splits raise before any item is read.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parents[3]
HARNESS = ROOT / "code/tests/quality_score/harness"
for _path in (ROOT / "code/src", TOOLS, HARNESS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import mutations  # noqa: E402, RUF100
from score_dataset import (  # noqa: E402, RUF100
    default_dataset,
    item_path,
    read_items,
)
from varde_code.quality_pass.facts import extract_facts  # noqa: E402, RUF100

ALLOWED_SPLITS = frozenset({"dev"})
DEFAULT_LANGUAGES = "python,typescript,csharp"
Facts = dict[str, Any]

# (operator name, parameters); the order is the order of pairs per item.
OPERATORS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("rename_to_short_names", {}),
    ("nest", {"levels": 4}),
    ("grow", {"copies": 5}),
    ("add_branches", {"branches": 5}),
    ("fragment", {"count": 6, "piece_tokens": 12}),
    ("forwarder_chain", {"count": 5}),
    ("agent_tree", {"count": 20}),
)
_OPERATOR_FUNCTIONS: dict[str, Callable[..., Facts]] = {
    name: getattr(mutations, name) for name, _ in OPERATORS
}


def require_allowed_splits(splits: frozenset[str]) -> None:
    disallowed = sorted(splits - ALLOWED_SPLITS)
    if disallowed:
        raise ValueError(f"mutation pairs use the dev split only, not {disallowed}")


def pairs_for_item(item: dict[str, Any], facts: Facts) -> list[dict[str, Any]]:
    """One pair per operator; none when the item has no functions to mutate."""
    if item["split"] not in ALLOWED_SPLITS:
        raise ValueError(f"item {item['id']} is in split {item['split']}, not dev")
    if not facts.get("functions"):
        return []
    return [
        {
            "id": f"{item['id']}#{name}",
            "item_id": item["id"],
            "language": item["language"],
            "split": item["split"],
            "mutation": name,
            "params": params,
            "worse": "mutated",
            "original": facts,
            "mutated": _OPERATOR_FUNCTIONS[name](facts, **params),
        }
        for name, params in OPERATORS
    ]


def build_pairs(
    items: list[dict[str, Any]], languages: frozenset[str]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (pairs sorted by id, ids of items whose facts could not be read)."""
    pairs: list[dict[str, Any]] = []
    skipped: list[str] = []
    for item in items:
        if item["language"] not in languages:
            continue
        try:
            facts = extract_facts(item["text"], item["language"], item_path(item))
        except ValueError, RuntimeError, KeyError, TypeError:
            skipped.append(item["id"])
            continue
        pairs.extend(pairs_for_item(item, facts))
    return sorted(pairs, key=lambda pair: pair["id"]), skipped


def jsonl(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=default_dataset())
    parser.add_argument("--languages", default=DEFAULT_LANGUAGES)
    parser.add_argument("--splits", default="dev")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    splits = frozenset(name.strip() for name in args.splits.split(",") if name.strip())
    require_allowed_splits(splits)
    languages = frozenset(name.strip() for name in args.languages.split(","))
    pairs, skipped = build_pairs(read_items(args.dataset, splits), languages)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(jsonl(pairs), encoding="utf-8")
    print(f"wrote {len(pairs)} pairs to {args.out}; skipped {len(skipped)} items")
    for item_id in skipped:
        print(f"skipped: {item_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
