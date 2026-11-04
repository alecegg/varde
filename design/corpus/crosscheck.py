"""Read-only agreement of `varde design check` with an external fixture set.

Usage: python design/corpus/crosscheck.py FIXTURE_DIR

File names carry the author's intended rule (`low-contrast-*`, `gradient-text-*`,
`skipped-heading-*`, `script-error-*`, `*overflow*`). Prints, per fixture, which
mapped rule our checker raised. Nothing is copied; these are the authors' intent,
not truth.
"""

from __future__ import annotations

import sys
from pathlib import Path

import mutate

INTENT = (
    ("low-contrast-", "R1"),
    ("gradient-text-", "S2"),
    ("skipped-heading-", "S5"),
    ("script-error", "R6"),
    ("overflow", "R2"),
)


def intended(name: str) -> str | None:
    return next((rule for prefix, rule in INTENT if prefix in name), None)


def main(argv: list[str]) -> int:
    rows = []
    for path in sorted(Path(argv[0]).glob("*.html")):
        rule = intended(path.name)
        if rule is None:
            continue
        report = mutate.check_html(path, False)
        rows.append(
            (
                path.name,
                rule,
                rule in mutate.rules_hit(report),
                report.get("checked", {}).get("rendered"),
            )
        )
    for name, rule, agrees, rendered in rows:
        print(f"{rule}\t{'fires' if agrees else 'silent'}\t{name}\trendered={rendered}")
    for rule in sorted({r for _, r, _, _ in rows}):
        mine = [a for _, r, a, _ in rows if r == rule]
        print(f"{rule}: fires on {sum(mine)}/{len(mine)} fixtures named for it")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
