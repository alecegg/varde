"""Child process for the integration tests: run one quality pass and print JSON.

Run as a script so ``PYTHONHASHSEED`` and the worker count can differ per
process. The parsing pool uses the spawn start method and re-imports
``__main__``, so all work stays behind the ``__main__`` guard.
"""

from __future__ import annotations

import json
import os
import signal
import sys
from pathlib import Path

from varde_code.extract.provider import CodeExtractionProvider
from varde_code.index.build import build
from varde_code.quality_pass.pass_ import read_facts, read_measures, run_quality_pass
from varde_code.quality_pass.store.store import Store


def _install_kill_hook() -> None:
    phase = os.environ.get("VARDE_TEST_KILL_PHASE")
    if phase not in {"facts", "measures"}:
        return
    target = int(os.environ["VARDE_TEST_KILL_AFTER"])
    original = Store.put_batch
    committed = 0

    def put_and_maybe_kill(self, path, values):
        nonlocal committed
        original(self, path, values)
        if phase not in values:
            return
        committed += 1
        if committed == target:
            os.kill(os.getpid(), signal.SIGKILL)

    Store.put_batch = put_and_maybe_kill


def main() -> None:
    _install_kill_hook()
    root = Path(sys.argv[1])
    mode = sys.argv[2]
    workers = int(sys.argv[3])
    if mode == "cold":
        build(root, CodeExtractionProvider())
    summary = run_quality_pass(root, workers=workers, no_cache=mode == "no_cache")
    payload = {
        "mode": mode,
        "workers": workers,
        "facts_recomputed": list(summary.facts_recomputed),
        "edges_recomputed": list(summary.edges_recomputed),
        "measures_recomputed": list(summary.measures_recomputed),
        "facts_reused": summary.facts_reused,
        "edges_reused": summary.edges_reused,
        "measures_reused": summary.measures_reused,
        "facts": list(read_facts(root)),
        "measures": list(read_measures(root)),
    }
    # Keep the record key order read from the store so the parent can detect a
    # nondeterministic stored order; only values and list order are canonical.
    print(json.dumps(payload, sort_keys=False))


if __name__ == "__main__":
    main()
