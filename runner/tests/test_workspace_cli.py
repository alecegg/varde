from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from starlette.applications import Starlette
from test_web import app_request
from varde_runner import workspace_cli
from varde_runner.web.workspaces import create_workspaces_routes
from varde_runner.workitems import WorkItemStore
from varde_runner.workspaces_service import WorkspacesService


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True)  # noqa: S603, S607


def test_create_sends_caller_and_prints_script_keys(monkeypatch, capsys):
    captured = {}

    def request(method, port, *, payload=None, query=None):
        captured.update(method=method, port=port, payload=payload)
        return 201, {"path": "/repo/.varde/worktrees/task", "branch": "worktree/task"}

    monkeypatch.setattr(workspace_cli, "_request", request)
    monkeypatch.setattr(workspace_cli.os, "getcwd", lambda: "/repo")
    workspace_cli.main(["create", "task", "--repo", "/repo"])
    assert captured["method"] == "POST"
    assert captured["payload"]["caller"] == "/repo"
    assert capsys.readouterr().out.splitlines() == [
        "path=/repo/.varde/worktrees/task",
        "branch=worktree/task",
        "created=true",
    ]


def test_list_json(monkeypatch, capsys):
    entries = [{"id": "/repo", "kind": "repo"}]
    monkeypatch.setattr(
        workspace_cli,
        "_request",
        lambda *a, **k: (200, {"workspaces": entries}),
    )
    workspace_cli.main(["list", "--json"])
    assert json.loads(capsys.readouterr().out) == entries


def test_remove_infers_unique_repo(monkeypatch, capsys):
    calls = []

    def request(method, port, *, payload=None, query=None):
        calls.append((method, query))
        if method == "GET":
            return 200, {
                "workspaces": [
                    {"kind": "worktree", "branch": "worktree/task", "repo": "/repo"}
                ]
            }
        return 200, {"branch": "worktree/task", "ignored_removed": ["cache.tmp"]}

    monkeypatch.setattr(workspace_cli, "_request", request)
    monkeypatch.setattr(workspace_cli.os, "getcwd", lambda: "/repo")
    workspace_cli.main(["remove", "task"])
    assert calls[1][1]["repo"] == "/repo"
    assert capsys.readouterr().out.splitlines() == [
        "removed=true",
        "branch=worktree/task",
        "ignored=cache.tmp",
    ]


@pytest.mark.parametrize(
    ("status", "message", "code", "expected"),
    [
        (409, "already exists", "exists", 3),
        (422, "base does not resolve", "base_unresolved", 2),
        (409, "dirty worktree", "dirty", 4),
        (500, "verification failed", "verify_failed", 5),
        (500, "git failed", "git_failed", 5),
        (504, "git timed out", "command_timeout", 5),
    ],
)
def test_error_exit_codes(monkeypatch, status, message, code, expected):
    monkeypatch.setattr(
        workspace_cli,
        "_request",
        lambda *a, **k: (status, {"error": message, "code": code}),
    )
    with pytest.raises(SystemExit) as exc:
        workspace_cli.main(["remove", "task", "--repo", "/repo"])
    assert exc.value.code == expected


def test_ambiguous_remove_exits_one(monkeypatch, capsys):
    monkeypatch.setattr(
        workspace_cli,
        "_request",
        lambda *a, **k: (
            200,
            {
                "workspaces": [
                    {"kind": "worktree", "branch": "worktree/task", "repo": "/a"},
                    {"kind": "worktree", "branch": "worktree/task", "repo": "/b"},
                ]
            },
        ),
    )
    with pytest.raises(SystemExit) as exc:
        workspace_cli.main(["remove", "task"])
    assert exc.value.code == 1
    assert "/a, /b" in capsys.readouterr().err


def test_usage_error_exits_one():
    with pytest.raises(SystemExit) as exc:
        workspace_cli.main(["create"])
    assert exc.value.code == 1


def test_git_runtime_error_returns_code_and_cli_exit_five(tmp_path, monkeypatch):
    class FailedService:
        async def remove(self, *args, **kwargs):
            raise RuntimeError("git worktree remove failed")

    store = WorkItemStore(tmp_path / "store")
    app = Starlette(
        routes=create_workspaces_routes(lambda: None, store, FailedService())
    )

    def request(method, port, *, payload=None, query=None):
        from urllib.parse import urlencode

        path = "/api/workspaces?" + urlencode(query or {})
        response = app_request(app, method, path)
        return response.status_code, response.json()

    monkeypatch.setattr(workspace_cli, "_request", request)
    with pytest.raises(SystemExit) as exc:
        workspace_cli.main(["remove", "task", "--repo", "/repo"])
    assert exc.value.code == 5
    store.close()


def test_cli_create_list_remove_against_workspace_app(tmp_path, monkeypatch, capsys):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / ".gitignore").write_text("ignored.tmp\n")
    (repo / "tracked").write_text("content")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    store = WorkItemStore(tmp_path / "store")
    service = WorkspacesService([repo])
    app = Starlette(routes=create_workspaces_routes(lambda: None, store, service))

    def request(method, port, *, payload=None, query=None):
        path = "/api/workspaces"
        if query:
            from urllib.parse import urlencode

            path += "?" + urlencode(query)
        response = app_request(
            app,
            method,
            path,
            content=json.dumps(payload or {}).encode(),
            headers={"content-type": "application/json"},
        )
        return response.status_code, response.json()

    monkeypatch.setattr(workspace_cli, "_request", request)
    monkeypatch.setattr(workspace_cli.os, "getcwd", lambda: str(repo))
    workspace_cli.main(["create", "task", "--repo", str(repo)])
    assert "created=true" in capsys.readouterr().out
    with pytest.raises(SystemExit) as exists:
        workspace_cli.main(["create", "task", "--repo", str(repo)])
    assert exists.value.code == 3
    with pytest.raises(SystemExit) as bad_id:
        workspace_cli.main(["create", "..", "--repo", str(repo)])
    assert bad_id.value.code == 1
    worktree = repo / ".varde" / "worktrees" / "task"
    (worktree / "ignored.tmp").write_text("ignored")

    workspace_cli.main(["list", "--json"])
    rows = json.loads(capsys.readouterr().out)
    assert any(row["branch"] == "worktree/task" for row in rows)

    workspace_cli.main(["remove", "task", "--repo", str(repo)])
    assert "ignored=ignored.tmp" in capsys.readouterr().out.splitlines()
    assert not worktree.exists()
    store.close()
