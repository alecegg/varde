"""Child process for the determinism test: run cold and warm, print JSON.

Kept out of pytest collection by name; the pool's spawn start method re-imports
``__main__``, so this module keeps its work behind a ``__main__`` guard. With a
third argument ``edit``, it edits one file and refreshes the index between the
cold and warm passes.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from varde_code.extract.provider import CodeExtractionProvider
from varde_code.index.build import build
from varde_code.index.incremental import refresh
from varde_code.quality_pass.pass_ import read_facts, read_measures, run_quality_pass


def main() -> None:
    root = Path(sys.argv[1])
    workers = int(sys.argv[2])
    edit = len(sys.argv) > 3 and sys.argv[3] == "edit"
    build(root, CodeExtractionProvider())
    cold = run_quality_pass(root, workers=workers)
    if edit:
        target = root / "pkg/standalone.py"
        target.write_text(
            target.read_text(encoding="utf-8") + "\n\ndef extra():\n    return 9\n",
            encoding="utf-8",
        )
        refresh(root, CodeExtractionProvider())
    warm = run_quality_pass(root, workers=workers)
    payload = {
        "cold_recomputed": list(cold.facts_recomputed),
        "warm_recomputed": list(warm.facts_recomputed),
        "warm_reused": warm.facts_reused,
        "warm_measures_recomputed": list(warm.measures_recomputed),
        "facts": list(read_facts(root)),
        "measures": list(read_measures(root)),
    }
    print(json.dumps(payload, sort_keys=True))


if __name__ == "__main__":
    main()
