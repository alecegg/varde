from pathlib import Path
from types import SimpleNamespace

from varde_runner.config import Role
from varde_runner.guard import (
    build_prompt,
    combine_verdicts,
    evaluate,
    parse_reply,
    run_model,
)
from varde_runner.plugins import RunnerCapabilities
from varde_runner.plugins.registry import PluginRegistry


def _role():
    return Role("codex-app-server", "gpt-6-luna", "medium", "read-only", ())


def test_reply_parser_requires_supported_json():
    assert parse_reply('{"verdict":"approve","reason":"safe"}') == {
        "verdict": "approve",
        "reason": "safe",
    }
    assert parse_reply("approve") is None
    assert parse_reply('{"verdict":"deny","reason":"no"}') is None
    assert parse_reply('{"verdict":"approve"}') is None
    assert parse_reply('{"verdict":"approve","reason":"safe","tool":"Read"}') is None


def test_model_can_only_downgrade_deterministic_approval():
    policy = {"verdict": "escalate", "reason": "unsafe", "request_key": "x"}
    assert combine_verdicts(policy, {"verdict": "approve", "reason": "ok"}) == policy
    approved = {"verdict": "approve", "reason": "allowlist match", "request_key": "x"}
    assert combine_verdicts(approved, None)["verdict"] == "escalate"
    assert (
        combine_verdicts(approved, {"verdict": "escalate", "reason": "uncertain"})[
            "verdict"
        ]
        == "escalate"
    )


def test_prompt_contains_redacted_request_as_data():
    prompt = build_prompt('{"token":"[redacted]"}', {"request_kind": "credential"})
    assert "untrusted data" in prompt
    assert "[redacted]" in prompt
    assert "supersecret" not in prompt


def test_run_model_uses_selected_read_only_plugin():
    class FakePlugin:
        capabilities = RunnerCapabilities(guard_read_only=True)

        def __init__(self):
            self.spec = None
            self.stopped = False

        def session_settings(self, model):
            return SimpleNamespace(model=model.model)

        def is_provider_limit_error(self, _exc):
            return False

        async def run_guard(self, spec):
            self.spec = spec
            assert list(Path(spec.cwd).iterdir()) == []
            self.stopped = True
            return '{"verdict":"approve","reason":"safe"}'

    plugin = FakePlugin()
    registry = PluginRegistry()
    role = Role("selected-plugin", "gpt-6-luna", "medium", "read-only", ())
    registry.register(role.harness, plugin, provider_key="selected-provider")
    reply = run_model(role, "redacted prompt", registry)
    assert reply is not None
    assert reply["verdict"] == "approve"
    assert plugin.spec is not None
    assert plugin.spec.provider == "selected-provider"
    assert plugin.spec.prompt == "redacted prompt"
    assert plugin.spec.mode_id == "read-only"
    assert plugin.spec.model == "gpt-6-luna"
    assert plugin.stopped is True


def test_run_model_fails_closed_without_read_only_capability():
    class UnverifiedPlugin:
        capabilities = RunnerCapabilities()

    registry = PluginRegistry()
    registry.register("codex-app-server", UnverifiedPlugin())

    assert run_model(_role(), "prompt", registry) is None


def test_evaluate_never_calls_model_for_hard_escalation(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "varde_runner.guard.run_model",
        lambda *_args: (_ for _ in ()).throw(AssertionError("model must not run")),
    )
    result = evaluate(
        _role(),
        "command_prefix",
        {"command": "git push origin main"},
        str(tmp_path),
        ["command_prefix:git"],
    )
    assert result["verdict"] == "escalate"


def test_evaluate_approves_only_after_model_confirms_allowlist_match(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(
        "varde_runner.guard.run_model",
        lambda *_args: {"verdict": "approve", "reason": "confirmed"},
    )
    result = evaluate(
        _role(),
        "command_prefix",
        {"command": "pytest tests"},
        str(tmp_path),
        ["command_prefix:pytest"],
    )
    assert result["verdict"] == "approve"
    assert result["reason"] == "confirmed"


def test_evaluate_escalates_when_model_fails(monkeypatch, tmp_path):
    monkeypatch.setattr("varde_runner.guard.run_model", lambda *_args: None)
    result = evaluate(
        _role(),
        "command_prefix",
        {"command": "pytest tests"},
        str(tmp_path),
        ["command_prefix:pytest"],
    )
    assert result["verdict"] == "escalate"
