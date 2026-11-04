"""The `varde serve` command tree is exactly four approved paths."""

from __future__ import annotations

import re
import subprocess
import sys

from varde.cli import _discover_modules
from varde.routes import ROUTES

APPROVED = {("serve",), ("serve", "stop"), ("serve", "status"), ("serve", "mcp")}


def test_serve_route_and_module_are_registered() -> None:
    assert [r.path for r in ROUTES if r.path[0] == "serve"] == [("serve",)]
    assert "serve" in _discover_modules()


def _help_words() -> set[str]:
    text = _discover_modules()["serve"].help("serve")
    block = text.split("\nCommands:\n", 1)[1].split("\n\n", 1)[0]
    return {
        m.group(1)
        for line in block.splitlines()
        if (m := re.match(r"^  ([a-z]+)", line))
    }


def test_command_tree_lists_exactly_the_approved_paths() -> None:
    paths = {("serve",)} | {("serve", word) for word in _help_words() - {"help"}}
    assert paths == APPROVED
    assert "token" not in _help_words()


def test_unknown_subcommand_is_a_usage_error() -> None:
    from varde.setup.serve_cmd import run

    assert run(["token"], None) == 2
    assert run(["stop", "now"], None) == 2
    assert subprocess.run([sys.executable, "-c", "pass"], check=False).returncode == 0


def test_varde_serve_mcp_lists_four_tools(tmp_path) -> None:
    import json
    import os
    import shutil
    from pathlib import Path

    bin_dir = Path(sys.executable).parent
    if shutil.which("varde-serve", path=str(bin_dir)) is None:
        import pytest

        pytest.skip("varde-serve is not installed beside this interpreter")
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    done = subprocess.run(  # noqa: S603
        [str(bin_dir / "varde"), "serve", "mcp"],
        input="\n".join(json.dumps(m) for m in messages) + "\n",
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "VARDE_CONFIG_DIR": str(tmp_path),
        },
    )
    listed = json.loads(done.stdout.splitlines()[1])
    assert sorted(t["name"] for t in listed["result"]["tools"]) == [
        "varde_events",
        "varde_read",
        "varde_search",
        "varde_write",
    ]


def test_missing_varde_serve_prints_how_to_install(monkeypatch, capsys) -> None:
    from varde.setup import serve_cmd

    monkeypatch.setattr(serve_cmd, "_executable", lambda: None)
    assert serve_cmd.run([], None) == 1
    message = capsys.readouterr().err
    assert "varde-serve is not installed" in message
    assert "runner/deploy/deploy.py" in message
    assert "PEX" in message
