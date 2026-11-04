from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
from varde.glue import hook_record
from varde_learn.loop.calls import CALLS_NAME


@pytest.mark.parametrize(
    "case",
    [
        "env",
        "xdg",
        "home_fallback",
        "unset_home",
        "config",
        "relative",
        "dotdot",
        "tilde",
        "unset_home_tilde",
        "symlink",
        "symlink_missing_tail",
        "config_symlink",
        "dangling_symlink",
        "symlink_loop",
        "absent",
        "bad_learn_type",
        "empty_learn",
        "bad_default",
        "malformed",
    ],
)
def test_store_dir_matches_learn_resolver(tmp_path, monkeypatch, case):  # noqa: C901, PLR0912, PLR0915
    from varde_data.paths import resolve_learn_store
    from varde_learn.loop.errors import StoreConfig, StoreIo
    from varde_learn.loop.store.paths import resolve_store_dir

    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("VARDE_LEARN_STORE", raising=False)
    if case == "env":
        monkeypatch.setenv("VARDE_LEARN_STORE", "~/env-store")
    elif case == "config":
        (config / "config.toml").write_text('default = { learn = "configured" }')
    elif case == "xdg":
        monkeypatch.delenv("VARDE_CONFIG_DIR", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    elif case == "home_fallback":
        monkeypatch.delenv("VARDE_CONFIG_DIR", raising=False)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    elif case == "unset_home":
        monkeypatch.delenv("VARDE_CONFIG_DIR", raising=False)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        monkeypatch.delenv("HOME", raising=False)
    elif case == "relative":
        (config / "config.toml").write_text('default = { learn = "../relative" }')
    elif case == "dotdot":
        (config / "existing").mkdir()
        (config / "config.toml").write_text(
            'default = { learn = "existing/../relative" }'
        )
    elif case == "tilde":
        (config / "config.toml").write_text('default = { learn = "~/configured" }')
    elif case == "unset_home_tilde":
        monkeypatch.delenv("HOME", raising=False)
        (config / "config.toml").write_text('default = { learn = "~/configured" }')
    elif case == "symlink":
        target = tmp_path / "target"
        target.mkdir()
        (tmp_path / "link").symlink_to(target, target_is_directory=True)
        monkeypatch.setenv("VARDE_LEARN_STORE", str(tmp_path / "link" / "child"))
    elif case == "symlink_missing_tail":
        target = tmp_path / "target"
        target.mkdir()
        (tmp_path / "link").symlink_to(target, target_is_directory=True)
        monkeypatch.setenv(
            "VARDE_LEARN_STORE", str(tmp_path / "link" / "missing" / "child")
        )
    elif case == "dangling_symlink":
        (tmp_path / "link").symlink_to(tmp_path / "missing", target_is_directory=True)
        monkeypatch.setenv("VARDE_LEARN_STORE", str(tmp_path / "link" / "child"))
    elif case == "symlink_loop":
        (tmp_path / "loop").symlink_to(tmp_path / "loop")
        monkeypatch.setenv("VARDE_LEARN_STORE", str(tmp_path / "loop" / "child"))
    elif case == "config_symlink":
        target = tmp_path / "target"
        target.mkdir()
        (tmp_path / "link").symlink_to(target, target_is_directory=True)
        (config / "config.toml").write_text(
            f'default = {{ learn = "{tmp_path}/link/child" }}'
        )
    elif case == "bad_learn_type":
        (config / "config.toml").write_text("default = { learn = 42 }")
    elif case == "empty_learn":
        (config / "config.toml").write_text('default = { learn = " " }')
    elif case == "bad_default":
        (config / "config.toml").write_text('default = "wrong"')
    elif case == "malformed":
        (config / "config.toml").write_text("not = [toml")

    if case in {"malformed", "bad_learn_type", "empty_learn", "unset_home_tilde"}:
        with pytest.raises(StoreConfig):
            resolve_store_dir()
        assert hook_record.record_firing("id") is False
    elif case == "symlink_loop":
        with pytest.raises(StoreIo):
            resolve_store_dir()
        assert hook_record.record_firing("id") is False
    else:
        assert hook_record.resolve_store_dir() == resolve_learn_store()


def test_record_shape_and_readback(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_LEARN_STORE", str(tmp_path))
    monkeypatch.setenv("CODEX_THREAD_ID", "session-1")
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    row = hook_record.build_row("guard-1", blocked=True)
    assert {"ts", "command", "status", "duration_s", "session"} <= set(row)
    assert isinstance(row["duration_s"], float)
    assert row["session"] == "session-1"
    assert row["command"] == "hook guard-1"
    assert row["status"] == "blocked"
    assert hook_record.record_firing("guard-1", blocked=True)
    stored = json.loads((tmp_path / CALLS_NAME).read_text().splitlines()[0])
    assert stored == row | {"ts": stored["ts"]}


def test_append_repairs_newline_and_uses_private_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_LEARN_STORE", str(tmp_path))
    path = tmp_path / "cli_calls.jsonl"
    path.write_text('{"old":true}')
    assert hook_record.record_firing("guard-1")
    assert len(path.read_bytes().splitlines()) == 2
    assert os.stat(path).st_mode & 0o777 == 0o600


def test_append_failure_returns_false(monkeypatch):
    monkeypatch.setattr(
        hook_record, "resolve_store_dir", lambda: (_ for _ in ()).throw(OSError())
    )
    assert hook_record.record_firing("guard-1") is False


def test_store_path_file_failure_returns_false(tmp_path, monkeypatch):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    monkeypatch.setenv("VARDE_LEARN_STORE", str(blocker / "store"))
    assert hook_record.record_firing("guard-1") is False


def test_import_loads_no_varde_package():
    script = """
import sys
import varde.glue
import varde.glue.hook_record
assert not any(name.startswith('varde_') for name in sys.modules)
"""
    env = os.environ.copy()
    for name in ("VARDE_CONFIG_DIR", "XDG_CONFIG_HOME", "VARDE_LEARN_STORE"):
        env.pop(name, None)
    subprocess.run([sys.executable, "-c", script], check=True, env=env, text=True)  # noqa: S603 - test launches an isolated Python process


def test_firing_after_calls_flip_lands_in_sqlite_not_jsonl(tmp_path, monkeypatch):
    from varde_data.calls import open_calls
    from varde_data.learn_store_mode import flip_domain_locked

    monkeypatch.setenv("VARDE_LEARN_STORE", str(tmp_path))
    assert hook_record.record_firing("before")
    flip_domain_locked(tmp_path, "calls", "sqlite")
    assert hook_record.record_firing("after")
    assert len((tmp_path / CALLS_NAME).read_text().splitlines()) == 1
    assert [row["guardrail"] for row in open_calls(tmp_path).read()] == ["after"]
