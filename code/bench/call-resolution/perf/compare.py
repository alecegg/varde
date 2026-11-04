"""Compare two measure.py results: exit 1 when time ratio >1.05 or memory ratio >1.5."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import stats


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: compare.py <baseline.json> <final.json>", file=sys.stderr)
        return 2
    baseline, final = (json.loads(Path(p).read_text(encoding="utf-8")) for p in argv)
    rows = stats.ratios(baseline, final)
    for row in rows:
        print(
            f"{row['fixture']}/{row['scenario']}: "
            f"time x{row['time_ratio']:.3f} memory x{row['memory_ratio']:.3f}"
        )
    problems = stats.violations(rows)
    for line in problems:
        print(f"FAIL {line}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
