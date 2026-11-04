# ruff: noqa: S603, S607
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from typing import cast

import pytest
from varde_runner.workspaces_config import configured_workspace_repos
from varde_runner.workspaces_service import WorkspaceError, WorkspacesService
from varde_runner.worktrees import add_worktree, list_worktrees


def git(repo, *args, check=True):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def make_repo(path):
    path.mkdir()
    git(path, "init", "-b", "main")
    git(path, "config", "user.email", "test@example.com")
    git(path, "config", "user.name", "Test")
    (path / "file").write_text("initial")
    git(path, "add", "file")
    git(path, "commit", "-m", "initial")
    return path


class FakeStore:
    def __init__(self, sessions=(), workspaces=None):
        self._sessions = list(sessions)
        self.workspaces = workspaces or {}
        self.upserts = []

    def sessions(self):
        return self._sessions

    def get_workspace(self, workspace_id):
        return self.workspaces.get(workspace_id)

    def upsert_workspace(self, workspace_id, **values):
        self.upserts.append((workspace_id, values))
        self.workspaces[workspace_id] = values


def service_for(repo, store=None, **kwargs):
    async def get_store():
        return store

    return WorkspacesService(
        [repo], get_store=get_store if store is not None else None, **kwargs
    )


def test_configured_repos_skips_invalid(tmp_path, caplog):
    repo = make_repo(tmp_path / "repo")
    missing = tmp_path / "missing"
    result = configured_workspace_repos(
        f'[workspaces]\nrepos = ["{repo}", "relative", "{missing}"]'
    )
    assert result == (repo,)
    assert "Ignoring invalid" in caplog.text


def test_create_list_and_remove_merged_into_caller_plan_branch(tmp_path, monkeypatch):
    repo = make_repo(tmp_path / "repo")

    async def scenario():
        service = service_for(repo)
        plan = await add_worktree(repo, "plan", base="HEAD")
        plan_admin = Path(git(plan, "rev-parse", "--git-dir").stdout.strip())
        created = await service.create(repo, "task", caller=plan)
        task = Path(created["path"])
        (repo / ".git/info/exclude").write_text("ignored.txt\n")
        (task / "ignored.txt").write_text("ignored content")
        git(task, "config", "user.email", "test@example.com")
        git(task, "config", "user.name", "Test")
        (task / "file").write_text("task change")
        git(task, "commit", "-am", "task change")
        git(plan, "merge", "--ff-only", "worktree/task")
        with pytest.raises(WorkspaceError, match="not merged") as error:
            await service.remove(repo, "task", caller=repo)
        assert error.value.status == 409
        assert task.exists()
        assert {row["kind"] for row in await service.list()} == {"repo", "worktree"}
        monkeypatch.setattr("varde_runner.workspaces_service._stop_watcher", noop)
        result = await service.remove(repo, "task", caller=plan)
        assert result["removed"] is True
        assert result["branch"] == "worktree/task"
        assert "ignored.txt" in result["ignored_removed"]
        assert not task.exists()
        assert not git(
            repo, "show-ref", "--verify", "refs/heads/worktree/task", check=False
        ).stdout
        # Native removal leaves the per-worktree admin entry and common registry intact.
        assert plan_admin.exists()
        assert not any(
            row["branch"] == "refs/heads/worktree/task"
            for row in await list_worktrees(repo)
        )
        source_files = [
            Path(__file__).parents[1] / "src/varde_runner" / name
            for name in (
                "worktrees.py",
                "workspaces_service.py",
                "workspaces_config.py",
            )
        ]
        assert all('"prune"' not in source.read_text() for source in source_files)
        git(repo, "worktree", "remove", str(plan))
        git(repo, "branch", "-D", "worktree/plan")

    async def noop(path, env=None):
        return None

    asyncio.run(scenario())


def test_create_rejects_unconfigured_bad_id_bad_base_and_foreign_caller(tmp_path):
    repo = make_repo(tmp_path / "repo")
    foreign = make_repo(tmp_path / "foreign")

    async def scenario():
        service = service_for(repo)
        with pytest.raises(WorkspaceError) as error:
            await service.create(foreign, "valid")
        assert error.value.status == 404
        with pytest.raises(WorkspaceError) as error:
            await service.create(repo, "bad/name")
        assert error.value.status == 422
        with pytest.raises(WorkspaceError) as error:
            await service.create(repo, "foreign-caller", caller=foreign)
        assert error.value.status == 422
        with pytest.raises(WorkspaceError) as error:
            await service.create(repo, "bad-base", base="no-such-commit")
        assert error.value.status == 422
        with pytest.raises(WorkspaceError) as error:
            await service.create(repo, "option-base", base="--help")
        assert error.value.code == "base_unresolved"
        assert not (repo / ".varde/worktrees/option-base").exists()

    asyncio.run(scenario())


def test_create_conflicts_on_registered_path_or_branch(tmp_path):
    repo = make_repo(tmp_path / "repo")

    async def scenario():
        service = service_for(repo)
        orphan_path = repo / ".varde/worktrees/exists"
        orphan_path.mkdir(parents=True)
        with pytest.raises(WorkspaceError) as error:
            await service.create(repo, "exists")
        assert error.value.status == 409
        orphan_path.rmdir()
        await add_worktree(repo, "exists", base="HEAD")
        with pytest.raises(WorkspaceError) as error:
            await service.create(repo, "exists")
        assert error.value.status == 409
        git(repo, "worktree", "remove", str(repo / ".varde/worktrees/exists"))
        # The branch remains after its worktree registration is removed.
        with pytest.raises(WorkspaceError) as error:
            await service.create(repo, "exists")
        assert error.value.status == 409

    asyncio.run(scenario())


def test_remove_registry_missing_duplicate_and_outside_path(tmp_path, monkeypatch):
    repo = make_repo(tmp_path / "repo")

    async def scenario():
        service = service_for(repo)
        with pytest.raises(WorkspaceError) as error:
            await service.remove(repo, "missing", caller=repo)
        assert error.value.status == 404
        target = await add_worktree(repo, "outside", base="HEAD")
        rows = await list_worktrees(repo)
        from varde_runner import workspaces_service as module

        original = module.list_worktrees
        monkeypatch.setattr(
            module, "list_worktrees", lambda *a, **k: async_result(rows + [rows[-1]])
        )
        with pytest.raises(WorkspaceError) as error:
            await service.remove(repo, "outside", caller=repo)
        assert error.value.status == 409
        monkeypatch.setattr("varde_runner.workspaces_service.list_worktrees", original)
        relocated = tmp_path / "external"
        git(repo, "worktree", "move", str(target), str(relocated))
        with pytest.raises(WorkspaceError) as error:
            await service.remove(repo, "outside", caller=repo)
        assert error.value.status == 404
        git(repo, "worktree", "move", str(relocated), str(target))
        git(repo, "worktree", "remove", str(target))
        git(repo, "branch", "-D", "worktree/outside")

    asyncio.run(scenario())


async def async_result(value):
    return value


def test_remove_refuses_caller_inside_dirty_and_unmerged(tmp_path):
    repo = make_repo(tmp_path / "repo")

    async def scenario():
        service = service_for(repo)
        target = Path((await service.create(repo, "checks"))["path"])
        with pytest.raises(WorkspaceError, match="inside") as error:
            await service.remove(repo, "checks", caller=target)
        assert error.value.status == 409
        (target / "untracked").write_text("dirty")
        with pytest.raises(WorkspaceError, match="uncommitted") as error:
            await service.remove(repo, "checks", caller=repo)
        assert error.value.status == 409
        (target / "untracked").unlink()
        git(target, "config", "user.email", "test@example.com")
        git(target, "config", "user.name", "Test")
        (target / "file").write_text("unmerged commit")
        git(target, "commit", "-am", "unmerged commit")
        with pytest.raises(WorkspaceError, match="not merged") as error:
            await service.remove(repo, "checks", caller=repo)
        assert error.value.status == 409
        git(repo, "worktree", "remove", str(target))
        git(repo, "branch", "-D", "worktree/checks")

    asyncio.run(scenario())


@pytest.mark.parametrize("path_form", ["plain", "trailing", "tilde", "subdir", "row"])
def test_live_session_workspace_forms_block_remove(tmp_path, monkeypatch, path_form):
    repo = make_repo(tmp_path / "repo")
    target = repo / ".varde/worktrees/live"
    home = tmp_path / "home"
    home.mkdir()
    if path_form == "tilde":
        target = home / "repo" / ".varde/worktrees/live"
        # Keep the checkout rooted below HOME so expanduser() covers this case.
        repo = make_repo(home / "repo")
        monkeypatch.setenv("HOME", str(home))
    git(repo, "worktree", "add", "-b", "worktree/live", str(target), "HEAD")
    workspace_id = str(target)
    workspace_row = None
    if path_form == "trailing":
        workspace_id += "/"
    elif path_form == "tilde":
        workspace_id = "~/repo/.varde/worktrees/live"
    elif path_form == "subdir":
        (target / "nested").mkdir()
        workspace_id = str(target / "nested")
    elif path_form == "row":
        workspace_id = "workspace-id"
        workspace_row = {workspace_id: {"cwd": str(target / "nested")}}
    store = FakeStore(
        [{"workspace_id": workspace_id, "lifecycle": "running"}], workspace_row
    )

    async def scenario():
        service = service_for(repo, store)
        with pytest.raises(WorkspaceError, match="live runner session") as error:
            await service.remove(repo, "live", caller=repo)
        assert error.value.status == 409

    asyncio.run(scenario())


def test_create_and_remove_upsert_store_rows(tmp_path, monkeypatch):
    repo = make_repo(tmp_path / "repo")
    store = FakeStore()

    async def scenario():
        service = service_for(repo, store)
        created = await service.create(repo, "stored")
        assert store.upserts[-1][0] == created["id"]
        assert store.upserts[-1][1]["branch"] == "worktree/stored"
        monkeypatch.setattr("varde_runner.workspaces_service._stop_watcher", noop)
        await service.remove(repo, "stored", discard=True)
        assert store.upserts[-1][1]["archived_at"]

    async def noop(path, env=None):
        return None

    asyncio.run(scenario())


def test_discard_reports_ignored_files_and_skips_dirty_and_merge_checks(
    tmp_path, monkeypatch
):
    repo = make_repo(tmp_path / "repo")
    (repo / ".git/info/exclude").write_text("ignored.txt\n")

    async def scenario():
        service = service_for(repo)
        target = Path((await service.create(repo, "discard"))["path"])
        (target / "ignored.txt").write_text("ignored")
        (target / "untracked.txt").write_text("dirty")
        monkeypatch.setattr("varde_runner.workspaces_service._stop_watcher", noop)
        result = await service.remove(repo, "discard", discard=True)
        assert "ignored.txt" in result["ignored_removed"]
        assert not target.exists()

    async def noop(path, env=None):
        return None

    asyncio.run(scenario())


def test_discard_still_refuses_live_session_with_trailing_slash(tmp_path):
    repo = make_repo(tmp_path / "repo")

    async def scenario():
        service = service_for(repo)
        target = Path((await service.create(repo, "live-discard"))["path"])
        store = FakeStore(
            [
                {
                    "workspace_id": str(target) + "/",
                    "lifecycle": "running",
                }
            ]
        )
        service = service_for(repo, store)
        with pytest.raises(WorkspaceError, match="live runner session") as error:
            await service.remove(repo, "live-discard", discard=True)
        assert error.value.status == 409
        assert error.value.code == "live_session"
        assert target.exists()

    asyncio.run(scenario())


def test_discard_still_refuses_caller_inside_worktree(tmp_path):
    repo = make_repo(tmp_path / "repo")

    async def scenario():
        service = service_for(repo)
        target = Path((await service.create(repo, "inside-discard"))["path"])
        with pytest.raises(WorkspaceError, match="caller is inside") as error:
            await service.remove(repo, "inside-discard", caller=target, discard=True)
        assert error.value.status == 409
        assert error.value.code == "caller_inside"
        assert target.exists()

    asyncio.run(scenario())


def test_registry_write_failures_do_not_change_git_results(
    tmp_path, monkeypatch, caplog
):
    repo = make_repo(tmp_path / "repo")

    async def scenario():
        async def unavailable_store():
            raise RuntimeError("store unavailable")

        create_service = WorkspacesService([repo], get_store=unavailable_store)
        created = await create_service.create(repo, "create-registry-failure")
        assert Path(created["path"]).is_dir()

        store_calls = 0

        async def failing_write_store():
            nonlocal store_calls
            store_calls += 1
            if store_calls == 1:
                return FakeStore()
            raise RuntimeError("registry write failed")

        remove_service = WorkspacesService([repo], get_store=failing_write_store)
        monkeypatch.setattr("varde_runner.workspaces_service._stop_watcher", noop)
        removed = await remove_service.remove(
            repo, "create-registry-failure", discard=True
        )
        assert removed["removed"] is True
        assert not Path(created["path"]).exists()
        assert "Could not update workspace registry" in caplog.text

    async def noop(path, env=None):
        return None

    asyncio.run(scenario())


def test_command_timeout_kills_child_and_maps_to_workspace_error(tmp_path, monkeypatch):
    from varde_runner import workspaces_service as service_module
    from varde_runner import worktrees

    class HangingProcess:
        returncode: int | None = None
        killed = False

        async def communicate(self):
            if not self.killed:
                await asyncio.sleep(1)
            return b"", b""

        def kill(self):
            self.killed = True
            self.returncode = -9

    async def scenario():
        monkeypatch.setattr(worktrees, "SUBPROCESS_TIMEOUT_SECONDS", 0.001)
        processes = []

        async def create_process(*args, **kwargs):
            process = HangingProcess()
            processes.append(process)
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", create_process)
        with pytest.raises(worktrees.CommandTimeoutError):
            await worktrees.run_git(tmp_path, "status")
        with pytest.raises(worktrees.CommandTimeoutError):
            await service_module._git_status(tmp_path, "status", env=None)
        with pytest.raises(worktrees.CommandTimeoutError):
            await service_module._stop_watcher(tmp_path)
        assert all(process.killed for process in processes)

        process = HangingProcess()
        with pytest.raises(worktrees.CommandTimeoutError):
            await worktrees.communicate_with_timeout(
                cast("asyncio.subprocess.Process", process), "git test"
            )
        assert process.killed

        async def timeout_common_dir(path, env):
            raise worktrees.CommandTimeoutError("git rev-parse timed out")

        monkeypatch.setattr(service_module, "_common_dir", timeout_common_dir)
        with pytest.raises(WorkspaceError) as error:
            await service_for(make_repo(tmp_path / "timeout-repo")).create(
                tmp_path / "timeout-repo", "timeout"
            )
        assert error.value.status == 504
        assert error.value.code == "command_timeout"

    asyncio.run(scenario())


def test_preflight_failure_post_remove_verification_and_watcher_best_effort(
    tmp_path, monkeypatch, caplog
):
    repo = make_repo(tmp_path / "repo")

    async def scenario():
        service = service_for(repo)
        target = Path((await service.create(repo, "preflight"))["path"])
        monkeypatch.setattr(
            "varde_runner.workspaces_service._preflight_admin", fail_preflight
        )
        with pytest.raises(WorkspaceError, match="writable"):
            await service.remove(repo, "preflight", discard=True)
        monkeypatch.undo()
        target = Path((await service.create(repo, "verify"))["path"])
        real_list = __import__(
            "varde_runner.workspaces_service", fromlist=["list_worktrees"]
        ).list_worktrees
        calls = 0

        async def lingering(root, **kwargs):
            nonlocal calls
            calls += 1
            result = await real_list(root, **kwargs)
            return result + ([{"worktree": str(target)}] if calls == 2 else [])

        monkeypatch.setattr("varde_runner.workspaces_service.list_worktrees", lingering)
        monkeypatch.setattr("varde_runner.workspaces_service._stop_watcher", noop)
        with pytest.raises(WorkspaceError, match="remains registered") as error:
            await service.remove(repo, "verify", discard=True)
        assert error.value.status == 500
        assert error.value.status == 500

    async def fail_preflight(path, env):
        raise WorkspaceError(409, "git admin directory is not writable")

    async def noop(path, env=None):
        return None

    asyncio.run(scenario())


def test_post_remove_branch_verification_failure_returns_500(tmp_path, monkeypatch):
    from varde_runner import workspaces_service as module

    repo = make_repo(tmp_path / "repo")

    async def noop(path, env=None):
        return None

    async def scenario():
        service = service_for(repo)
        target = Path((await service.create(repo, "branch-verify"))["path"])
        monkeypatch.setattr(module, "_stop_watcher", noop)
        real_status = module._git_status

        async def branch_still_exists(root, *args, **kwargs):
            if args[:2] == ("show-ref", "--verify"):
                return 0
            return await real_status(root, *args, **kwargs)

        monkeypatch.setattr(module, "_git_status", branch_still_exists)
        with pytest.raises(WorkspaceError, match="branch remains") as error:
            await service.remove(repo, "branch-verify", discard=True)
        assert error.value.status == 500
        assert not target.exists()

    asyncio.run(scenario())


def test_watcher_missing_binary_warns_and_receives_runner_environment(
    tmp_path, monkeypatch, caplog
):
    from varde_runner import workspaces_service as module

    seen = {}

    async def missing_binary(*args, **kwargs):
        seen.update(kwargs)
        raise FileNotFoundError("varde missing")

    async def scenario():
        env = {"PATH": "", "RUNNER_ENV": "present"}
        monkeypatch.setattr(module.asyncio, "create_subprocess_exec", missing_binary)
        await module._stop_watcher(tmp_path, env)
        assert seen["env"] == env
        assert "Could not stop watcher" in caplog.text

    asyncio.run(scenario())


def test_preflight_checks_admin_parent_writability(tmp_path, monkeypatch):
    from varde_runner import workspaces_service as module

    repo = make_repo(tmp_path / "repo")

    async def scenario():
        target = await add_worktree(repo, "parent", base="HEAD")
        monkeypatch.setattr(module.os, "access", lambda path, mode: False)
        with pytest.raises(WorkspaceError, match="writable"):
            await module._preflight_admin(target, None)
        git(repo, "worktree", "remove", str(target))
        git(repo, "branch", "-D", "worktree/parent")

    asyncio.run(scenario())


def test_per_repo_lock_serializes_create(tmp_path, monkeypatch):
    repo = make_repo(tmp_path / "repo")
    from varde_runner import workspaces_service as module

    async def scenario():
        service = service_for(repo)
        active = maximum = 0
        original_add = module.add_worktree

        async def slow_add(root, worktree_id, *, base, env=None):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.02)
            result = await original_add(root, worktree_id, base=base, env=env)
            active -= 1
            return result

        monkeypatch.setattr(module, "add_worktree", slow_add)
        await asyncio.gather(service.create(repo, "one"), service.create(repo, "two"))
        assert maximum == 1

    asyncio.run(scenario())
