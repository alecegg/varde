from __future__ import annotations

import json

import pytest
from varde.glue import hook, memory_subagent
from varde_learn.memory import store
from varde_learn.memory.entry import Entry

CREATED = "2026-01-01T00:00:00Z"

# Payload shapes read from the Claude Code 2.1.296 hook table (agent_id,
# agent_type) and the Codex 0.162.1 `subagent-start.command.input` schema.
CLAUDE_PAYLOAD = {
    "session_id": "s1",
    "transcript_path": "/t/s1.jsonl",
    "cwd": "{cwd}",
    "hook_event_name": "SubagentStart",
    "agent_id": "agent-1",
    "agent_type": "varde-builder",
}
CODEX_PAYLOAD = {
    **CLAUDE_PAYLOAD,
    "model": "gpt",
    "permission_mode": "default",
    "turn_id": "t1",
}


def entry(entry_id: str, key: str) -> Entry:
    return Entry(
        id=entry_id,
        scope="agent",
        scope_key=key,
        text=f"lesson {entry_id}\nbody {entry_id}",
        source="t",
        created=CREATED,
        model="m",
        harness_version="1",
    )


@pytest.fixture
def memory_root(tmp_path, monkeypatch):
    root = tmp_path / "mem"
    monkeypatch.setenv("VARDE_MEMORY_DIR", str(root))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setenv("VARDE_RUNNER_ENABLED", "0")
    monkeypatch.chdir(tmp_path)
    store.write_entry(root, entry("a1", "builder"))
    store.write_entry(root, entry("a2", "varde-builder"))
    store.write_entry(root, entry("a3", "reviewer"))
    return root


def raw(payload: dict, cwd) -> bytes:
    return json.dumps(payload).replace("{cwd}", str(cwd)).encode()


def test_subagent_names_match_both_key_forms() -> None:
    assert memory_subagent.subagent_names("varde-builder") == (
        "builder",
        "varde-builder",
    )
    assert memory_subagent.subagent_names("builder") == ("builder", "varde-builder")


@pytest.mark.parametrize("payload", [CLAUDE_PAYLOAD, CODEX_PAYLOAD])
def test_section_lists_the_started_agents_entries(
    memory_root, tmp_path, payload
) -> None:
    text = memory_subagent.subagent_section(raw(payload, tmp_path))
    assert "a1 | agent" in text and "a2 | agent" in text
    assert "a3 |" not in text and "body a1" not in text


def test_section_is_empty_without_agent_type_or_with_bad_json(
    memory_root, tmp_path
) -> None:
    bare = {k: v for k, v in CLAUDE_PAYLOAD.items() if k != "agent_type"}
    assert memory_subagent.subagent_section(raw(bare, tmp_path)) == ""
    assert memory_subagent.subagent_section(b"not json") == ""


@pytest.mark.parametrize("harness", ["claude", "codex"])
def test_hook_writes_subagent_start_context(
    memory_root, tmp_path, capsys, harness
) -> None:
    hook.dispatch(
        {"event": "subagent-start", "input": raw(CLAUDE_PAYLOAD, tmp_path)}, harness
    )
    out = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert out["hookEventName"] == "SubagentStart"
    assert "a1 | agent" in out["additionalContext"]


def test_hook_prints_nothing_for_other_harnesses(memory_root, tmp_path, capsys) -> None:
    hook.dispatch(
        {"event": "subagent-start", "input": raw(CLAUDE_PAYLOAD, tmp_path)}, "pi"
    )
    assert capsys.readouterr().out == ""


def test_hook_honours_an_explicit_provider_list_without_memory(
    memory_root, tmp_path, capsys
) -> None:
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "config.toml").write_text(
        '[hooks.session_start]\nproviders = ["inbox"]\n'
    )
    hook.dispatch(
        {"event": "subagent-start", "input": raw(CLAUDE_PAYLOAD, tmp_path)}, "claude"
    )
    assert capsys.readouterr().out == ""
