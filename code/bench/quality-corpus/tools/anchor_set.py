"""Build the Q5 anchor set: excellent and poor anchors from dev-split corpus items.

Reads only `items/<language>/` task folders whose split in `splits.lock` is
`dev`; test-restricted and regression tasks are skipped before any file is
opened. Writes deterministic `anchors.jsonl` (sorted, no timestamps), one row
per anchor with provenance. Excellent/poor anchors come in couples of the same
task: the category (e) `misc/anchor-*` couples, and the `b/<task>`
sensible/monolith couples. Seeded samples carry no split assignment, so they
are not used. No model calls.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from splits import LOCK  # noqa: E402, RUF100

ITEMS = TOOLS.parent / "items"
ANCHOR_SPLIT = "dev"
DEFAULT_LANGUAGES = "python,typescript,csharp"
# (item folder group, excellent file stem, poor file stem, source label)
COUPLE_KINDS = (
    ("misc", "excellent", "poor", "corpus-e", "anchor-"),
    ("b", "sensible", "monolith", "corpus-b", ""),
)


def load_assignments(lock: Path = LOCK) -> dict[str, str]:
    return json.loads(lock.read_text(encoding="utf-8"))["assignments"]


def _find(folder: Path, stem: str) -> Path | None:
    matches = sorted(
        path for path in folder.glob(f"{stem}.*") if path.suffix != ".toml"
    )
    return matches[0] if matches else None


def anchor_row(
    path: Path, root: Path, language: str, task: str, role: str, source: str
) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    return {
        "id": f"{language}:{task}:{role}",
        "language": language,
        "task": task,
        "couple": f"{language}:{task}",
        "role": role,
        "split": ANCHOR_SPLIT,
        "source": source,
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "text": text,
    }


def couple_rows(
    folder: Path,
    root: Path,
    language: str,
    kind: tuple[str, str, str, str, str],
) -> list[dict[str, Any]]:
    _, excellent_stem, poor_stem, source, _ = kind
    excellent = _find(folder, excellent_stem)
    poor = _find(folder, poor_stem)
    if excellent is None or poor is None:
        return []
    task = folder.name
    return [
        anchor_row(excellent, root, language, task, "excellent", source),
        anchor_row(poor, root, language, task, "poor", source),
    ]


def build_anchors(
    items_root: Path,
    languages: list[str],
    assignments: Mapping[str, str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for language in languages:
        for kind in COUPLE_KINDS:
            group, prefix = kind[0], kind[4]
            group_dir = items_root / language / group
            for folder in sorted(p for p in group_dir.glob(f"{prefix}*") if p.is_dir()):
                if assignments.get(folder.name) != ANCHOR_SPLIT:
                    continue
                rows.extend(couple_rows(folder, items_root, language, kind))
    return sorted(rows, key=lambda row: row["id"])


def jsonl(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", type=Path, default=ITEMS)
    parser.add_argument("--splits", type=Path, default=LOCK)
    parser.add_argument("--languages", default=DEFAULT_LANGUAGES)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    languages = [name.strip() for name in args.languages.split(",") if name.strip()]
    rows = build_anchors(args.items, languages, load_assignments(args.splits))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(jsonl(rows), encoding="utf-8")
    print(f"wrote {len(rows)} anchors to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
