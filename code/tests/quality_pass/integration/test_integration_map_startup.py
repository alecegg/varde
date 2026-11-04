"""Hook latency: starting the map command must not import the quality packages.

Hooks and other latency-sensitive flows call the code map command. Running it
in a fresh interpreter must leave ``varde_code.quality_*`` out of ``sys.modules``
so the scan-time quality pass never loads on that path.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from integration_support import build_index, prepare_env, write_repo

REPO_ROOT = Path(__file__).resolve().parents[4]

CHILD = """
import contextlib, io, json, sys
from varde import cli

root = sys.argv[1]
captured = io.StringIO()
with contextlib.redirect_stdout(captured):
    code = cli.main(["map", "nav_map", "--json", json.dumps({"repoRoot": root})])
payload = json.loads(captured.getvalue())
quality = sorted(name for name in sys.modules if name.startswith("varde_code.quality"))
print(json.dumps({"code": code, "ok": payload.get("ok"), "quality": quality}))
"""


def test_map_startup_does_not_import_quality_packages(tmp_path, monkeypatch):
    root = prepare_env(monkeypatch, tmp_path)
    write_repo(root, {"alpha.py": "def alpha():\n    return 1\n"})
    build_index(root)

    result = subprocess.run(  # noqa: S603 - Starts the test CLI with controlled map-startup arguments.
        [sys.executable, "-c", CHILD, str(root)],
        cwd=REPO_ROOT,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])

    assert payload["code"] == 0
    assert payload["ok"] is True
    assert payload["quality"] == []
