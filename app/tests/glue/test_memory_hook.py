# ruff: noqa: S603, S607
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from varde.glue import hook, memory_hook
from varde_learn.memory import store
from varde_learn.memory.entry import Entry

CREATED = "2026-01-01T00:00:00Z"


def entry(entry_id: str, scope: str, key: str = "") -> Entry:
    agent = scope == "agent"
    return Entry(
        id=entry_id,
        scope=scope,
        scope_key=key,
        text=f"lesson {entry_id}\nbody {entry_id}",
        source="t",
        created=CREATED,
        model="m" if agent else "",
        harness_version="1" if agent else "",
    )


@pytest.fixture
def memory_root(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "mem"
    monkeypatch.setenv("VARDE_MEMORY_DIR", str(root))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setenv("VARDE_WORKING_DIR", str(tmp_path / "working"))
    monkeypatch.setenv("VARDE_RUNNER_ENABLED", "0")
    monkeypatch.chdir(tmp_path)
    return root


def test_role_of_address_forms() -> None:
    assert memory_hook.role_of_address("plan1-builder") == "builder"
    assert memory_hook.role_of_address("builder:plan1") == "builder"
    assert memory_hook.role_of_address("main") == "main"
    assert memory_hook.role_of_address("") is None
    assert memory_hook.role_of_address(None) is None


def test_agent_from_payload() -> None:
    assert memory_hook.agent_from_payload({"agent_type": "builder"}) == "builder"
    assert memory_hook.agent_from_payload({"agent_type": " "}) is None
    assert memory_hook.agent_from_payload({}) is None
    assert memory_hook.agent_from_payload([]) is None


def test_pointer_with_known_agent_has_index_and_skill_line(
    memory_root, tmp_path
) -> None:
    store.write_entry(memory_root, entry("a1", "agent", "builder"))
    store.write_entry(memory_root, entry("g1", "global"))
    store.write_entry(memory_root, entry("s1", "skill", "varde-build"))
    text = memory_hook.pointer_text(tmp_path, "builder")
    assert "a1 | agent | lesson a1" in text and "g1 | global" in text
    assert "Skill memory: varde-build (1)" in text
    assert "body a1" not in text and "s1 | skill" not in text


def test_pointer_without_agent_has_global_and_skill_line_only(
    memory_root, tmp_path
) -> None:
    store.write_entry(memory_root, entry("a1", "agent", "builder"))
    store.write_entry(memory_root, entry("g1", "global"))
    store.write_entry(memory_root, entry("s1", "skill", "varde-build"))
    text = memory_hook.pointer_text(tmp_path, None)
    assert "a1 |" not in text and "g1 | global" in text
    assert "Skill memory: varde-build (1)" in text


def test_empty_store_emits_nothing(memory_root, tmp_path) -> None:
    assert memory_hook.pointer_text(tmp_path, "builder") == ""


def test_only_other_agents_entries_emit_nothing(memory_root, tmp_path) -> None:
    store.write_entry(memory_root, entry("a2", "agent", "reviewer"))
    assert memory_hook.pointer_text(tmp_path, "builder") == ""


def test_linked_worktree_uses_main_checkout_project_key(memory_root, tmp_path) -> None:
    main = tmp_path / "main"
    main.mkdir()
    for args in (
        ["init", "-q", "-b", "main"],
        [
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@x",
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            "i",
        ],
    ):
        subprocess.run(["git", "-C", str(main), *args], check=True, capture_output=True)
    worktree = tmp_path / "linked"
    subprocess.run(
        ["git", "-C", str(main), "worktree", "add", "-q", str(worktree)],
        check=True,
        capture_output=True,
    )
    key = store.current_project_key(main)
    store.write_entry(memory_root, entry("p1", "project", key))
    assert store.current_project_key(worktree) == key
    assert "p1 | project" in memory_hook.pointer_text(worktree, None)


def test_session_start_runs_memory_provider(memory_root, tmp_path, capsys) -> None:
    store.write_entry(memory_root, entry("g1", "global"))
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "config.toml").write_text(
        '[instructions]\ntargets = ["x.md"]\n'
        '[hooks.session_start]\nproviders = ["memory"]\n'
    )
    hook.session_start("pi", b'{"session_id":"s","agent_type":"builder"}')
    assert "g1 | global | lesson g1" in capsys.readouterr().out


def test_role_maps_to_both_agent_name_forms() -> None:
    assert memory_hook.role_agent_names("builder") == ("builder", "varde-builder")
    assert memory_hook.role_agent_names(None) is None


def test_pointer_matches_agent_entries_keyed_by_either_name(
    memory_root, tmp_path
) -> None:
    store.write_entry(memory_root, entry("a1", "agent", "builder"))
    store.write_entry(memory_root, entry("a2", "agent", "varde-builder"))
    store.write_entry(memory_root, entry("a3", "agent", "varde-reviewer"))
    text = memory_hook.pointer_text(tmp_path, ("builder", "varde-builder"))
    assert "a1 | agent" in text and "a2 | agent" in text and "a3 |" not in text


def test_hook_does_not_warn_about_dropped_shared_files(
    memory_root, tmp_path, monkeypatch, capsys
) -> None:
    from varde_learn.memory import share

    monkeypatch.setattr(
        share, "read_shared", lambda checkout=None: ([], ["dropped shared x: bad"])
    )
    store.write_entry(memory_root, entry("g1", "global"))
    memory_hook.pointer_text(tmp_path, None)
    assert "dropped" not in capsys.readouterr().err


def test_hook_latency_with_200_entries_and_no_index_write(
    memory_root, tmp_path, monkeypatch
) -> None:
    import time

    from varde_core import paths

    for i in range(200):
        store.write_entry(memory_root, entry(f"g{i}", "global"))
    monkeypatch.setattr(paths, "data_dir", lambda: None)
    started = time.perf_counter()
    text = memory_hook.pointer_text(tmp_path, None)
    elapsed = time.perf_counter() - started
    assert "g0 | global" in text or "omitted" in text
    assert elapsed < 0.25
    assert not (tmp_path / "share").exists()
