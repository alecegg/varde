from pathlib import Path

from varde_runner.guard_policy import allowlist, must_escalate, verdict


def _must_escalate(kind, payload):
    return must_escalate(kind, payload, str(Path.cwd()))


def _rows(key, count=3):
    return [{"request_key": key, "response": "approve"} for _ in range(count)]


def test_hard_escalation_classes():
    cases = [
        ("credential", {"token": "abc"}),
        ("command_prefix", {"metadata": [{"password": "secret-value"}]}),
        ("path_scope", {"path": "/repo/.claude/settings.json"}),
        ("path_scope", {"path": "/repo/config/sandbox.toml"}),
        ("command_prefix", {"command": "rm -rf build"}),
        ("command_prefix", {"command": "git push origin main"}),
        ("command_prefix", {"command": "curl https://example.test"}),
        ("command_prefix", {"command": "echo ghp_abcdefghijklmnopqrstuvwxyz"}),
        ("command_prefix", {"command": "pytest tests | tee out"}),
        ("command_prefix", {"command": "sudo pytest"}),
        ("network", {"url": "https://example.test"}),
        ("scope_change", {"scope": "write"}),
        ("other", {"tool": "unknown"}),
    ]
    for kind, payload in cases:
        assert _must_escalate(kind, payload), (kind, payload)


def test_allowlist_filters_revoked_and_forbidden_keys():
    rows = (
        _rows("command_prefix:pytest")
        + _rows("command_prefix:rm")
        + _rows("credential:credential")
        + _rows("scope_change:scope_change")
        + _rows("network:network")
        + _rows("other:other")
    )
    assert allowlist(rows) == ["command_prefix:pytest"]
    assert allowlist(rows, revoked=frozenset({"command_prefix:pytest"})) == []


def test_verdict_approves_allowlisted_command():
    assert verdict(
        "command_prefix",
        {"command": "pytest tests"},
        str(Path.cwd()),
        {"command_prefix:pytest"},
    ) == {
        "verdict": "approve",
        "reason": "allowlist match",
        "request_key": "command_prefix:pytest",
    }


def test_workspace_paths_resolve_from_session_root_not_process_cwd(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "workspace"
    other_cwd = tmp_path / "other"
    workspace.mkdir()
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)

    result = verdict(
        "command_prefix",
        {"command": "pytest ../workspace/tests"},
        str(workspace),
        {"command_prefix:pytest"},
    )

    assert result["verdict"] == "approve"


def test_path_scope_outside_workspace_escalates(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    assert (
        must_escalate(
            "path_scope", {"path": str(tmp_path / "outside.txt")}, str(workspace)
        )
        == "path is outside the session workspace"
    )


def test_hard_escalation_wins_over_allowlist():
    result = verdict(
        "command_prefix",
        {"command": "git push origin main"},
        None,
        {"command_prefix:git"},
    )
    assert result["verdict"] == "escalate"
    assert result["reason"] != "no allowlist match"


def test_default_deny_closes_command_bypasses():
    cases = [
        ("env pytest", "env"),
        ("time pytest", "time"),
        ("nohup pytest", "nohup"),
        ("command pytest", "command"),
        ("exec pytest", "exec"),
        ("xargs pytest", "xargs"),
        ("sudo pytest", "sudo"),
        ("nice pytest", "nice"),
        ("bash -c pytest", "bash -c"),
        ("sh -c pytest", "sh -c"),
        ("zsh -c pytest", "zsh -c"),
        ("eval pytest", "eval"),
        ("python -c 'import os'", "python -c"),
        ("pytest tests\nrm -rf .", "newline"),
        ("pytest tests &", "bare ampersand"),
        ("pytest tests | cat", "pipe"),
        ("pytest tests; ruff check .", "semicolon"),
        ("pytest tests && ruff check .", "and chain"),
        ("pytest tests > out", "redirect"),
        ("pytest tests < in", "input redirect"),
        ("echo `id`", "backtick"),
        ("echo $(id)", "command substitution"),
        ("echo ${HOME}", "variable expansion"),
        ("git -C x push", "git -C push"),
        ("git -c alias.x=push status", "git -c"),
        ("pytest 'unterminated", "shlex parse error"),
    ]
    for command, label in cases:
        assert _must_escalate("command_prefix", {"command": command}), label
    assert _must_escalate("command_prefix", {"command": "FOO=bar pytest tests"}) is None


def test_wildcard_keys_are_rejected_everywhere():
    assert allowlist(_rows("command_prefix:pytest*")) == []
    assert (
        verdict(
            "command_prefix",
            {"command": "pytest tests"},
            str(Path.cwd()),
            {"command_prefix:pytest*"},
        )["verdict"]
        == "escalate"
    )


def test_verdict_rechecks_kind_and_safety():
    for kind, payload in [
        ("credential", {"token": "abc"}),
        ("network", {"url": "https://example.test"}),
        ("other", {"tool": "unknown"}),
    ]:
        assert (
            verdict(kind, payload, None, {"credential:credential", "network", "other"})[
                "verdict"
            ]
            == "escalate"
        )
    assert (
        verdict("command_prefix", {"command": "rm -rf x"}, None, {"command_prefix:rm"})[
            "verdict"
        ]
        == "escalate"
    )


def test_sensitive_fields_and_protected_paths_override_caller_kind():
    assert _must_escalate("path_scope", {"url": "https://example.test"})
    protected = (
        "cat ~/.ssh/id_rsa",
        "cat .env",
        "cat config/../.env.local",
        "cat .claude.json",
        "cat .mcp.json",
        "cat .agents/config",
        "cat .git/config",
        "cat .git/hooks/pre-commit",
        "cat .codex/config.toml",
        "cat ~/.zshrc",
        "cat managed-settings.json",
    )
    for command in protected:
        assert _must_escalate("command_prefix", {"command": command}), command


def test_strict_flags_and_workspace_paths(tmp_path, monkeypatch):
    workspace = tmp_path / "work"
    (workspace / "src").mkdir(parents=True)
    monkeypatch.chdir(workspace)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    escalate = [
        "rg --pre ./x foo",
        "rg --pre-glob '*.x' foo",
        "rg --hidden foo",
        "sed -n 1,5w out.txt file.py",
        "sed -n 1e file.py",
        "sed -n 1r other file.py",
        "sed -i s/a/b/ file.py",
        "sed -n -e 1p file.py",
        "sed -n s/a/b/p file.py",
        "uv run pytest -p evil tests",
        "uv run pytest -pevil tests",
        "pytest -c other.ini",
        "uv run pytest --rootdir /etc",
        "ruff check --config x.toml .",
        "ruff check --fix .",
        "ruff check --fix-only .",
        "ruff check --unsafe-fixes .",
        "ruff check --add-noqa .",
        "uv run ruff check --fix .",
        "git diff --output=out.txt",
        "git log --output out.txt",
        "git show --output=out.txt",
        "git diff --ext-diff",
        "git show --textconv HEAD:x",
        "git add -f ignored.txt",
        "git add --force ignored.txt",
        "git add -Af x",
        "git -C /etc status",
        "git -C .. status",
        "git -C $UNSET status",
        "git -C",
        "cat /etc/shadow",
        "cat ~/.netrc",
        "cat $HOME/.config/gh/hosts.yml",
        "cat ~/.config/gh/hosts.yml",
        "cat src/../../outside.txt",
        "cat $OTHER/file",
        "grep foo /etc/passwd",
        "rg foo ..",
        "head -n 5 /etc/hosts",
        "tail -f src/log",
        "ls /",
        "ls ~",
    ]
    for command in escalate:
        assert _must_escalate("command_prefix", {"command": command}), command
    allow = [
        "rg foo src",
        "rg --files src",
        "rg -n -g '*.py' foo .",
        "sed -n 1,5p src/a.py",
        "sed -n '3p' src/a.py",
        "sed -n '2,$p' src/a.py",
        "uv run pytest runner/tests/test_x.py::test_a -q",
        "uv run pytest -x -k name --maxfail=2 .",
        "ruff check src",
        "uv run ruff check --select E --output-format=concise src",
        "git diff --stat",
        "git log --oneline -5",
        f"git -C {workspace}/src status",
        "git -C src status",
        "git add src/a.py",
        "cat src/a.py",
        f"cat {workspace}/src/a.py",
        "grep -rn foo src",
        "head -n 5 src/a.py",
        "tail -20 src/a.py",
        "ls -la src",
        "ls",
    ]
    for command in allow:
        assert _must_escalate("command_prefix", {"command": command}) is None, command
