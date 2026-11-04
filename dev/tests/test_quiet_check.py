from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_lock_wait_timeout_and_custom_path():
    with tempfile.TemporaryDirectory() as temp:
        lock = Path(temp) / "lock"
        lock.mkdir()
        result = subprocess.run(  # noqa: S603 - Test runs the quiet-check script with controlled fixture arguments.
            [str(ROOT / "dev/scripts/with-lock.sh"), "true"],
            env={
                **os.environ,
                "VARDE_LOCK_DIR": str(lock),
                "VARDE_LOCK_TIMEOUT_S": "0",
            },
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        assert result.returncode == 75
        assert "timed out" in result.stderr


def test_quiet_check_reports_a_load_sample():
    result = subprocess.run(  # noqa: S603 - Test runs the quiet-check script with controlled fixture arguments.
        [sys.executable, str(ROOT / "dev/scripts/quiet_check.py")],
        input="small fixture input\n",
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert set(data) == {"load"}
    assert len(data["load"]) == 3
    assert all(isinstance(value, (float, int)) for value in data["load"])
