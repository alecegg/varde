from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest
from varde_runner.worktrees import (
    BaseUnresolvedError,
    add_worktree,
    ensure_exclude,
    list_worktrees,
    parse_worktree_porcelain,
    remove_worktree,
    validate_worktree_id,
    worktree_branch,
    worktree_path,
)


def test_worktree_id_and_derived_values(tmp_path):
    assert validate_worktree_id("task-1.a_2") == "task-1.a_2"
    for invalid in (
        "../escape",
        "-option",
        "a.lock",
        "a..b",
        "@",
        "@{",
        ".leading",
        "trailing.",
        "with/slash",
    ):
        with pytest.raises(ValueError, match=".lock.*@"):
            validate_worktree_id(invalid)
    assert worktree_branch("task-1") == "worktree/task-1"


def test_worktree_path_uses_common_repo_root(repo, tmp_path):
    async def scenario():
        subdir = repo / "subdir"
        subdir.mkdir()
        linked = tmp_path / "linked"
        await git(repo, "worktree", "add", "--detach", str(linked), "HEAD")
        assert await worktree_path(subdir, "from-subdir") == (
            repo / ".varde/worktrees/from-subdir"
        )
        assert await worktree_path(linked, "from-linked") == (
            repo / ".varde/worktrees/from-linked"
        )
        await git(repo, "worktree", "remove", str(linked))

    asyncio.run(scenario())


def test_parse_worktree_porcelain():
    rows = parse_worktree_porcelain(
        "worktree /repo\nHEAD abc\nbranch refs/heads/main\n\n"
        "worktree /repo/.varde/worktrees/task\nHEAD def\n"
        "branch refs/heads/worktree/task\n\n"
        "worktree /gone\nHEAD 123\nprunable gitdir file missing\n"
    )
    assert rows == [
        {"worktree": "/repo", "HEAD": "abc", "branch": "refs/heads/main"},
        {
            "worktree": "/repo/.varde/worktrees/task",
            "HEAD": "def",
            "branch": "refs/heads/worktree/task",
        },
        {"worktree": "/gone", "HEAD": "123", "prunable": "gitdir file missing"},
    ]


async def git(repo, *args):
    process = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(repo),
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await process.communicate()
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode, args, out, err)
    return out.decode().strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(  # noqa: S603 - fixed git executable and test arguments
        ["git", "-C", str(root), "init", "-b", "main"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603 - fixed git executable and test arguments
        ["git", "-C", str(root), "config", "user.email", "test@example.com"],  # noqa: S607
        check=True,
    )
    subprocess.run(  # noqa: S603 - fixed git executable and test arguments
        ["git", "-C", str(root), "config", "user.name", "Test"],  # noqa: S607
        check=True,
    )
    (root / "file").write_text("initial")
    subprocess.run(  # noqa: S603 - fixed git executable and test arguments
        ["git", "-C", str(root), "add", "file"],  # noqa: S607
        check=True,
    )
    subprocess.run(  # noqa: S603 - fixed git executable and test arguments
        ["git", "-C", str(root), "commit", "-m", "initial"],  # noqa: S607
        check=True,
        capture_output=True,
    )
    return root


def test_create_list_and_remove_worktree(repo):
    async def scenario():
        path = await add_worktree(repo, "alpha", base="HEAD")
        assert path == await worktree_path(repo, "alpha")
        rows = await list_worktrees(repo)
        assert any(
            row["worktree"] == str(path)
            and row["branch"] == "refs/heads/worktree/alpha"
            for row in rows
        )
        await remove_worktree(repo, path)
        rows = await list_worktrees(repo)
        assert not any(row["worktree"] == str(path) for row in rows)
        assert "refs/heads/worktree/alpha" in await git(
            repo, "show-ref", "--verify", "refs/heads/worktree/alpha"
        )
        dirty_path = await add_worktree(repo, "force-remove", base="HEAD")
        (dirty_path / "untracked").write_text("dirty")
        await remove_worktree(repo, dirty_path, force=True)

    asyncio.run(scenario())


def test_ensure_exclude_adds_common_git_exclude_once(repo):
    async def scenario():
        common_dir = await git(
            repo, "rev-parse", "--path-format=absolute", "--git-common-dir"
        )
        common = Path(common_dir)
        exclude_path = common / "info/exclude"
        exclude_path.parent.mkdir(parents=True, exist_ok=True)
        exclude_path.write_text("existing-without-newline")
        await ensure_exclude(repo)
        await ensure_exclude(repo)
        return exclude_path

    exclude = asyncio.run(scenario())
    assert exclude.read_text() == "existing-without-newline\n/.varde/\n"


def test_flag_like_base_is_rejected_before_add(repo):
    async def scenario():
        with pytest.raises(BaseUnresolvedError):
            await add_worktree(repo, "flag-base", base="--help")
        assert not (repo / ".varde/worktrees/flag-base").exists()
        assert "refs/heads/worktree/flag-base" not in await git(repo, "show-ref")

    asyncio.run(scenario())
