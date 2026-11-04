"""Native workspace operations and their safety checks."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from varde_runner.worktrees import (
    BaseUnresolvedError,
    CommandTimeoutError,
    add_worktree,
    communicate_with_timeout,
    list_worktrees,
    remove_worktree,
    run_git,
    validate_worktree_id,
    worktree_branch,
    worktree_path,
)

logger = logging.getLogger(__name__)
_LIVE_EXCLUDED = {"archived", "completed", "failed"}


class WorkspaceError(Exception):
    def __init__(self, status: int, message: str, code: str = "refused"):
        super().__init__(message)
        self.status = status
        self.code = code


class WorkspacesService:
    def __init__(
        self,
        repos,
        env: dict[str, str] | None = None,
        get_store: Callable[[], Awaitable[Any]] | None = None,
    ):
        self.repos = tuple(Path(repo).expanduser().resolve() for repo in repos)
        self.env = env
        self.get_store = get_store
        self._locks: dict[Path, asyncio.Lock] = {}

    def _repo(self, repo: str | Path) -> Path:
        path = Path(repo).expanduser().resolve()
        if path not in self.repos:
            raise WorkspaceError(404, "repo is not configured", "repo_not_configured")
        return path

    def _lock(self, repo: Path) -> asyncio.Lock:
        return self._locks.setdefault(repo, asyncio.Lock())

    async def list(self) -> list[dict[str, Any]]:
        entries = []
        for repo in self.repos:
            try:
                root = Path(
                    await run_git(repo, "rev-parse", "--show-toplevel", env=self.env)
                ).resolve()
                rows = await list_worktrees(repo, env=self.env)
                for row in rows:
                    path = Path(row.get("worktree", "")).resolve()
                    if "prunable" in row or "bare" in row or not path.is_dir():
                        continue
                    is_repo = path == root
                    branch = row.get("branch", "").removeprefix("refs/heads/")
                    worktree_id = (
                        branch.removeprefix("worktree/")
                        if branch.startswith("worktree/")
                        else ""
                    )
                    entries.append(
                        {
                            "id": str(path),
                            "title": root.name
                            if is_repo
                            else f"{root.name} / {worktree_id or path.name}",
                            "cwd": str(path),
                            "repo": str(root),
                            "kind": "repo" if is_repo else "worktree",
                            "branch": branch,
                            "head": row.get("HEAD", ""),
                            "last_used": False,
                        }
                    )
            except (OSError, RuntimeError, ValueError) as exc:
                logger.warning("Could not list workspaces for %s: %s", repo, exc)
        return entries

    async def create(
        self,
        repo: str | Path,
        worktree_id: str,
        *,
        base: str | None = None,
        caller: str | Path | None = None,
    ) -> dict[str, Any]:
        try:
            return await self._create(repo, worktree_id, base=base, caller=caller)
        except CommandTimeoutError as exc:
            raise WorkspaceError(504, str(exc), "command_timeout") from exc

    async def _create(
        self,
        repo: str | Path,
        worktree_id: str,
        *,
        base: str | None = None,
        caller: str | Path | None = None,
    ) -> dict[str, Any]:
        root = self._repo(repo)
        try:
            validate_worktree_id(worktree_id)
        except ValueError as exc:
            raise WorkspaceError(422, str(exc), "bad_id") from exc
        caller_path = Path(caller).expanduser().resolve() if caller else root
        if await _common_dir(caller_path, self.env) != await _common_dir(
            root, self.env
        ):
            raise WorkspaceError(
                422, "caller must be a checkout of the configured repo", "bad_caller"
            )
        async with self._lock(root):
            path = await worktree_path(root, worktree_id, env=self.env)
            rows = await list_worktrees(root, env=self.env)
            branch = worktree_branch(worktree_id)
            branch_exists = (
                await _git_status(
                    root,
                    "show-ref",
                    "--verify",
                    "--quiet",
                    f"refs/heads/{branch}",
                    env=self.env,
                )
                == 0
            )
            if (
                path.exists()
                or branch_exists
                or any(row.get("branch") == f"refs/heads/{branch}" for row in rows)
            ):
                raise WorkspaceError(
                    409, "worktree path or branch already exists", "exists"
                )
            selected_base = base or await run_git(
                caller_path, "rev-parse", "HEAD", env=self.env
            )
            try:
                resolved = await run_git(
                    root,
                    "rev-parse",
                    "--verify",
                    "--end-of-options",
                    f"{selected_base}^{{commit}}",
                    env=self.env,
                )
                created_path = await add_worktree(
                    root, worktree_id, base=resolved, env=self.env
                )
            except CommandTimeoutError:
                raise
            except (RuntimeError, BaseUnresolvedError) as exc:
                raise WorkspaceError(
                    422, "base does not resolve to a commit", "base_unresolved"
                ) from exc
            if self.get_store:
                await _upsert_workspace_best_effort(
                    self.get_store,
                    str(created_path),
                    repo_root=str(root),
                    cwd=str(created_path),
                    worktree=str(created_path),
                    branch=branch,
                )
            return {
                "id": str(created_path),
                "path": str(created_path),
                "branch": branch,
                "base": resolved,
                "created": True,
            }

    async def remove(
        self,
        repo: str | Path,
        worktree_id: str,
        *,
        caller: str | Path | None = None,
        discard: bool = False,
    ) -> dict[str, Any]:
        try:
            return await self._remove(repo, worktree_id, caller=caller, discard=discard)
        except CommandTimeoutError as exc:
            raise WorkspaceError(504, str(exc), "command_timeout") from exc

    async def _remove(
        self,
        repo: str | Path,
        worktree_id: str,
        *,
        caller: str | Path | None = None,
        discard: bool = False,
    ) -> dict[str, Any]:
        root = self._repo(repo)
        if caller is None and not discard:
            raise WorkspaceError(
                422, "caller is required unless discard=true", "bad_caller"
            )
        caller_path = Path(caller).expanduser().resolve() if caller else None
        if caller_path and await _common_dir(
            caller_path, self.env
        ) != await _common_dir(root, self.env):
            raise WorkspaceError(
                422, "caller must be a checkout of the configured repo", "bad_caller"
            )
        try:
            branch = worktree_branch(worktree_id)
        except ValueError as exc:
            raise WorkspaceError(422, str(exc), "bad_id") from exc
        async with self._lock(root):
            rows = await list_worktrees(root, env=self.env)
            matches = [
                row for row in rows if row.get("branch") == f"refs/heads/{branch}"
            ]
            if len(matches) != 1:
                raise WorkspaceError(
                    404 if not matches else 409,
                    "no unique registered worktree for branch",
                    "not_found" if not matches else "ambiguous",
                )
            path = Path(matches[0]["worktree"]).resolve()
            expected = await worktree_path(root, worktree_id, env=self.env)
            if (
                not path.is_relative_to(expected.parent)
                or path.parent != expected.parent
            ):
                raise WorkspaceError(
                    404,
                    "worktree is outside the native worktree directory",
                    "not_found",
                )
            if caller_path and caller_path.is_relative_to(path):
                raise WorkspaceError(
                    409, "caller is inside the target worktree", "caller_inside"
                )
            oid = matches[0].get("HEAD", "")
            ignored = []
            try:
                status = await run_git(
                    path, "status", "--porcelain", "--ignored=matching", env=self.env
                )
                ignored = [
                    line[3:] for line in status.splitlines() if line.startswith("!! ")
                ]
            except RuntimeError:
                if not discard:
                    raise
            if not discard:
                dirty = await run_git(
                    path, "status", "--porcelain", "--untracked-files=all", env=self.env
                )
                if dirty:
                    raise WorkspaceError(409, "worktree has uncommitted files", "dirty")
                ancestor = await _git_status(
                    root,
                    "merge-base",
                    "--is-ancestor",
                    oid,
                    "HEAD",
                    env=self.env,
                    cwd=caller_path,
                )
                if ancestor != 0:
                    raise WorkspaceError(
                        409, "branch is not merged into caller HEAD", "unmerged"
                    )
            if await self._has_live_session(path):
                raise WorkspaceError(
                    409, "live runner session uses this worktree", "live_session"
                )
            await _preflight_admin(path, self.env)
            await _stop_watcher(path, self.env)
            await remove_worktree(root, path, force=discard, env=self.env)
            remaining = await list_worktrees(root, env=self.env)
            if any(
                Path(row.get("worktree", "")).resolve() == path for row in remaining
            ):
                raise WorkspaceError(
                    500, "worktree remains registered after removal", "verify_failed"
                )
            await run_git(
                root, "update-ref", "-d", f"refs/heads/{branch}", oid, env=self.env
            )
            if (
                await _git_status(
                    root,
                    "show-ref",
                    "--verify",
                    "--quiet",
                    f"refs/heads/{branch}",
                    env=self.env,
                )
                == 0
            ):
                raise WorkspaceError(
                    500, "branch remains after removal", "verify_failed"
                )
            if self.get_store:
                await _upsert_workspace_best_effort(
                    self.get_store,
                    str(path),
                    repo_root=str(root),
                    cwd=str(path),
                    worktree=str(path),
                    branch=branch,
                    archived_at=datetime.now(UTC).isoformat(),
                )
            return {"removed": True, "branch": branch, "ignored_removed": ignored}

    async def _has_live_session(self, path: Path) -> bool:
        if not self.get_store:
            return False
        store = await self.get_store()
        for session in store.sessions():
            if session.get("lifecycle") in _LIVE_EXCLUDED:
                continue
            workspace = str(session.get("workspace_id") or "")
            record = store.get_workspace(workspace) if workspace else None
            candidate = Path(record["cwd"] if record else workspace).expanduser()
            try:
                candidate = candidate.resolve()
                if candidate == path or candidate.is_relative_to(path):
                    return True
            except OSError, RuntimeError:
                continue
        return False


async def _common_dir(path: Path, env) -> str:
    try:
        return await run_git(
            path, "rev-parse", "--path-format=absolute", "--git-common-dir", env=env
        )
    except CommandTimeoutError:
        raise
    except RuntimeError as exc:
        raise WorkspaceError(422, "caller is not a git checkout", "bad_caller") from exc


async def _git_status(repo, *args, env, cwd=None) -> int:
    proc = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(cwd or repo),
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    await communicate_with_timeout(proc, f"git {' '.join(args)}")
    if proc.returncode is None:
        raise RuntimeError("git process did not exit")
    return proc.returncode


async def _preflight_admin(path: Path, env) -> None:
    try:
        admin = Path(
            await run_git(
                path, "rev-parse", "--path-format=absolute", "--git-dir", env=env
            )
        )
        if not os.access(admin.parent, os.W_OK):
            raise WorkspaceError(
                409, "git admin directory is not writable", "preflight"
            )
        fd, probe = tempfile.mkstemp(prefix=".varde-worktree-remove-probe-", dir=admin)
        os.close(fd)
        os.unlink(probe)
    except CommandTimeoutError:
        raise
    except (OSError, RuntimeError) as exc:
        raise WorkspaceError(
            409, "git admin directory is not writable", "preflight"
        ) from exc


async def _stop_watcher(path: Path, env: dict[str, str] | None = None) -> None:
    try:
        proc = await asyncio.create_subprocess_exec(
            "varde",
            "setup",
            "watch",
            "--stop",
            "--remove-index",
            "--repo",
            str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except OSError as exc:
        logger.warning("Could not stop watcher for %s: %s", path, exc)
        return
    _, stderr = await communicate_with_timeout(proc, "varde setup watch --stop")
    if proc.returncode:
        logger.warning(
            "Could not stop watcher for %s: %s", path, stderr.decode(errors="replace")
        )


async def _upsert_workspace_best_effort(
    get_store: Callable[[], Awaitable[Any]], workspace_id: str, **values: Any
) -> None:
    try:
        store = await get_store()
        store.upsert_workspace(workspace_id, **values)
    except Exception as exc:  # noqa: BLE001 - Git has already changed state.
        logger.warning(
            "Could not update workspace registry for %s: %s", workspace_id, exc
        )
