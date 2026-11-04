import os
import shutil
import subprocess
import time
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
HOOKS = REPO / ".githooks"
PYRIGHT = REPO / ".venv" / "bin" / "pyright"
_REPO_TEMPLATE: list[Path] = []


def _run(
    args: list[str], cwd: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - Helper invokes Git with test-controlled arguments in temporary repositories.
        args, cwd=cwd, env=env, text=True, capture_output=True, check=False
    )


def _environment(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.pop("VIRTUAL_ENV", None)
    for name in ("HOME", "XDG_CONFIG_HOME", "VARDE_CONFIG_DIR", "XDG_DATA_HOME"):
        value = tmp_path / name.lower()
        value.mkdir()
        env[name] = str(value)
    env["VARDE_HOOKS_TOOL_PREFIX"] = str(tmp_path / "tool")
    env["UV_CACHE_DIR"] = os.environ.get(
        "UV_CACHE_DIR", str(Path.home() / ".cache" / "uv")
    )
    varde = tmp_path / "varde-bin" / "varde"
    varde.parent.mkdir(exist_ok=True)
    varde.write_text(
        "#!/bin/sh\n"
        "[ \"$1 $2\" = 'plan merge-gate' ] || exit 0\n"
        'printf \'%s\\n\' "$*" >> "$VARDE_MERGE_GATE_LOG"\n'
        'exit "${VARDE_MERGE_GATE_STATUS:-0}"\n'
    )
    env["VARDE_MERGE_GATE_LOG"] = str(tmp_path / "merge-gate-calls")
    varde.chmod(0o755)
    env["PATH"] = f"{varde.parent}{os.pathsep}{env['PATH']}"
    return env


def _write_tool_wrapper(path: Path) -> None:
    path.write_text(f'#!/bin/sh\ntool=$1\nshift\nexec "{REPO}/.venv/bin/$tool" "$@"\n')
    path.chmod(0o755)


@pytest.fixture(scope="module", autouse=True)
def _prepare_repo_template(tmp_path_factory: pytest.TempPathFactory) -> None:
    root = tmp_path_factory.mktemp("git-hook-template") / "repo"
    root.mkdir()
    (root / ".venv").mkdir()
    shutil.copytree(HOOKS, root / ".githooks")
    (root / "justfile").write_text("default:\n\t@true\n")
    (root / "pyproject.toml").write_text(
        '[tool.ruff]\nline-length = 88\nexclude = ["tests/fixtures/**"]\n'
    )
    (root / "pyrightconfig.json").write_text('{"include": ["src"]}\n')
    env = _environment(root.parent)
    _write_tool_wrapper(root.parent / "tool")
    _run(["git", "init", "-q"], root, env)
    _run(["git", "config", "user.email", "hooks@example.test"], root, env)
    _run(["git", "config", "user.name", "Hooks Test"], root, env)
    (root / "README").write_text("test repo\n")
    _run(
        [
            "git",
            "add",
            "README",
            ".githooks",
            "justfile",
            "pyproject.toml",
            "pyrightconfig.json",
        ],
        root,
        env,
    )
    _run(["git", "commit", "-qm", "initial"], root, env)
    _REPO_TEMPLATE.append(root)


def _repo(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    if not _REPO_TEMPLATE:
        raise AssertionError("Git hook repository template was not initialized")
    root = tmp_path / "repo"
    shutil.copytree(_REPO_TEMPLATE[0], root)
    env = _environment(tmp_path)
    _write_tool_wrapper(tmp_path / "tool")
    return root, env


def _stage(root: Path, env: dict[str, str], relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    _run(["git", "add", relative], root, env)


def _hook(
    root: Path, env: dict[str, str], name: str, *args: str
) -> subprocess.CompletedProcess[str]:
    return _run([str(root / ".githooks" / name), *args], root, env)


def _pyright_stub(root: Path, env: dict[str, str], *, status: int = 0) -> Path:
    executable = root.parent / "tool"
    marker = root.parent / "pyright-ran"
    executable.write_text(f'#!/bin/sh\n: > "$PYRIGHT_MARKER"\nexit {status}\n')
    executable.chmod(0o755)
    env["PYRIGHT_MARKER"] = str(marker)
    return marker


def _ff_merge(root: Path, env: dict[str, str], *, non_ff: bool = False) -> None:
    target = _run(["git", "branch", "--show-current"], root, env).stdout.strip()
    _run(["git", "config", "core.hooksPath", ".githooks"], root, env)
    _run(["git", "switch", "-qc", "feature"], root, env)
    (root / "feature.txt").write_text("feature\n")
    _run(["git", "add", "feature.txt"], root, env)
    commit = _run(["git", "commit", "--no-verify", "-qm", "feature"], root, env)
    assert commit.returncode == 0, commit.stderr
    _run(["git", "switch", "-q", target], root, env)
    if non_ff:
        (root / "target.txt").write_text("target\n")
        _run(["git", "add", "target.txt"], root, env)
        commit = _run(["git", "commit", "--no-verify", "-qm", "target"], root, env)
        assert commit.returncode == 0, commit.stderr
        merge = _run(["git", "merge", "--no-ff", "feature", "-m", "merge"], root, env)
    else:
        merge = _run(["git", "merge", "feature"], root, env)
    assert merge.returncode == 0, merge.stdout + merge.stderr


def test_pre_commit_blocks_ruff_error(tmp_path: Path) -> None:
    root, env = _repo(tmp_path)
    _stage(root, env, "bad.py", "import os\n")

    result = _hook(root, env, "pre-commit")

    assert result.returncode != 0
    assert "F401" in result.stdout + result.stderr


def test_pre_commit_blocks_bad_format(tmp_path: Path) -> None:
    root, env = _repo(tmp_path)
    _stage(root, env, "bad.py", "value =  [1,2]\n")

    result = _hook(root, env, "pre-commit")

    assert result.returncode != 0
    assert "File would be reformatted" in result.stdout + result.stderr


def test_pre_commit_allows_clean_file(tmp_path: Path) -> None:
    root, env = _repo(tmp_path)
    _stage(root, env, "good.py", "value = [1, 2]\n")

    result = _hook(root, env, "pre-commit")

    assert result.returncode == 0


def test_pre_commit_skips_ruff_when_uv_cannot_provide_it(tmp_path: Path) -> None:
    root, env = _repo(tmp_path)
    _stage(root, env, "good.py", "value = [1, 2]\n")
    (tmp_path / "tool").write_text(
        "#!/bin/sh\n"
        'if [ "$1" = ruff ] && [ "$2" = --version ]; then\n'
        '  echo "Failed to spawn: ruff" >&2\n'
        "  exit 2\n"
        "fi\n"
        "exit 0\n"
    )

    result = _hook(root, env, "pre-commit")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Skipping ruff" in result.stdout + result.stderr


def test_pre_commit_uses_configured_runner_when_ruff_is_not_on_path(
    tmp_path: Path,
) -> None:
    root, env = _repo(tmp_path)
    _stage(root, env, "bad.py", "import os\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text('#!/bin/sh\necho "Failed to spawn: ruff" >&2\nexit 2\n')
    uv.chmod(0o755)
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"

    result = _hook(root, env, "pre-commit")

    assert result.returncode != 0
    assert "F401" in result.stdout + result.stderr


def test_pre_commit_skips_ruff_when_venv_setup_fails(tmp_path: Path) -> None:
    root, env = _repo(tmp_path)
    _stage(root, env, "good.py", "value = [1, 2]\n")
    shutil.rmtree(root / ".venv")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    uv = bin_dir / "uv"
    uv.write_text('#!/bin/sh\necho "offline sync failed" >&2\nexit 1\n')
    uv.chmod(0o755)
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    ruff_marker = tmp_path / "ruff-ran"
    tool = tmp_path / "tool"
    tool.write_text(f'#!/bin/sh\nprintf ran > "{ruff_marker}"\nexit 1\n')
    tool.chmod(0o755)

    result = _hook(root, env, "pre-commit")

    assert result.returncode == 0, result.stdout + result.stderr
    output = result.stdout + result.stderr
    assert "Hook setup failed" in output
    assert "hook sandbox cannot provide its offline environment" in output
    assert not ruff_marker.exists()


def test_commit_ignores_unstaged_ruff_error(tmp_path: Path) -> None:
    root, env = _repo(tmp_path)
    _stage(root, env, "good.py", "value = [1, 2]\n")
    (root / "unstaged_bad.py").write_text("import os\n")
    _run(["git", "config", "core.hooksPath", ".githooks"], root, env)

    result = _run(["git", "commit", "-m", "clean staged file"], root, env)

    assert result.returncode == 0, result.stdout + result.stderr


def test_pre_commit_excludes_fixtures(tmp_path: Path) -> None:
    root, env = _repo(tmp_path)
    _stage(root, env, "tests/fixtures/bad.py", "import os\n")

    result = _hook(root, env, "pre-commit")

    assert result.returncode == 0


@pytest.mark.skipif(
    not PYRIGHT.exists(), reason="local pyright executable is unavailable"
)
def test_pyright_runs_only_at_configured_stage(tmp_path: Path) -> None:
    root, env = _repo(tmp_path)
    _stage(root, env, "src/bad.py", 'value: int = "wrong"\n')
    (root / ".githooks" / "pyright-stage").write_text("pre-merge-commit pre-push\n")

    commit_stage = _hook(root, env, "pre-commit")
    merge_stage = _hook(root, env, "pre-merge-commit")
    push_stage = _hook(root, env, "pre-push")
    (root / ".githooks" / "pyright-stage").write_text("pre-commit\n")
    switched_stage = _hook(root, env, "pre-commit")

    assert commit_stage.returncode == 0
    assert merge_stage.returncode != 0
    assert push_stage.returncode != 0
    assert switched_stage.returncode != 0
    assert "error" in push_stage.stdout + push_stage.stderr


def test_hook_works_from_git_worktree(tmp_path: Path) -> None:
    root, env = _repo(tmp_path)
    worktree = tmp_path / "linked-worktree"
    result = _run(["git", "worktree", "add", "-qb", "linked", str(worktree)], root, env)
    assert result.returncode == 0
    (worktree / ".venv").mkdir()
    _stage(worktree, env, "good.py", "value = [1, 2]\n")

    _run(["git", "config", "core.hooksPath", ".githooks"], worktree, env)
    hook_result = _run(["git", "commit", "-m", "clean"], worktree, env)

    assert hook_result.returncode == 0


@pytest.mark.skipif(
    not PYRIGHT.exists(), reason="local pyright executable is unavailable"
)
def test_pre_merge_commit_hook_runs_from_git_worktree(tmp_path: Path) -> None:
    root, env = _repo(tmp_path)
    worktree = tmp_path / "merge-worktree"
    result = _run(
        ["git", "worktree", "add", "-qb", "merge-target", str(worktree)], root, env
    )
    assert result.returncode == 0, result.stderr
    (worktree / ".venv").mkdir()
    (worktree / ".githooks" / "pyright-stage").write_text("pre-merge-commit pre-push\n")
    marker = tmp_path / "pre-merge-ran"
    tracked_hook = worktree / ".githooks" / "pre-merge-commit"
    tracked_hook.write_text(
        tracked_hook.read_text().replace(
            "run_pyright_at_stage pre-merge-commit",
            f'printf ran > "{marker}"\nrun_pyright_at_stage pre-merge-commit',
        )
    )
    _run(["git", "config", "core.hooksPath", ".githooks"], worktree, env)

    _run(["git", "switch", "-qc", "merge-feature"], worktree, env)
    (worktree / "src").mkdir()
    (worktree / "src" / "bad.py").write_text('value: int = "wrong"\n')
    _run(["git", "add", "src/bad.py"], worktree, env)
    feature_commit = _run(
        ["git", "commit", "--no-verify", "-m", "type error"], worktree, env
    )
    assert feature_commit.returncode == 0, feature_commit.stderr
    _run(["git", "switch", "-q", "merge-target"], worktree, env)
    (worktree / "clean.txt").write_text("target change\n")
    _run(["git", "add", "clean.txt"], worktree, env)
    target_commit = _run(
        ["git", "commit", "--no-verify", "-m", "target change"], worktree, env
    )
    assert target_commit.returncode == 0, target_commit.stderr

    blocked_merge = _run(
        ["git", "merge", "--no-ff", "merge-feature", "-m", "bad merge"],
        worktree,
        env,
    )

    assert blocked_merge.returncode != 0
    assert marker.read_text() == "ran"
    assert "error" in blocked_merge.stdout + blocked_merge.stderr

    aborted_merge = _run(["git", "merge", "--abort"], worktree, env)
    assert aborted_merge.returncode == 0, aborted_merge.stderr
    _run(["git", "switch", "-q", "merge-feature"], worktree, env)
    (worktree / "src" / "bad.py").write_text("value: int = 1\n")
    _run(["git", "add", "src/bad.py"], worktree, env)
    fixed_feature = _run(
        ["git", "commit", "--no-verify", "--amend", "-m", "clean feature"],
        worktree,
        env,
    )
    assert fixed_feature.returncode == 0, fixed_feature.stderr
    _run(["git", "switch", "-q", "merge-target"], worktree, env)
    marker.unlink()

    clean_merge = _run(
        ["git", "merge", "--no-ff", "merge-feature", "-m", "clean merge"],
        worktree,
        env,
    )

    assert clean_merge.returncode == 0, clean_merge.stdout + clean_merge.stderr
    assert marker.read_text() == "ran"


def test_fast_forward_merge_does_not_run_pre_merge_commit(tmp_path: Path) -> None:
    root, env = _repo(tmp_path)
    worktree = tmp_path / "ff-worktree"
    result = _run(
        ["git", "worktree", "add", "-qb", "ff-target", str(worktree)], root, env
    )
    assert result.returncode == 0, result.stderr
    marker = tmp_path / "pre-merge-ran"
    (worktree / ".githooks" / "pre-merge-commit").write_text(
        f'#!/bin/sh\nprintf ran > "{marker}"\n'
    )
    (worktree / ".githooks" / "pre-merge-commit").chmod(0o755)
    _run(["git", "config", "core.hooksPath", ".githooks"], worktree, env)
    _run(["git", "switch", "-qc", "ff-feature"], worktree, env)
    (worktree / "feature.txt").write_text("feature\n")
    _run(["git", "add", "feature.txt"], worktree, env)
    feature_commit = _run(
        ["git", "commit", "--no-verify", "-m", "feature"], worktree, env
    )
    assert feature_commit.returncode == 0, feature_commit.stderr
    _run(["git", "switch", "-q", "ff-target"], worktree, env)

    merge = _run(["git", "merge", "ff-feature"], worktree, env)

    assert merge.returncode == 0, merge.stdout + merge.stderr
    assert not marker.exists()


def test_post_merge_pyright_passes_after_fast_forward(tmp_path: Path) -> None:
    root, env = _repo(tmp_path)
    marker = _pyright_stub(root, env)
    (root / ".githooks" / "pyright-stage").write_text("pre-merge-commit\n")

    _ff_merge(root, env)
    assert marker.exists()
    result = _hook(root, env, "post-merge", "0")

    assert result.returncode == 0, result.stdout + result.stderr
    assert marker.exists()


def test_post_merge_pyright_error_fails_after_fast_forward(tmp_path: Path) -> None:
    root, env = _repo(tmp_path)
    marker = _pyright_stub(root, env, status=1)
    (root / ".githooks" / "pyright-stage").write_text("pre-merge-commit\n")

    _ff_merge(root, env)
    assert marker.exists()
    result = _hook(root, env, "post-merge", "0")

    assert result.returncode != 0
    assert "Post-merge pyright check failed" in result.stderr
    assert marker.exists()


def test_post_merge_runs_after_fast_forward_to_merge_commit_tip(
    tmp_path: Path,
) -> None:
    root, env = _repo(tmp_path)
    marker = _pyright_stub(root, env, status=1)
    target = _run(["git", "branch", "--show-current"], root, env).stdout.strip()
    (root / ".githooks" / "pyright-stage").write_text("pre-push\n")
    _run(["git", "config", "core.hooksPath", ".githooks"], root, env)
    _run(["git", "switch", "-qc", "feature"], root, env)
    (root / "feature.txt").write_text("feature\n")
    _run(["git", "add", "feature.txt"], root, env)
    feature = _run(["git", "commit", "--no-verify", "-qm", "feature"], root, env)
    assert feature.returncode == 0, feature.stderr
    _run(["git", "switch", "-qc", "side"], root, env)
    (root / "side.txt").write_text("side\n")
    _run(["git", "add", "side.txt"], root, env)
    side = _run(["git", "commit", "--no-verify", "-qm", "side"], root, env)
    assert side.returncode == 0, side.stderr
    _run(["git", "switch", "-q", "feature"], root, env)
    merge = _run(["git", "merge", "--no-ff", "side", "-m", "merge tip"], root, env)
    assert merge.returncode == 0, merge.stdout + merge.stderr
    _run(["git", "switch", "-q", target], root, env)
    (root / ".githooks" / "pyright-stage").write_text("pre-merge-commit\n")

    ff = _run(["git", "merge", "feature"], root, env)
    assert marker.exists()
    result = _hook(root, env, "post-merge", "0")

    assert "Fast-forward" in ff.stdout
    assert result.returncode != 0
    assert marker.exists()


def test_post_merge_skips_non_fast_forward_merge(tmp_path: Path) -> None:
    root, env = _repo(tmp_path)
    marker = _pyright_stub(root, env, status=1)
    (root / ".githooks" / "pyright-stage").write_text("pre-push\n")

    _ff_merge(root, env, non_ff=True)
    (root / ".githooks" / "pyright-stage").write_text("pre-merge-commit\n")
    result = _hook(root, env, "post-merge", "0")

    assert result.returncode == 0, result.stdout + result.stderr
    assert not marker.exists()


def test_post_merge_skips_squash_merge(tmp_path: Path) -> None:
    root, env = _repo(tmp_path)
    marker = _pyright_stub(root, env, status=1)
    (root / ".githooks" / "pyright-stage").write_text("pre-merge-commit\n")

    result = _hook(root, env, "post-merge", "1")

    assert result.returncode == 0, result.stdout + result.stderr
    assert not marker.exists()


def test_post_merge_skips_when_stage_is_not_configured(tmp_path: Path) -> None:
    root, env = _repo(tmp_path)
    marker = _pyright_stub(root, env, status=1)
    (root / ".githooks" / "pyright-stage").write_text("pre-push\n")

    result = _hook(root, env, "post-merge", "0")

    assert result.returncode == 0, result.stdout + result.stderr
    assert not marker.exists()


def test_install_sets_repo_local_hook_path(tmp_path: Path) -> None:
    root, env = _repo(tmp_path)
    result = _run([str(root / ".githooks" / "install")], root, env)

    assert result.returncode == 0
    assert (
        _run(
            ["git", "config", "--local", "--get", "core.hooksPath"], root, env
        ).stdout.strip()
        == ".githooks"
    )


def test_git_push_runs_pre_push_hook(tmp_path: Path) -> None:
    root, env = _repo(tmp_path)
    bare = tmp_path / "remote.git"
    assert _run(["git", "init", "--bare", "-q", str(bare)], root, env).returncode == 0
    assert (
        _run(["git", "remote", "add", "origin", str(bare)], root, env).returncode == 0
    )
    _run(["git", "config", "core.hooksPath", ".githooks"], root, env)
    (root / "src").mkdir()
    (root / "src" / "bad.py").write_text('value: int = "wrong"\n')
    _run(["git", "add", "src/bad.py"], root, env)
    assert _run(["git", "commit", "-m", "bad typing"], root, env).returncode == 0
    (root / ".githooks" / "pyright-stage").write_text("pre-push\n")

    result = _run(["git", "push", "origin", "HEAD"], root, env)

    assert result.returncode != 0
    assert "error" in result.stdout + result.stderr


@pytest.mark.parametrize("hook", ["pre-commit", "pre-merge-commit", "pre-push"])
def test_invalid_pyright_stage_fails_clearly(tmp_path: Path, hook: str) -> None:
    root, env = _repo(tmp_path)
    (root / ".githooks" / "pyright-stage").write_text("precommit\n")

    result = _hook(root, env, hook)

    assert result.returncode != 0
    assert "Invalid .githooks/pyright-stage" in result.stderr


def test_hook_exits_cleanly_without_repo_markers(tmp_path: Path) -> None:
    root = tmp_path / "plain-repo"
    root.mkdir()
    env = _environment(tmp_path)
    _write_tool_wrapper(tmp_path / "tool")
    _run(["git", "init", "-q"], root, env)

    result = _run([str(HOOKS / "pre-commit")], root, env)

    assert result.returncode == 0


@pytest.mark.parametrize(
    ("hook", "identifier"),
    [
        ("pre-commit", "hook-pre-commit"),
        ("pre-merge-commit", "hook-pre-merge-commit"),
        ("pre-push", "hook-pre-push"),
        ("post-merge", "hook-post-merge"),
    ],
)
def test_git_hook_fires_registered_guardrail_best_effort(
    tmp_path: Path, hook: str, identifier: str
) -> None:
    root, env = _repo(tmp_path)
    env["VARDE_LEARN_STORE"] = str(tmp_path / "learn-store")
    registry = tomllib.loads(
        (REPO / "learn/src/varde_learn/loop/guardrails.toml").read_text()
    )
    assert identifier in {entry["id"] for entry in registry["guardrails"]}
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "fire-args"
    varde = bin_dir / "varde"
    varde.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{marker}"\nexit 1\n')
    varde.chmod(0o755)
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"

    result = _hook(root, env, hook, "0")

    assert result.returncode == 0, result.stdout + result.stderr
    _wait_for_file(marker)
    fired = f"learn sessions fire {identifier}"
    for _ in range(50):
        if fired in marker.read_text().splitlines():
            break
        time.sleep(0.1)
    assert fired in marker.read_text().splitlines()


def test_git_hook_without_varde_on_path_still_succeeds(tmp_path: Path) -> None:
    root, env = _repo(tmp_path)
    env["VARDE_LEARN_STORE"] = str(tmp_path / "learn-store")
    env["PATH"] = "/usr/bin:/bin"

    result = _hook(root, env, "pre-commit")

    assert result.returncode == 0, result.stdout + result.stderr


def test_rejected_git_hook_records_blocked_best_effort(tmp_path: Path) -> None:
    root, env = _repo(tmp_path)
    env["VARDE_LEARN_STORE"] = str(tmp_path / "learn-store")
    _stage(root, env, "bad.py", "import os\n")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "fire-args"
    varde = bin_dir / "varde"
    varde.write_text(f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{marker}"\nexit 1\n')
    varde.chmod(0o755)
    env["PATH"] = f"{bin_dir}:/usr/bin:/bin"

    result = _hook(root, env, "pre-commit")

    assert result.returncode != 0
    _wait_for_file(marker)
    assert marker.read_text().strip() == "learn sessions fire hook-pre-commit --blocked"


def _wait_for_file(path: Path, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    while (
        not path.exists() or path.stat().st_size == 0
    ) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert path.exists() and path.stat().st_size > 0, f"timed out waiting for {path}"


def _plan_branch_merge(
    tmp_path: Path, varde_status: int, branch: str = "worktree/p1", by_sha: bool = False
) -> subprocess.CompletedProcess[str]:
    root, env = _repo(tmp_path)
    _pyright_stub(root, env)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "varde"
    record = f'printf "%s\\n" "$*" > "{tmp_path}/varde-args"'
    fake.write_text(f"#!/bin/sh\n{record}\nexit {varde_status}\n")
    fake.chmod(0o755)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    target = _run(["git", "branch", "--show-current"], root, env).stdout.strip()
    _run(["git", "config", "core.hooksPath", ".githooks"], root, env)
    _run(["git", "switch", "-qc", branch], root, env)
    (root / "plan.txt").write_text("plan\n")
    _run(["git", "add", "plan.txt"], root, env)
    _run(["git", "commit", "--no-verify", "-qm", "plan work"], root, env)
    tip = _run(["git", "rev-parse", "HEAD"], root, env).stdout.strip()
    _run(["git", "switch", "-q", target], root, env)
    (root / "other.txt").write_text("other\n")
    _run(["git", "add", "other.txt"], root, env)
    _run(["git", "commit", "--no-verify", "-qm", "other"], root, env)
    revision = tip if by_sha else branch
    return _run(["git", "merge", "--no-ff", revision, "-m", "merge"], root, env)


@pytest.mark.parametrize(
    ("branch", "by_sha"),
    [("worktree/p1", False), ("feature/renamed", False), ("feature/by-sha", True)],
)
def test_pre_merge_commit_blocks_a_plan_merge_without_an_approval(
    tmp_path: Path, branch: str, by_sha: bool
) -> None:
    blocked = _plan_branch_merge(tmp_path, varde_status=1, branch=branch, by_sha=by_sha)
    assert blocked.returncode != 0
    assert "no user merge approval" in blocked.stderr
    asked = (tmp_path / "varde-args").read_text().strip()
    assert asked.startswith("plan merge-gate ")
    assert len(asked.split()[-1]) == 40 if by_sha else branch in asked


def test_pre_merge_commit_allows_a_plan_branch_with_an_approval(
    tmp_path: Path,
) -> None:
    merged = _plan_branch_merge(tmp_path, varde_status=0)
    assert merged.returncode == 0, merged.stdout + merged.stderr


def test_pre_merge_commit_blocks_when_varde_is_missing(tmp_path: Path) -> None:
    root, env = _repo(tmp_path)
    _pyright_stub(root, env)
    target = _run(["git", "branch", "--show-current"], root, env).stdout.strip()
    _run(["git", "config", "core.hooksPath", ".githooks"], root, env)
    _run(["git", "switch", "-qc", "feature/x"], root, env)
    (root / "x.txt").write_text("x\n")
    _run(["git", "add", "x.txt"], root, env)
    _run(["git", "commit", "--no-verify", "-qm", "x"], root, env)
    _run(["git", "switch", "-q", target], root, env)
    (root / "y.txt").write_text("y\n")
    _run(["git", "add", "y.txt"], root, env)
    _run(["git", "commit", "--no-verify", "-qm", "y"], root, env)
    bare = tmp_path / "no-varde-bin"
    bare.mkdir()
    for tool in ("git", "sh", "dirname", "env", "rm", "cat"):
        found = shutil.which(tool, path=env["PATH"])
        if found:
            (bare / tool).symlink_to(found)
    env["PATH"] = str(bare)
    blocked = _run(["git", "merge", "--no-ff", "feature/x", "-m", "m"], root, env)
    assert blocked.returncode != 0
    assert "varde is needed" in blocked.stderr
