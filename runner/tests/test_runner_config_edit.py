from __future__ import annotations

from pathlib import Path

import pytest
from varde_runner import config_io
from varde_runner.config import default_toml
from varde_runner.runner_config_edit import EditError, allowlist, apply, validate


class Registry:
    def __init__(self, *tables: str):
        self._tables = frozenset(tables)

    def config_tables(self):
        return self._tables

    def known_harnesses(self):
        return {
            "claude-cli",
            "claude-sdk",
            "codex-app-server",
            "pi-rpc",
            "opencode-http",
        }

    def config_choices(self, harness):
        options = {
            "claude-sdk": {
                "models": ["claude-sonnet-5-5"],
                "reasoning_efforts": ["low", "medium", "high"],
                "modes": ["workspace-write", "read-only"],
            },
            "codex-app-server": {
                "models": ["gpt-6-luna"],
                "reasoning_efforts": ["low", "medium", "high"],
                "modes": ["workspace-write", "read-only"],
            },
            "opencode-http": {
                "models": ["opencode-go/deepseek-v4.1-flash"],
                "reasoning_efforts": ["high"],
                "modes": ["workspace-write", "read-only"],
            },
            "claude-cli": {
                "models": ["claude-sonnet-5-5"],
                "reasoning_efforts": ["low", "medium", "high"],
                "modes": ["workspace-write", "read-only"],
            },
            "pi-rpc": {
                "models": ["claude-sonnet-5-5"],
                "reasoning_efforts": [
                    "off",
                    "minimal",
                    "low",
                    "medium",
                    "high",
                    "xhigh",
                    "max",
                ],
                "modes": ["workspace-write", "read-only"],
            },
        }
        for value in options.values():
            value["harnesses"] = list(options)
        return options.get(
            harness,
            {"harnesses": [], "models": [], "reasoning_efforts": [], "modes": []},
        )

    def capabilities(self, harness):
        return type(
            "Capabilities", (), {"guard_read_only": harness == "codex-app-server"}
        )()


@pytest.fixture
def registry():
    return Registry(
        "claude_cli",
        "claude_sdk",
        "codex_app_server",
        "opencode_http",
        "pi_rpc",
        "pi_durable",
    )


def test_allowlist_uses_registry_tables_and_bounded_shared_fields(registry):
    fields = allowlist(registry, default_toml())

    assert set(fields) == {
        "limits.max_live_instances",
        "claude_cli.enabled",
        "claude_sdk.enabled",
        "codex_app_server.enabled",
        "opencode_http.enabled",
        "pi_rpc.enabled",
        "pi_durable.enabled",
        "types.standard.harness",
        "types.standard.model",
        "types.standard.reasoning_effort",
        "types.standard.fallback",
        "types.heavy.harness",
        "types.heavy.model",
        "types.heavy.reasoning_effort",
        "types.heavy.fallback",
        "types.light.harness",
        "types.light.model",
        "types.light.reasoning_effort",
        "types.light.fallback",
        "roles.orchestrator.type",
        "roles.planner.type",
        "roles.builder.type",
        "roles.explorer.type",
        "roles.reviewer.type",
        "roles.judge.type",
        "roles.guard.type",
        "roles.guard.enabled",
        "roles.manager-bot.type",
        "policy.never_models",
        "policy.allow_fallback_only_on",
    }


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("limits.max_live_instances", 64),
        ("claude_sdk.enabled", False),
        ("codex_app_server.enabled", True),
        ("claude_cli.enabled", True),
        ("opencode_http.enabled", False),
        ("pi_rpc.enabled", True),
        ("pi_durable.enabled", False),
    ],
)
def test_validate_accepts_each_allowlisted_key(registry, key, value):
    assert validate({key: value}, registry, default_toml()) == {}


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"unknown.enabled": True}, "not allowlisted"),
        ({"runner.require_user_pairing": True}, "not allowlisted"),
        ({"runner.idle_process_timeout_s": 0}, "not allowlisted"),
        ({"limits.max_live_instances": 0}, "at least 1"),
        ({"limits.max_live_instances": 65}, "at most 64"),
        ({"limits.max_live_instances": True}, "integer"),
        ({"claude_sdk.enabled": 1}, "boolean"),
        ({"bot.api_key": "secret"}, "cannot be edited"),
        ({"bot.access_token": "secret"}, "cannot be edited"),
        ({"bot.client_secret": "secret"}, "cannot be edited"),
        ({"codex_app_server.binary": "codex-bin"}, "cannot be edited"),
        ({"launch.command": "anything"}, "cannot be edited"),
        ({"config.path": "config-dir"}, "cannot be edited"),
    ],
)
def test_validate_rejects_unknown_excluded_and_invalid_values(
    registry, change, message
):
    key = next(iter(change))
    assert message in validate(change, registry, default_toml())[key]


def test_numeric_token_budgets_are_allowed_but_secret_tokens_are_not(
    registry, monkeypatch
):
    bounds = {
        "daily_token_budget": (0, 1_000_000_000),
        "weekly_token_budget": (0, 1_000_000_000),
        "api_token": (0, 1_000_000_000),
    }
    monkeypatch.setattr(
        "varde_runner.runner_config_edit.config.BOT_CONFIG_BOUNDS",
        bounds,
        raising=False,
    )
    text = (
        default_toml() + "\n[bot]\ndaily_token_budget = 500\n"
        "weekly_token_budget = 1500\napi_token = 10\n"
    )

    assert validate({"bot.daily_token_budget": 600}, registry, text) == {}
    assert validate({"bot.weekly_token_budget": 1600}, registry, text) == {}
    assert validate({"bot.api_token": 20}, registry, text)["bot.api_token"].endswith(
        "edited in Settings"
    )


def test_apply_replaces_values_and_preserves_comments_and_unmanaged_tables(registry):
    text = default_toml() + "\n[custom]\n# keep this\nname = 'mine'\n"
    text = text.replace("max_live_instances = 8", "max_live_instances = 8 # cap")

    result = apply(text, {"limits.max_live_instances": 12}, registry)

    assert isinstance(result, str)
    assert "max_live_instances = 12 # cap" in result
    assert "[custom]\n# keep this\nname = 'mine'" in result


def test_apply_appends_missing_plugin_table(registry):
    text = default_toml()

    result = apply(text, {"claude_cli.enabled": True}, registry)

    assert isinstance(result, str)
    assert "[claude_cli]\nenabled = true" in result


@pytest.mark.parametrize(
    "text",
    [
        "[limits]\nmax_live_instances = { value = 8 }\n",
        "limits = { max_live_instances = 8 }\n",
        "[[limits]]\nmax_live_instances = 8\n",
    ],
)
def test_apply_refuses_structures_that_cannot_be_edited_safely(registry, text):
    result = apply(text, {"limits.max_live_instances": 9}, registry)

    assert isinstance(result, EditError)
    assert "by hand" in result.hint or "invalid" in result.hint


def test_apply_refuses_changes_that_make_whole_config_invalid(registry):
    text = (
        default_toml()
        .replace("[claude_cli]\nenabled = false", "[claude_cli]\nenabled = true")
        .replace('harness = "claude-sdk"', 'harness = "claude-cli"', 1)
    )
    result = apply(text, {"claude_cli.enabled": False}, registry)

    assert isinstance(result, EditError)
    assert "resulting config is invalid" in result.hint


def test_type_fields_role_mappings_guard_and_policy_are_editable(registry):
    text = default_toml()
    changes = {
        "types.light.harness": "codex-app-server",
        "types.light.model": "gpt-6-luna",
        "types.light.reasoning_effort": "high",
        "types.standard.fallback": [
            {
                "harness": "opencode-http",
                "model": "opencode-go/deepseek-v4.1-flash",
                "reasoning_effort": "high",
            }
        ],
        "roles.builder.type": "standard",
        "roles.guard.enabled": True,
        "policy.never_models": ["*-sol", "*-legacy"],
        "policy.allow_fallback_only_on": [],
    }

    result = apply(text, changes, registry)

    assert isinstance(result, str)
    parsed = __import__("tomllib").loads(result)
    assert parsed["types"]["light"]["reasoning_effort"] == "high"
    assert parsed["types"]["standard"]["fallback"] == changes["types.standard.fallback"]
    assert parsed["roles"]["builder"]["type"] == "standard"
    assert parsed["roles"]["guard"]["enabled"] is True
    assert parsed["policy"]["never_models"] == ["*-sol", "*-legacy"]
    assert parsed["policy"]["allow_fallback_only_on"] == []


@pytest.mark.parametrize(
    "change",
    [
        {"types.standard.harness": "unknown-harness"},
        {"types.standard.model": "unknown-model"},
        {"types.standard.reasoning_effort": "impossible"},
        {"roles.builder.type": "missing"},
        {
            "types.standard.fallback": [
                {"harness": "missing", "model": "x", "reasoning_effort": "high"}
            ]
        },
        {"types.light.harness": "claude-sdk", "roles.guard.enabled": True},
    ],
)
def test_apply_rejects_invalid_supported_edits_without_values_in_errors(
    registry, change
):
    result = apply(default_toml(), change, registry)

    assert isinstance(result, EditError)
    assert "unknown-model" not in result.hint
    assert "impossible" not in result.hint


def test_apply_rejects_readonly_and_sensitive_fields_without_echoing_values(registry):
    sentinel = "SENSITIVE-SENTINEL-4831"

    result = apply(
        default_toml(),
        {
            "allowed_hosts": [sentinel],
            "config.path": sentinel,
            "bot.env": {"KEY": sentinel},
            "launch.command": sentinel,
        },
        registry,
    )

    assert isinstance(result, EditError)
    assert sentinel not in result.hint


def test_write_config_creates_backup_and_rotates_to_five(tmp_path: Path):
    path = tmp_path / "runner.toml"
    path.write_text("version = 1\n", encoding="utf-8")

    for index in range(7):
        config_io.write_config(path, f"version = {index + 2}\n")

    backups = list(tmp_path.glob("runner.toml.*.bak"))
    assert path.read_text(encoding="utf-8") == "version = 8\n"
    assert len(backups) == 5
    assert {backup.read_text(encoding="utf-8") for backup in backups} == {
        f"version = {value}\n" for value in range(3, 8)
    }


def test_atomic_write_failure_keeps_existing_file(tmp_path: Path, monkeypatch):
    path = tmp_path / "runner.toml"
    path.write_bytes(b"old")
    replace = config_io.os.replace

    def fail_target(source, destination):
        if destination == path:
            raise OSError("replace failed")
        replace(source, destination)

    monkeypatch.setattr(config_io.os, "replace", fail_target)

    with pytest.raises(OSError, match="replace failed"):
        config_io.atomic_write(path, b"new")

    assert path.read_bytes() == b"old"
    assert list(tmp_path.glob(".runner.toml.*")) == []
