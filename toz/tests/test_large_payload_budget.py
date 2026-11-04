import io
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from varde_toz import hook

PACKAGE = Path(__file__).parents[1]


def test_hook_handles_small_and_large_command_payload_shapes(
    tmp_path: Path, monkeypatch, capsysbinary
) -> None:
    config = tmp_path / "config"
    store = tmp_path / "store"
    config.mkdir()
    store.mkdir()
    (config / "config.toml").write_text(
        '[hooks.post_tool_use]\nproviders=["capture"]\n'
        '[hooks.session_start]\nproviders=["toz_note"]\n'
    )
    command = "x" * (256 * 1024)
    output = "x" * (256 * 1024)
    for source in ("printf short-command", command):
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": source},
            "tool_response": {"stdout": output, "stderr": ""},
        }
        monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))
        monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(store))
        monkeypatch.setattr(
            hook.sys,
            "stdin",
            SimpleNamespace(
                buffer=io.BytesIO(json.dumps(payload, separators=(",", ":")).encode())
            ),
        )
        assert hook.main(["post-tool-use", "--harness", "claude"]) == 0
        capsysbinary.readouterr()


@pytest.mark.slow
def test_cli_handles_large_command_payload(tmp_path: Path) -> None:
    config = tmp_path / "config"
    store = tmp_path / "store"
    config.mkdir()
    store.mkdir()
    (config / "config.toml").write_text(
        '[hooks.post_tool_use]\nproviders=["capture"]\n'
        '[hooks.session_start]\nproviders=["toz_note"]\n'
    )
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "x" * (256 * 1024)},
        "tool_response": {"stdout": "x" * (256 * 1024), "stderr": ""},
    }
    env = os.environ.copy()
    env.update({"VARDE_CONFIG_DIR": str(config), "VARDE_TOZ_CONFIG_DIR": str(store)})
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "varde_toz.cli",
            "hook",
            "post-tool-use",
            "--harness",
            "claude",
        ],
        cwd=PACKAGE,
        env=env,
        input=json.dumps(payload, separators=(",", ":")),
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
