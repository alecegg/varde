from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from varde.glue import hook, worktree_prune_guard
from varde.glue.worktree_prune_guard import (
    deny_worktree_prune,
    is_primary_checkout,
    resolve_unmailboxed_caller,
)


@pytest.fixture(autouse=True)
def _runner_on(monkeypatch) -> None:
    monkeypatch.setenv("VARDE_RUNNER_ENABLED", "1")


def _denial(command: str, address: str | None) -> str | None:
    return deny_worktree_prune(command, lambda: address)


@pytest.mark.parametrize(
    "command",
    [
        "git worktree prune",
        "git -C /repo worktree prune --dry-run -v",
        "git -c safe.directory=/repo worktree prune",
        "git -C /repo -c user.name=test worktree prune",
        "git --no-optional-locks worktree prune",
        "git --no-replace-objects --glob-pathspecs -p -P worktree prune",
        "git --super-prefix=/repo --attr-source=HEAD worktree prune",
        "git --html-path --exec-path worktree prune",
        "git --exec-path=/git/libexec worktree prune",
        "git --unknown-global-option worktree prune",
        "env git worktree prune",
        "sudo -u alec git worktree prune",
        "sudo -E git worktree prune",
        "command -- git worktree prune",
        "time git worktree prune",
        "time -p git worktree prune",
        "nohup git worktree prune",
        "xargs git worktree prune",
        "bash -c 'git worktree prune'",
        "bash -c \"bash -c 'git worktree prune'\"",
        "eval 'git worktree prune'",
        "exec git worktree prune",
        "exec -a x git worktree prune",
        "echo `git worktree prune`",
        "echo $(git worktree prune)",
        "echo safe && git worktree prune",
        "git worktree prune --dry-run --verbose",
        "git worktree prune --help --dry-run",
    ],
)
def test_detects_prune_commands_for_non_main(command: str) -> None:
    assert _denial(command, "worker")
    assert _denial(command, None)
    assert _denial(command, "main") is None


@pytest.mark.parametrize(
    "command",
    [
        "git worktree list",
        "git worktree add /repo/task",
        "git worktree remove /repo/task",
        "git status",
        "echo 'git worktree prune'",
        "bash -c 'echo git worktree prune'",
        "git -C worktree prune",
        "git config worktree prune",
        "echo '`git worktree prune`'",
        "git --git-dir /repo worktree list",
        "git --help worktree prune",
        "git worktree prune'",
    ],
)
def test_ignores_other_commands(command: str) -> None:
    assert _denial(command, "worker") is None


@pytest.mark.parametrize(
    "command",
    [
        "git -C /repo -c name=value worktree prune",
        "git --git-dir=/repo/.git worktree prune",
        "git --git-dir /repo/.git worktree prune",
        "git --work-tree=/repo worktree prune",
        "git --work-tree /repo worktree prune",
        "git --namespace=space worktree prune",
        "git --namespace space worktree prune",
        "git --config-env=name=ENV worktree prune",
        "git --config-env name=ENV worktree prune",
    ],
)
def test_consumes_values_for_git_global_options(command: str) -> None:
    assert _denial(command, "worker")


def test_denial_tokenizes_a_plain_command_once(monkeypatch) -> None:
    original = worktree_prune_guard.tokenize_command
    calls = []

    def tokenize(command: str):
        calls.append(command)
        return original(command)

    monkeypatch.setattr(worktree_prune_guard, "tokenize_command", tokenize)
    assert _denial("git worktree prune", "worker")
    assert calls == ["git worktree prune"]


def test_hook_resolves_only_prune_commands_and_records_each_attempt(
    monkeypatch, capsys
) -> None:
    resolutions = []
    firings = []
    monkeypatch.setattr(
        "varde.glue.inbox_hook.resolve_address",
        lambda harness, session_id: (
            resolutions.append((harness, session_id)) or "worker"
        ),
    )
    monkeypatch.setattr(
        "varde.glue.hook_record.record_firing",
        lambda guardrail_id, *, blocked=False: firings.append((guardrail_id, blocked)),
    )

    hook.pre_tool_use(
        "codex",
        json.dumps(
            {
                "session_id": "worker-session",
                "tool_name": "Bash",
                "tool_input": {"command": "git worktree prune --dry-run"},
            }
        ),
    )
    assert (
        json.loads(capsys.readouterr().out)["hookSpecificOutput"]["permissionDecision"]
        == "deny"
    )
    assert resolutions == [("codex", "worker-session")]
    assert firings == [("hook-pre-tool-worktree-prune", True)]

    monkeypatch.setattr(
        "varde.glue.inbox_hook.resolve_address",
        lambda harness, session_id: "main",
    )
    hook.pre_tool_use(
        "codex",
        json.dumps(
            {
                "session_id": "main-session",
                "tool_name": "Bash",
                "tool_input": {"command": "git worktree prune -v"},
            }
        ),
    )
    assert capsys.readouterr().out == ""
    assert firings[-1] == ("hook-pre-tool-worktree-prune", False)

    monkeypatch.setattr(
        "varde.glue.inbox_hook.resolve_address",
        lambda harness, session_id: None,
    )
    hook.pre_tool_use(
        "codex",
        json.dumps(
            {
                "session_id": "unknown-session",
                "tool_name": "Bash",
                "tool_input": {"command": "git worktree prune"},
            }
        ),
    )
    assert (
        json.loads(capsys.readouterr().out)["hookSpecificOutput"]["permissionDecision"]
        == "deny"
    )
    assert firings[-1] == ("hook-pre-tool-worktree-prune", True)


def test_hook_denies_if_address_resolution_raises(monkeypatch, capsys) -> None:
    def resolve_address(harness, session_id):
        raise OSError("binding store unreadable")

    firings = []
    monkeypatch.setattr("varde.glue.inbox_hook.resolve_address", resolve_address)
    monkeypatch.setattr(
        "varde.glue.hook_record.record_firing",
        lambda guardrail_id, *, blocked=False: firings.append((guardrail_id, blocked)),
    )
    hook.pre_tool_use(
        "codex",
        json.dumps(
            {
                "session_id": "session",
                "tool_name": "Bash",
                "tool_input": {"command": "git worktree prune"},
            }
        ),
    )
    assert (
        json.loads(capsys.readouterr().out)["hookSpecificOutput"]["permissionDecision"]
        == "deny"
    )
    assert firings == [("hook-pre-tool-worktree-prune", True)]


def test_hook_denies_agent_id_even_when_session_resolves_to_main(
    monkeypatch, capsys
) -> None:
    resolutions = []

    def resolve_address(harness, session_id):
        resolutions.append((harness, session_id))
        return "main"

    firings = []
    monkeypatch.setattr("varde.glue.inbox_hook.resolve_address", resolve_address)
    monkeypatch.setattr(
        "varde.glue.hook_record.record_firing",
        lambda guardrail_id, *, blocked=False: firings.append((guardrail_id, blocked)),
    )
    hook.pre_tool_use(
        "codex",
        json.dumps(
            {
                "session_id": "main-session",
                "agent_id": "builder-1",
                "tool_name": "Bash",
                "tool_input": {"command": "git worktree prune"},
            }
        ),
    )
    assert (
        json.loads(capsys.readouterr().out)["hookSpecificOutput"]["permissionDecision"]
        == "deny"
    )
    assert firings == [("hook-pre-tool-worktree-prune", True)]
    assert resolutions == []


def test_hook_skips_address_resolution_and_firing_for_other_commands(
    monkeypatch, capsys
) -> None:
    def unexpected(*args):
        pytest.fail("non-prune command must not resolve caller address")

    firings = []

    def record_firing(guardrail_id, *, blocked=False):
        firings.append((guardrail_id, blocked))

    monkeypatch.setattr("varde.glue.inbox_hook.resolve_address", unexpected)
    monkeypatch.setattr(
        "varde.glue.hook_record.record_firing",
        record_firing,
    )
    hook.pre_tool_use(
        "codex",
        json.dumps(
            {
                "session_id": "session",
                "tool_name": "Bash",
                "tool_input": {"command": "git worktree list"},
            }
        ),
    )
    assert capsys.readouterr().out == ""
    assert firings == []


def _linked_worktree(tmp_path: Path) -> Path:
    main = tmp_path / "main"
    worktree = tmp_path / "worktree"
    main.mkdir()
    commands = [
        ["git", "init", str(main)],
        ["git", "-C", str(main), "config", "user.name", "Test"],
        ["git", "-C", str(main), "config", "user.email", "test@example.com"],
    ]
    for command in commands:
        subprocess.run(command, check=True, capture_output=True)
    (main / "tracked.py").write_text("pass\n")
    subprocess.run(
        ["git", "-C", str(main), "add", "tracked.py"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(main), "commit", "-m", "init"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(main), "worktree", "add", "-b", "task", str(worktree)],
        check=True,
        capture_output=True,
    )
    return worktree


def test_main_prune_allow_continues_to_install_guard_in_linked_worktree(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    worktree = _linked_worktree(tmp_path)
    firings = []
    monkeypatch.setattr(
        "varde.glue.inbox_hook.resolve_address",
        lambda harness, session_id: "main",
    )
    monkeypatch.setattr(
        "varde.glue.hook_record.record_firing",
        lambda guardrail_id, *, blocked=False: firings.append((guardrail_id, blocked)),
    )
    hook.pre_tool_use(
        "codex",
        json.dumps(
            {
                "session_id": "main-session",
                "cwd": str(worktree),
                "tool_name": "Bash",
                "tool_input": {
                    "command": "git worktree prune && uv tool install varde"
                },
            }
        ),
    )
    reason = json.loads(capsys.readouterr().out)["hookSpecificOutput"][
        "permissionDecisionReason"
    ]
    assert "uv tool install" in reason
    assert firings == [
        ("hook-pre-tool-worktree-prune", False),
        ("hook-pre-tool-install-guard", True),
    ]


def _primary(tmp_path: Path) -> Path:
    return _linked_worktree(tmp_path).parent / "main"


def test_is_primary_checkout_true_at_root_and_in_subfolder(tmp_path: Path) -> None:
    main = _primary(tmp_path)
    (main / "sub" / "deep").mkdir(parents=True)
    assert is_primary_checkout(str(main))
    assert is_primary_checkout(str(main / "sub" / "deep"))


def test_is_primary_checkout_false_in_linked_worktree(tmp_path: Path) -> None:
    worktree = _linked_worktree(tmp_path)
    (worktree / "sub").mkdir()
    assert not is_primary_checkout(str(worktree))
    assert not is_primary_checkout(str(worktree / "sub"))


def test_is_primary_checkout_follows_symlinked_cwd(tmp_path: Path) -> None:
    worktree = _linked_worktree(tmp_path)
    main = worktree.parent / "main"
    to_main = tmp_path / "to-main"
    to_worktree = tmp_path / "to-worktree"
    to_main.symlink_to(main)
    to_worktree.symlink_to(worktree)
    assert is_primary_checkout(str(to_main))
    assert not is_primary_checkout(str(to_worktree))


@pytest.mark.parametrize("variable", ["GIT_DIR", "GIT_COMMON_DIR"])
def test_is_primary_checkout_false_when_git_location_env_set(
    tmp_path: Path, monkeypatch, variable: str
) -> None:
    main = _primary(tmp_path)
    monkeypatch.setenv(variable, str(main / ".git"))
    assert not is_primary_checkout(str(main))


@pytest.mark.parametrize("cwd", [None, 7, ["x"], "", "/nonexistent/path/x"])
def test_is_primary_checkout_false_for_bad_cwd(cwd) -> None:
    assert not is_primary_checkout(cwd)


def test_is_primary_checkout_false_outside_a_repository(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert not is_primary_checkout(str(plain))


def test_resolve_unmailboxed_caller(tmp_path: Path) -> None:
    worktree = _linked_worktree(tmp_path)
    main = str(worktree.parent / "main")
    assert resolve_unmailboxed_caller({}, main) == "main"
    assert resolve_unmailboxed_caller({}, str(worktree)) is None
    assert resolve_unmailboxed_caller({"agent_id": "a"}, main) is None
    assert resolve_unmailboxed_caller({}, None) is None
    assert resolve_unmailboxed_caller({}, 3) is None  # type: ignore[arg-type]


def _git(*args: str) -> None:
    subprocess.run(
        ["git", "-c", "protocol.file.allow=always", *args],
        check=True,
        capture_output=True,
    )


def _submodule_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Return (primary checkout, linked worktree), both containing submodule sm."""
    sub, main, worktree = tmp_path / "sub", tmp_path / "main", tmp_path / "wt"
    for repo in (sub, main):
        _git("init", str(repo))
        _git("-C", str(repo), "config", "user.name", "Test")
        _git("-C", str(repo), "config", "user.email", "t@example.com")
    _git("-C", str(sub), "commit", "--allow-empty", "-m", "s")
    _git("-C", str(main), "submodule", "add", str(sub), "sm")
    _git("-C", str(main), "commit", "-m", "add sm")
    _git("-C", str(main), "worktree", "add", "-b", "task", str(worktree))
    _git("-C", str(worktree), "submodule", "update", "--init")
    return main, worktree


def test_submodule_is_judged_by_its_superproject(tmp_path: Path) -> None:
    main, worktree = _submodule_repo(tmp_path)
    assert is_primary_checkout(str(main / "sm"))
    assert not is_primary_checkout(str(worktree / "sm"))


def test_bare_repository_counts_as_primary(tmp_path: Path) -> None:
    bare = tmp_path / "bare.git"
    subprocess.run(
        ["git", "init", "--bare", str(bare)], check=True, capture_output=True
    )
    assert is_primary_checkout(str(bare))
