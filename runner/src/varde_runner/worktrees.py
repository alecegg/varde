"""Low-level asynchronous git worktree operations."""

from __future__ import annotations

import asyncio
import contextlib
import re
from pathlib import Path

WORKTREE_ROOT = ".varde/worktrees"
SUBPROCESS_TIMEOUT_SECONDS = 30
_WORKTREE_ID = re.compile(r"[A-Za-z0-9._-]+\Z")


class CommandTimeoutError(RuntimeError):
    """A git or watcher subprocess exceeded its time limit."""


async def communicate_with_timeout(
    process: asyncio.subprocess.Process, command: str
) -> tuple[bytes, bytes]:
    try:
        return await asyncio.wait_for(
            process.communicate(), timeout=SUBPROCESS_TIMEOUT_SECONDS
        )
    except TimeoutError as exc:
        if process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
        await process.communicate()
        raise CommandTimeoutError(f"{command} timed out") from exc


def validate_worktree_id(value: str) -> str:
    """Validate an id that forms an unambiguous ``worktree/<id>`` branch."""
    if (
        not _WORKTREE_ID.fullmatch(value)
        or value.startswith(("-", "."))
        or value.endswith((".", ".lock"))
        or ".." in value
        or "@{" in value
        or value == "@"
    ):
        raise ValueError(
            "worktree id must use letters, numbers, dot, underscore, or hyphen; "
            "it cannot start with dot or hyphen, end with dot or .lock, or contain "
            ".. or @{"
        )
    return value


async def worktree_path(
    repo: str | Path, worktree_id: str, *, env: dict[str, str] | None = None
) -> Path:
    validate_worktree_id(worktree_id)
    common_dir = Path(
        await run_git(
            repo,
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
            env=env,
        )
    )
    return common_dir.parent / WORKTREE_ROOT / worktree_id


def worktree_branch(worktree_id: str) -> str:
    return f"worktree/{validate_worktree_id(worktree_id)}"


def parse_worktree_porcelain(output: str) -> list[dict[str, str]]:
    """Parse records from ``git worktree list --porcelain``."""
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in (*output.splitlines(), ""):
        if not line:
            if current:
                records.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        current[key] = value
    return records


async def run_git(
    repo: str | Path,
    *args: str,
    env: dict[str, str] | None = None,
) -> str:
    """Run git asynchronously in a checkout and return stdout as text."""
    process = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(Path(repo).expanduser().resolve()),
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await communicate_with_timeout(process, f"git {' '.join(args)}")
    if process.returncode:
        raise RuntimeError(
            f"git {' '.join(args)} failed ({process.returncode}): "
            f"{stderr.decode(errors='replace').strip()}"
        )
    return stdout.decode(errors="replace").strip()


async def list_worktrees(
    repo: str | Path, *, env: dict[str, str] | None = None
) -> list[dict[str, str]]:
    output = await run_git(repo, "worktree", "list", "--porcelain", env=env)
    return parse_worktree_porcelain(output)


async def add_worktree(
    repo: str | Path,
    worktree_id: str,
    *,
    base: str,
    env: dict[str, str] | None = None,
) -> Path:
    path = await worktree_path(repo, worktree_id, env=env)
    try:
        commit = await run_git(
            repo, "rev-parse", "--verify", f"{base}^{{commit}}", env=env
        )
    except CommandTimeoutError:
        raise
    except RuntimeError as exc:
        raise BaseUnresolvedError(
            f"base {base!r} does not resolve to a commit"
        ) from exc
    path.parent.mkdir(parents=True, exist_ok=True)
    await ensure_exclude(repo, env=env)
    await run_git(
        repo,
        "worktree",
        "add",
        "-b",
        worktree_branch(worktree_id),
        "--",
        str(path),
        commit,
        env=env,
    )
    return path


async def remove_worktree(
    repo: str | Path,
    path: str | Path,
    *,
    force: bool = False,
    env: dict[str, str] | None = None,
) -> None:
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(Path(path).expanduser().resolve()))
    await run_git(repo, *args, env=env)


async def ensure_exclude(
    repo: str | Path, *, env: dict[str, str] | None = None
) -> Path:
    common_dir = Path(
        await run_git(
            repo,
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
            env=env,
        )
    )
    exclude = common_dir / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text() if exclude.exists() else ""
    if "/.varde/" not in existing.splitlines():
        with exclude.open("a") as stream:
            if existing and not existing.endswith("\n"):
                stream.write("\n")
            stream.write("/.varde/\n")
    return exclude


class BaseUnresolvedError(ValueError):
    """Raised when a worktree base cannot be resolved to a commit."""
