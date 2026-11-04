from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from varde.glue import hook


@pytest.mark.parametrize("harness", hook.HARNESSES)
def test_session_start_cli_emits_response_and_reserves_session(
    tmp_path: Path, harness: str
) -> None:
    home = tmp_path / "home"
    config = tmp_path / "config"
    working = tmp_path / "working"
    env = os.environ.copy()
    env.update(
        HOME=str(home), VARDE_CONFIG_DIR=str(config), VARDE_WORKING_DIR=str(working)
    )
    event = json.dumps({"session_id": "small-hook-test"})
    result = subprocess.run(  # noqa: S603 - Runs the hook CLI to test its command-line contract.
        [
            str(Path(sys.executable).with_name("varde")),
            "hook",
            "session-start",
            "--harness",
            harness,
        ],
        input=event,
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    state_files = list((config / "sessions").glob(f"{harness}-*.json"))
    assert len(state_files) == 1
    state = json.loads(state_files[0].read_text())
    assert state["harness"] == harness
    assert state["session_id"] == "small-hook-test"
    if harness in {"claude", "codex"}:
        response = json.loads(result.stdout)
        assert response["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        assert (
            "varde session: small-hook-test"
            in response["hookSpecificOutput"]["additionalContext"]
        )
    else:
        assert "varde session: small-hook-test" in result.stdout


def test_dispatch_rejects_unknown_harness(capsys):
    assert hook.dispatch({"event": "session-start"}, "vim") == 2
    assert "--harness" in capsys.readouterr().err


def _hook_environment(tmp_path: Path, monkeypatch) -> Path:
    config = tmp_path / "config"
    config.mkdir()
    working = tmp_path / "working"
    working.mkdir()
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("VARDE_RUNNER_ENABLED", "1")
    monkeypatch.chdir(tmp_path)
    return config


def _stub_capture(monkeypatch, payload: bytes) -> None:
    monkeypatch.setitem(
        sys.modules,
        "varde_toz.hook",
        type("Capture", (), {"_capture_hook": staticmethod(lambda *_: payload)})(),
    )


def test_post_tool_use_combines_capture_and_session_note(
    tmp_path: Path, monkeypatch, capsys
):
    config = _hook_environment(tmp_path, monkeypatch)
    (config / "config.toml").write_text(
        '[hooks.post_tool_use]\nproviders = ["capture", "session_notes"]\n'
    )
    _stub_capture(monkeypatch, b'{"additionalContext":"captured"}')
    payload = {
        "session_id": "s",
        "usage": {"input": 90},
        "model": {"contextWindow": 100},
    }

    hook.post_tool_use("pi", json.dumps(payload).encode())

    value = json.loads(capsys.readouterr().out)
    assert value["additionalContext"].startswith(
        "captured\n\nContext reached 90 tokens (threshold 90)"
    )
    assert "Orchestrators: write HANDOFF.md" in value["additionalContext"]


def test_post_tool_use_ignores_subagent_note_and_keeps_capture(
    tmp_path: Path, monkeypatch, capsys
):
    config = _hook_environment(tmp_path, monkeypatch)
    (config / "config.toml").write_text(
        '[hooks.post_tool_use]\nproviders = ["capture", "session_notes"]\n'
    )
    _stub_capture(monkeypatch, b"captured")

    hook.post_tool_use("pi", b'{"session_id":"s","agent_id":"a"}')

    assert capsys.readouterr().out == "captured"


def test_session_start_formats_plain_harness(tmp_path: Path, monkeypatch, capsys):
    config = _hook_environment(tmp_path, monkeypatch)
    (config / "config.toml").write_text(
        '[instructions]\ntargets = ["installed.md"]\n'
        '[hooks.session_start]\nproviders = ["orchestration"]\n'
    )

    hook.session_start("pi", b'{"session_id":"s"}')

    output = capsys.readouterr().out
    assert output.startswith("varde session: s\n\nvarde session notes: ")
    assert output.rstrip().endswith("notes.md")


def test_session_start_resolves_code_nav_map_lazily(
    tmp_path: Path, monkeypatch, capsys
):
    config = _hook_environment(tmp_path, monkeypatch)
    (config / "config.toml").write_text(
        '[instructions]\ntargets = ["installed.md"]\n'
        '[hooks.session_start]\nproviders = ["nav_map"]\n'
    )
    seen = []
    monkeypatch.setattr("varde_code.index.paths.repo_db_path", lambda root: root / "db")

    def nav_map_text(payload, include_symbols):
        seen.append(payload["repoRoot"])
        return "repo map"

    monkeypatch.setattr("varde_code.query.nav_map.nav_map_text", nav_map_text)

    hook.session_start("pi", b"{}")

    assert capsys.readouterr().out.strip() == "repo map"
    assert seen


def _nav_map_with_envelope(tmp_path, monkeypatch, capsys, code: str):
    config = _hook_environment(tmp_path, monkeypatch)
    (config / "config.toml").write_text(
        '[instructions]\ntargets = ["installed.md"]\n'
        '[hooks.session_start]\nproviders = ["nav_map"]\n'
    )
    envelope = json.dumps({"ok": False, "data": {"error": {"code": code}}})
    monkeypatch.setattr("varde_code.index.paths.repo_db_path", lambda root: root / "db")
    monkeypatch.setattr(
        "varde_code.query.nav_map.nav_map_text", lambda payload, symbols: envelope
    )
    hook.session_start("pi", b"{}")
    return capsys.readouterr()


def test_session_start_nav_map_silent_without_index(tmp_path, monkeypatch, capsys):
    output = _nav_map_with_envelope(tmp_path, monkeypatch, capsys, "index_missing")

    assert "skipped" not in output.out
    assert "skipped" not in output.err


def test_session_start_nav_map_stale_index_still_notices(tmp_path, monkeypatch, capsys):
    output = _nav_map_with_envelope(tmp_path, monkeypatch, capsys, "index_stale")

    assert "provider `nav_map` skipped: index_stale" in output.out


def test_session_start_unreadable_config_skips_providers(
    tmp_path: Path, monkeypatch, capsys
):
    config = _hook_environment(tmp_path, monkeypatch)
    (config / "config.toml").write_text("[session\nnotes = 1\n")

    hook.session_start("pi", b"{}")

    output = capsys.readouterr()
    assert "config unreadable" in output.out
    assert "no providers run" in output.out
    assert "config unreadable" in output.err


def test_oversized_post_payload_is_ignored(tmp_path: Path, monkeypatch, capsys):
    config = _hook_environment(tmp_path, monkeypatch)
    (config / "config.toml").write_text(
        '[hooks.post_tool_use]\nproviders = ["capture"]\n'
    )
    _stub_capture(
        monkeypatch, b'{"hookSpecificOutput":{"additionalContext":"captured"}}'
    )

    hook.post_tool_use("pi", b"x" * (hook.MAX_PAYLOAD_BYTES + 1))

    assert capsys.readouterr().out == ""


def test_post_tool_use_without_payload_records_no_failure(
    tmp_path: Path, monkeypatch, capsys
):
    config = _hook_environment(tmp_path, monkeypatch)
    (config / "config.toml").write_text(
        '[hooks.post_tool_use]\nproviders = ["capture"]\n'
    )
    diagnostics = tmp_path / "toz"
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(diagnostics))

    hook.post_tool_use("pi", b"")

    assert capsys.readouterr().out == ""
    assert not (diagnostics / "diagnostics.jsonl").exists()

    hook.post_tool_use("pi", b"not json")

    events = [
        json.loads(line)
        for line in (diagnostics / "diagnostics.jsonl").read_text().splitlines()
    ]
    assert [(row["harness"], row["outcome"], row["reason"]) for row in events] == [
        ("pi", "failed", "invalid-payload")
    ]


class _PipelineSessionNotes:
    def turn_prompt(self, harness: str, session_id: str) -> str:
        return f"checkpoint required for {harness}:{session_id}"

    def turn_end(self, harness: str, session_id: str, payload: bytes) -> str:
        return f"handoff blocked for {harness}:{session_id}"


def test_user_prompt_and_stop_hooks_gate_pipeline_boundary(
    tmp_path: Path, monkeypatch, capsys
):
    _hook_environment(tmp_path, monkeypatch)
    monkeypatch.setattr(hook, "_config", dict)
    monkeypatch.setattr(hook, "_session_notes", _PipelineSessionNotes)
    raw = b'{"session_id":"pipeline-worker"}'

    hook.dispatch({"event": "user-prompt-submit", "input": raw}, "codex")
    prompt = capsys.readouterr().out
    hook.dispatch({"event": "stop", "input": raw}, "codex")
    stopped = json.loads(capsys.readouterr().out)

    assert "checkpoint required for codex:pipeline-worker" in prompt
    assert stopped["decision"] == "block"
    assert "handoff blocked for codex:pipeline-worker" in stopped["reason"]


def test_runner_off_session_inbox_is_silent_but_checkpoint_still_blocks(
    tmp_path: Path, monkeypatch, capsys
):
    _hook_environment(tmp_path, monkeypatch)
    monkeypatch.setenv("VARDE_RUNNER_ENABLED", "0")
    monkeypatch.setattr(hook, "_config", dict)
    monkeypatch.setattr(hook, "_session_notes", _PipelineSessionNotes)
    recorded: list[str] = []
    monkeypatch.setattr(
        "varde.glue.hook_record.record_firing",
        lambda name, **_: recorded.append(name),
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("address resolved with the runner off")

    monkeypatch.setattr("varde.glue.inbox_hook.resolve_address", forbidden)
    raw = b'{"session_id":"s1","source":"compact"}'

    assert hook._session_inbox("codex", raw) == []
    hook.dispatch({"event": "stop", "input": raw}, "codex")
    stopped = json.loads(capsys.readouterr().out)

    assert "handoff blocked for codex:s1" in stopped["reason"]
    assert recorded == ["hook-stop-inbox-block"]


def test_default_session_providers_include_memory():
    providers, _, _ = hook._session_providers(
        {"instructions": {"targets": ["x"]}}, None
    )
    assert providers[-1] == "memory"
    assert (
        "memory"
        not in hook._session_providers(
            {"hooks": {"session_start": {"providers": ["inbox"]}}}, None
        )[0]
    )


def test_session_start_memory_provider_failure_yields_notice(
    tmp_path: Path, monkeypatch, capsys
):
    config = _hook_environment(tmp_path, monkeypatch)
    (config / "config.toml").write_text(
        '[instructions]\ntargets = ["installed.md"]\n'
        '[hooks.session_start]\nproviders = ["memory"]\n'
    )

    def boom(harness, raw):
        raise OSError("boom")

    monkeypatch.setattr("varde.glue.memory_hook.memory_section", boom)

    hook.session_start("pi", b'{"session_id":"s"}')

    assert "provider `memory` skipped: failed" in capsys.readouterr().out
