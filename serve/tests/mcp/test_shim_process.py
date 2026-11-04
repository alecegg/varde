"""The shim as a subprocess: lists tools without starting a daemon."""

import json
import subprocess
import sys
from pathlib import Path

from varde_serve.daemon.state import read_info
from varde_serve.daemon.tokens import state_dir


def test_initialize_and_tools_list_do_not_start_a_daemon(tmp_path: Path) -> None:
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    done = subprocess.run(
        [sys.executable, "-m", "varde_serve", "mcp"],
        input="\n".join(json.dumps(m) for m in lines) + "\n",
        capture_output=True,
        text=True,
        timeout=30,
        env={"VARDE_CONFIG_DIR": str(tmp_path), "PATH": "/usr/bin:/bin"},
        check=True,
    )
    replies = [json.loads(line) for line in done.stdout.splitlines()]
    assert [r["id"] for r in replies] == [1, 2]
    names = {t["name"] for t in replies[1]["result"]["tools"]}
    assert names == {"varde_read", "varde_search", "varde_write", "varde_events"}
    assert read_info(state_dir(tmp_path)) is None
