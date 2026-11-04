import io
import json
import os
import sys
from types import SimpleNamespace

import pytest
from varde_toz import cli
from varde_toz.chunk import chunk_default
from varde_toz.project import store_db_path
from varde_toz.store import NewCapture, Store


def _project(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    base = tmp_path / "toz"
    root.mkdir()
    base.mkdir()
    monkeypatch.setenv("TOZ_CONFIG_DIR", str(base))
    monkeypatch.delenv("TOZ_PROJECT", raising=False)
    return root, base


def _capture(root, base, label):
    with Store.open(store_db_path(root, base)) as store:
        store.insert_capture(
            NewCapture(label, "run", label, bytes=4),
            [("stdout", chunk_default("body")[0])],
        )


def test_query_route_receives_limit_and_json_options(tmp_path, monkeypatch, capsys):
    root, base = _project(tmp_path, monkeypatch)
    _capture(root, base, "first")
    _capture(root, base, "second")

    assert (
        cli.main(["--project", str(root), "query", "--list", "--limit", "1", "--json"])
        == 0
    )
    assert len(json.loads(capsys.readouterr().out)) == 1


def test_global_project_option_scopes_the_command(tmp_path, monkeypatch, capsys):
    root, base = _project(tmp_path, monkeypatch)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    _capture(root, base, "only-here")

    assert cli.main(["--project", str(root), "query", "--list", "--json"]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 1
    assert "TOZ_PROJECT" not in os.environ

    assert cli.main(["query", "--list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_capture_route_reads_a_hook_payload(tmp_path, monkeypatch, capsysbinary):
    _project(tmp_path, monkeypatch)
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "varde"))
    token = "ghp_" + "a" * 36
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "cat f"},
        "tool_response": {"stdout": f"credential {token}\n", "stderr": ""},
    }
    monkeypatch.setattr(
        sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(payload).encode()))
    )

    assert cli.main(["capture", "--hook", "--harness", "claude"]) == 0
    output = capsysbinary.readouterr().out
    assert token.encode() not in output
    assert b"[redacted:github]" in output


def test_top_level_help_lists_commands(capsys):
    assert cli.main(["--help"]) == 0
    output = capsys.readouterr().out
    assert "query" in output
    assert "hook" in output


def test_unknown_command_errors(capsys):
    with pytest.raises(SystemExit) as error:
        cli.main(["unknown"])
    assert error.value.code == 2
    assert "unknown command: unknown" in capsys.readouterr().err
