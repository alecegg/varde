"""AC1: an MCP client's plan list equals the CLI plan list, one daemon started."""

import contextlib
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest
from varde_learn.knowledge.memory import MemoryPaths
from varde_serve.daemon.state import read_info
from varde_serve.daemon.tokens import state_dir

DROP = {"now_at", "status_at", "merge_approved_at", "stalled"}


def scrub(value):
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items() if k not in DROP}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    return value


def test_varde_read_plans_equals_cli_plan_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, repo = tmp_path / "cfg", tmp_path / "repo"
    config.mkdir()
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)  # noqa: S603, S607
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(repo)
    working = MemoryPaths.resolve(repo).working.path
    assert working.is_relative_to(tmp_path)
    plan = working / "plans" / "demo"
    plan.mkdir(parents=True)
    (plan / "plan.md").write_text(
        "---\ntype: plan\ntitle: Demo\nstatus: backlog\n---\n\n## Problem\n\nX.\n"
    )
    try:
        cli = subprocess.run(  # noqa: S603
            [str(Path(sys.executable).parent / "varde"), "plan", "status", "--json"],
            capture_output=True,
            text=True,
            check=True,
            cwd=repo,
        )
        expected = json.loads(cli.stdout)["data"]
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "varde_read", "arguments": {"resource": "plans"}},
        }
        shim = subprocess.run(
            [sys.executable, "-m", "varde_serve", "mcp"],
            input=json.dumps(request) + "\n",
            capture_output=True,
            text=True,
            check=True,
            cwd=repo,
            timeout=60,
        )
        reply = json.loads(shim.stdout)
        assert reply["result"]["isError"] is False, reply
        got = json.loads(reply["result"]["content"][0]["text"])
        assert scrub(got) == scrub(expected)
        assert read_info(state_dir(config)) is not None
    finally:
        info = read_info(state_dir(config))
        if info is not None:
            with contextlib.suppress(ProcessLookupError):
                os.kill(info.pid, signal.SIGTERM)
