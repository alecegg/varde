"""Component `recap`: a plan-to-change recap; props are the recap's JSON keys."""

from varde_learn.docs.pages.blocks.rules import Fault
from varde_learn.docs.pages.blocks.spec import BlockSpec

_ROW_KEYS = ("file", "status", "hunk")


def validate_recap(data: dict[str, object]) -> list[Fault]:
    rows = data.get("rows")
    if not isinstance(rows, list):
        return [Fault("type", "recap needs a `rows` list")]
    for row in rows:
        if not isinstance(row, dict) or any(k not in row for k in _ROW_KEYS):
            return [Fault("type", "each recap row needs file, status and hunk")]
    return []


RECAP = BlockSpec(
    "recap",
    "A plan's changed files, drift flags and review buttons",
    (
        "rows      list of changed files: file, status, hunk (and optional",
        "          tasks, blocks, drift, added, removed, shared, binary, truncated)",
        "plan, base, head  optional text for the heading",
        "summary   optional {name: count}",
        "untouched, unverified  optional drift lists",
    ),
    r"""recap = recap(
  plan: "demo",
  base: "main",
  head: "work",
  summary: {"modified": 1},
  rows: [
    {"file": "a.py", "status": "modified", "hunk": "@@ -1 +1 @@", "tasks": ["t1"]},
  ],
)
""",
    validate_recap,
)
