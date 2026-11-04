from __future__ import annotations

import io
import json
from typing import Any

import pytest
from varde_learn.loop import cli_memory
from varde_learn.memory import store
from varde_learn.module import register

KEY = "proj-0123456789abcdef"


class Io:
    def __init__(self) -> None:
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()


@pytest.fixture(autouse=True)
def memory_env(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_MEMORY_DIR", str(tmp_path / "mem"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.chdir(tmp_path)
    return tmp_path / "mem"


def call(*argv: str) -> tuple[int, str, str]:
    out = Io()
    code = cli_memory.run(["memory", *argv], out)
    return code, out.stdout.getvalue(), out.stderr.getvalue()


def add_json(*argv: str) -> dict[str, Any]:
    code, out, err = call("add", *argv, "--json")
    assert code == 0, err
    return json.loads(out)["data"]


AGENT = (
    "--scope",
    "agent",
    "--key",
    "builder",
    "--model",
    "m1",
    "--harness-version",
    "1",
)


def test_add_in_each_scope(memory_env) -> None:
    ids = [
        add_json("--scope", "global", "--text", "g note", "--tag", "t1")["id"],
        add_json(*AGENT, "--text", "a note")["id"],
        add_json("--scope", "skill", "--key", "varde-build", "--text", "s note")["id"],
        add_json("--scope", "project", "--key", KEY, "--text", "p note")["id"],
    ]
    assert len(set(ids)) == 4
    assert len(list(memory_env.rglob("*.md"))) == 4
    assert (memory_env / "agent" / "builder").is_dir()


def test_project_scope_defaults_to_current_project(memory_env) -> None:
    data = add_json("--scope", "project", "--text", "p")
    assert (memory_env / "project").is_dir()
    assert "/project/" in data["path"]


def test_add_with_project_field_on_skill(memory_env) -> None:
    add_json("--scope", "skill", "--key", "k", "--project", KEY, "--text", "s")
    assert next(store.load_entries(memory_env)).project == KEY


@pytest.mark.parametrize(
    "argv",
    [
        ("--scope", "global", "--project", KEY, "--text", "x"),
        ("--scope", "project", "--key", KEY, "--project", KEY, "--text", "x"),
        ("--scope", "skill", "--key", "../x", "--text", "x"),
        ("--scope", "skill", "--text", "x"),
        ("--scope", "agent", "--key", "b", "--text", "x"),
        ("--scope", "global", "--text", "password = hunter2hunter2"),
        ("--scope", "team", "--text", "x"),
        ("--scope", "global", "--text", "  "),
    ],
)
def test_add_rejects(argv, memory_env) -> None:
    code, _, err = call("add", *argv)
    assert code == 2
    assert err
    assert not list(memory_env.rglob("*.md")) if memory_env.exists() else True


def test_list_filters_and_default_active(memory_env) -> None:
    g = add_json("--scope", "global", "--text", "global one")["id"]
    add_json("--scope", "skill", "--key", "alpha", "--text", "alpha one")
    add_json("--scope", "skill", "--key", "beta", "--text", "beta one")
    add_json(*AGENT, "--text", "agent one")
    code, out, _ = call("list")
    assert code == 0 and len(out.splitlines()) == 4
    assert out.splitlines()[0].split(" | ")[1] == "agent"
    _, out, _ = call("list", "--scope", "global")
    assert out.startswith(g)
    _, out, _ = call("list", "--skill", "alpha")
    assert out.count("\n") == 1 and "alpha one" in out
    _, by_scope_key, _ = call("list", "--scope", "skill", "--key", "alpha")
    assert by_scope_key == out
    assert call("list", "--skill", "alpha", "--scope", "global")[0] == 2
    code, out, _ = call("list", "--json")
    assert json.loads(out)["data"]["entries"][0]["scope"] == "agent"
    call("retire", g)
    assert g not in call("list")[1]
    assert g in call("list", "--all")[1]


def test_show_and_missing(memory_env) -> None:
    entry_id = add_json(*AGENT, "--text", "hello world")["id"]
    code, out, _ = call("show", entry_id)
    assert code == 0 and "model: m1" in out and out.rstrip().endswith("hello world")
    code, _, err = call("show", "nope")
    assert code == 1 and "no memory entry" in err
    assert call("show", "../x")[0] == 2
    assert call("show")[0] == 2


def test_retire_sets_status(memory_env) -> None:
    entry_id = add_json("--scope", "global", "--text", "x")["id"]
    assert call("retire", entry_id)[0] == 0
    assert next(store.load_entries(memory_env)).status == "retired"
    assert call("retire", "missing")[0] == 1


def test_reset_archives_mismatching_agent_entries(memory_env) -> None:
    old = add_json(*AGENT, "--text", "old model")["id"]
    same = add_json(
        "--scope",
        "agent",
        "--key",
        "builder",
        "--model",
        "m2",
        "--harness-version",
        "1",
        "--text",
        "same",
    )["id"]
    other_agent = add_json(
        "--scope",
        "agent",
        "--key",
        "planner",
        "--model",
        "m1",
        "--harness-version",
        "1",
        "--text",
        "other agent",
    )["id"]
    glob = add_json("--scope", "global", "--text", "global")["id"]
    skill = add_json("--scope", "skill", "--key", "k", "--text", "skill")["id"]
    args = ("reset", "--agent", "builder", "--model", "m2", "--harness-version", "1")

    before = {p: p.read_text() for p in memory_env.rglob("*.md")}
    code, out, _ = call(*args, "--dry-run")
    assert code == 0 and old in out
    assert {p: p.read_text() for p in memory_env.rglob("*.md")} == before

    assert call(*args)[0] == 0
    status = {e.id: e.status for e in store.load_entries(memory_env)}
    assert status[old] == "archived"
    assert all(status[i] == "active" for i in (same, other_agent, glob, skill))
    assert old not in call("list")[1]
    assert old in call("list", "--all")[1]
    assert call("reset", "--agent", "builder")[0] == 2


def test_later_verbs_help_works_and_missing_module_is_reported(monkeypatch) -> None:
    for verb in ("surface", "promote", "pull", "migrate"):
        code, out, _ = call(verb, "--help")
        assert code == 0 and "Usage: varde learn memory" in out
    monkeypatch.setitem(cli_memory.LATER_VERBS, "promote", "cli_memory_absent")
    code, _, err = call("promote", "x")
    assert code == 2 and "not yet available" in err


def test_promote_and_pull_without_a_shared_store_exit_2() -> None:
    code, _, err = call("promote", "abc")
    assert code == 2 and "pull" in err
    code, _, err = call("pull")
    assert code == 2 and "[memory] shared" in err


def test_group_help_and_usage() -> None:
    code, out, _ = call("--help")
    assert code == 0
    for verb in cli_memory.VERBS:
        assert f"  {verb} " in out
    for scope in ("agent", "skill", "project", "global"):
        assert scope in out
    code, out, err = call()
    assert code == 2 and out == "" and "Usage" in err
    assert call("bogus")[0] == 2


def test_registered_in_learn_module(capsys) -> None:
    assert register().run(["memory", "--help"]) == 0
    assert "add" in capsys.readouterr().out
    assert register().run(["memory"]) == 2
    assert (
        register().run(
            ["memory", "add", "--scope", "skill", "--key", "../x", "--text", "t"]
        )
        == 2
    )
