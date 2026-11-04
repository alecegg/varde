"""Exit 0 only when every in-scope language meets the dev precision and recall targets.

Usage: ``python audit/check_targets.py <metrics.json>``. The metrics file is the
runner's ``--metrics-json`` payload: one entry per language with ``precision`` and
``natural_frequency_recall``.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from pathlib import Path

IN_SCOPE_LANGUAGES = ("python", "typescript", "csharp")
MIN_PRECISION = 0.95
MIN_RECALL = 0.80


def check_targets(metrics: Mapping[str, Mapping[str, object]]) -> list[str]:
    """Return one failure line per missed target; empty when all pass."""
    failures = []
    for language in IN_SCOPE_LANGUAGES:
        entry = metrics.get(language)
        if entry is None:
            failures.append(f"{language}: missing from metrics")
            continue
        failures.extend(_language_failures(language, entry))
    return failures


def _language_failures(language: str, entry: Mapping[str, object]) -> list[str]:
    failures = []
    precision = entry.get("precision")
    recall = entry.get("natural_frequency_recall")
    if not isinstance(precision, int | float) or precision < MIN_PRECISION:
        failures.append(f"{language}: precision {precision} < {MIN_PRECISION}")
    if not isinstance(recall, int | float) or recall < MIN_RECALL:
        failures.append(f"{language}: recall {recall} < {MIN_RECALL}")
    return failures


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: check_targets.py <metrics.json>", file=sys.stderr)
        return 2
    metrics = json.loads(Path(argv[1]).read_text(encoding="utf-8"))
    failures = check_targets(metrics)
    for line in failures:
        print(line)
    if not failures:
        print("all in-scope languages meet P>=0.95 and R>=0.80")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
