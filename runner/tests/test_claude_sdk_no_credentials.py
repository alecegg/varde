"""The SDK adapter scrubs ambient credentials without reading or logging them."""

import ast
from pathlib import Path

from varde_runner.plugins import SessionSpec
from varde_runner.plugins.claude_sdk.plugin import (
    REMOVED_ENV_VARS,
    child_env,
    host_env,
)

PLUGIN = Path(__file__).parents[1] / "src/varde_runner/plugins/claude_sdk/plugin.py"


def test_sdk_adapter_scrubs_all_anthropic_auth_environment(monkeypatch) -> None:

    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "secret")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "secret")
    assert set(REMOVED_ENV_VARS) == {
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "CLAUDE_CODE_OAUTH_TOKEN",
    }
    env = child_env(
        SessionSpec("claude-sdk", "sonnet", "workspace", "/workspace/project")
    )
    assert not set(REMOVED_ENV_VARS) & env.keys()
    assert not set(REMOVED_ENV_VARS) & host_env().keys()
    source = PLUGIN.read_text(encoding="utf-8")
    assert "getpass" not in source and "keyring" not in source
    ast.parse(source)
