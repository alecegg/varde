from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_perf_run_records_load_and_keeps_every_run():
    with tempfile.TemporaryDirectory() as temp:
        lock = Path(temp) / "lock"
        result = subprocess.run(  # noqa: S603 - Test runs the quiet-check script with controlled fixture arguments.
            [
                sys.executable,
                str(ROOT / "toz/scripts/toz-perf/perf_run.py"),
                "--lock-dir",
                str(lock),
                "--runs",
                "3",
                "--",
                sys.executable,
                "-c",
                "pass",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert data["status"] == "ok"
        assert len(data["attempts"]) == 1
        attempt = data["attempts"][0]
        assert len(attempt["samples"]) == 3
        assert len(attempt["load_before"]) == 3
        assert len(attempt["load_after"]) == 3
        assert attempt["lock_hold_s"] > 0
        assert not lock.exists()
