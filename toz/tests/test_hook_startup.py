import io
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

PACKAGE = Path(__file__).parents[1]


def _hook_config(tmp_path, monkeypatch, text) -> None:
    config = tmp_path / "config"
    store = tmp_path / "toz"
    for directory in (config, store):
        directory.mkdir(exist_ok=True)
        (directory / "config.toml").write_text(text)
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(store))


def test_installed_launchers_reach_hook_main(tmp_path: Path) -> None:
    tool_dir = tmp_path / "tools"
    tool_bin = tmp_path / "bin"
    install_env = os.environ.copy()
    install_env["UV_TOOL_DIR"] = str(tool_dir)
    install_env["UV_TOOL_BIN_DIR"] = str(tool_bin)
    subprocess.run(  # noqa: S603 - Setup test installs this local package into an isolated temporary tool directory.
        ["uv", "tool", "install", "--editable", "--force", str(PACKAGE)],  # noqa: S607 - uv is the test's required installer from PATH.
        env=install_env,
        check=True,
    )
    executable = tool_dir / "varde-toz" / "bin" / "varde-toz"
    python = tool_dir / "varde-toz" / "bin" / "python"
    env = os.environ.copy()
    env["VARDE_CONFIG_DIR"] = str(tmp_path / "config")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.toml").write_text(
        "[hooks.post_tool_use]\nproviders=[]\n"
    )
    args = ["post-tool-use", "--harness", "claude", "--help"]
    commands = (
        [str(executable), "hook", *args],
        [str(python), "-m", "varde_toz.hook_main", *args],
        [str(python), "-I", "-m", "varde_toz.hook_main", *args],
    )
    for command in commands:
        result = subprocess.run(  # noqa: S603 - Test launches locally installed entry points with fixed argv.
            command, env=env, capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, (command, result.stderr)
        assert "Usage: varde hook" in result.stdout


@pytest.mark.parametrize("error", [ValueError, AttributeError])
def test_hook_deadline_falls_back_when_signal_setup_is_unavailable(
    tmp_path, monkeypatch, capsys, error
) -> None:
    from varde_toz import hook

    instruction = tmp_path / "instructions.md"
    instruction.write_text("no managed block\n")
    _hook_config(
        tmp_path,
        monkeypatch,
        '[hooks.session_start]\nproviders=["toz_note"]\n'
        f'[instructions]\ntargets=["{instruction}"]\n',
    )
    monkeypatch.setattr(
        hook.signal, "signal", lambda *_: (_ for _ in ()).throw(error())
    )

    assert hook.main(["session-start", "--harness", "codex"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["hookSpecificOutput"]["additionalContext"]


def test_capture_timeout_does_not_write_partial_stdout(
    tmp_path, monkeypatch, capsysbinary
) -> None:
    from varde_toz import hook

    _hook_config(
        tmp_path,
        monkeypatch,
        'threshold=1\n[hooks.post_tool_use]\nproviders=["capture"]\n',
    )
    monkeypatch.setattr(hook, "HOOK_TIMEOUT_SECONDS", 60.0)
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "make"},
        "tool_response": {"stdout": "x" * (2 * 1024 * 1024), "stderr": ""},
    }
    monkeypatch.setattr(
        sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(payload).encode()))
    )
    assert hook.main(["post-tool-use", "--harness", "claude"]) == 0
    assert capsysbinary.readouterr().out

    monkeypatch.setattr(hook, "HOOK_TIMEOUT_SECONDS", 0.001)
    monkeypatch.setattr(
        sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(payload).encode()))
    )
    assert hook.main(["post-tool-use", "--harness", "claude"]) == 0
    assert capsysbinary.readouterr().out == b""


def test_deadline_is_cancelled_before_stdout_write(tmp_path, monkeypatch) -> None:
    from varde_toz import hook

    _hook_config(
        tmp_path,
        monkeypatch,
        'threshold=4096\n[hooks.post_tool_use]\nproviders=["capture"]\n',
    )
    token = "ghp_" + "a" * 36
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "cat f"},
        "tool_response": {"stdout": f"credential {token}\n", "stderr": ""},
    }
    monkeypatch.setattr(
        sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(payload).encode()))
    )
    seen = []

    class CheckedOutput(io.BytesIO):
        def write(self, value):
            seen.append(signal.getitimer(signal.ITIMER_REAL))
            return super().write(value)

    output = CheckedOutput()
    monkeypatch.setattr(sys, "stdout", SimpleNamespace(buffer=output))

    assert hook.main(["post-tool-use", "--harness", "claude"]) == 0
    assert output.getvalue()
    assert seen == [(0.0, 0.0)]
