from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from varde_runner.config import (
    DEFAULT_ROLE_TYPES,
    TYPE_DEFINITIONS,
    ConfigError,
    classify_limit_error,
    config_dir,
    config_path,
    configured_allowed_hosts,
    configured_user_pairing,
    default_config,
    default_toml,
    keep_unknown_roles,
    load_config,
    parse_config,
    unknown_role_blocks,
)
from varde_runner.generate import check_drift


def valid_toml(model: str = "gpt-6-luna") -> str:
    return f'''version = 1

[roles.builder]
harness = "codex-app-server"
model = "{model}"
reasoning_effort = "medium"
mode = "workspace-write"

[[roles.builder.fallback]]
harness = "opencode-http"
model = "opencode-go/deepseek-v4.1-flash"
reasoning_effort = "high"
mode = "workspace-write"

[policy]
never_models = ["*-sol"]
allow_fallback_only_on = ["provider_limit"]
create_paseo_projects = false
'''


def new_format_toml() -> str:
    return default_toml()


def test_startup_kill_timeout_must_be_zero_or_at_least_warning_timeout():
    with pytest.raises(ConfigError, match="startup_kill_timeout_s"):
        text = valid_toml().replace(
            "[roles.builder]",
            "startup_timeout_s = 30\nstartup_kill_timeout_s = 29\n\n[roles.builder]",
        )
        parse_config(text)


def test_absent_startup_kill_timeout_defaults_to_at_least_warning_timeout():
    text = valid_toml().replace(
        "[roles.builder]", "startup_timeout_s = 400\n\n[roles.builder]"
    )
    config = parse_config(text)
    assert config.startup_kill_timeout_s == 400
    assert parse_config(valid_toml()).startup_kill_timeout_s == 300


def test_fallback_trigger_policy_can_disable_fallback():
    text = valid_toml().replace(
        'allow_fallback_only_on = ["provider_limit"]',
        "allow_fallback_only_on = []",
    )
    assert parse_config(text).allow_fallback_only_on == ()


def test_stall_after_must_be_positive():
    with pytest.raises(ConfigError, match="stall_after_s"):
        text = valid_toml().replace("version = 1", "version = 1\nstall_after_s = 0")
        parse_config(text)
    assert parse_config(valid_toml()).stall_after_s == 600


def legacy_default_toml(guard_enabled: bool = False) -> str:
    roles = default_config().roles
    lines = [
        "version = 1",
        "",
        "[policy]",
        'never_models = ["*-sol"]',
        'allow_fallback_only_on = ["provider_limit"]',
        "create_paseo_projects = false",
        "",
    ]
    for name, role in roles.items():
        lines.extend(
            (
                f"[roles.{name}]",
                f'harness = "{role.harness}"',
                f'model = "{role.model}"',
                f'reasoning_effort = "{role.reasoning_effort}"',
                f'mode = "{role.mode}"',
            )
        )
        if name == "guard":
            lines.append(f"enabled = {str(guard_enabled).lower()}")
        lines.append("")
        for fallback in role.fallback:
            lines.extend(
                (
                    f"[[roles.{name}.fallback]]",
                    f'harness = "{fallback.harness}"',
                    f'model = "{fallback.model}"',
                    f'reasoning_effort = "{fallback.reasoning_effort}"',
                    f'mode = "{fallback.mode}"',
                    "",
                )
            )
    return "\n".join(lines)


def test_new_and_legacy_defaults_resolve_identically():
    assert (
        parse_config(new_format_toml()).roles
        == parse_config(legacy_default_toml()).roles
    )


def test_user_pairing_gate_defaults_off_and_requires_a_boolean():
    assert parse_config(default_toml()).require_user_pairing is False
    assert configured_user_pairing(default_toml()) is False
    enabled_text = default_toml().replace(
        "require_user_pairing = false", "require_user_pairing = true"
    )
    assert parse_config(enabled_text).require_user_pairing is True
    assert configured_user_pairing(enabled_text) is True
    with pytest.raises(ConfigError, match="runner.require_user_pairing"):
        parse_config(
            default_toml().replace(
                "require_user_pairing = false", 'require_user_pairing = "yes"'
            )
        )


def test_runner_host_settings_remain_supported_in_config_file():
    text = (
        default_toml()
        .replace("require_user_pairing = false", "require_user_pairing = true")
        .replace("idle_process_timeout_s = 600", "idle_process_timeout_s = 900")
    )
    config = parse_config(text)
    assert config.require_user_pairing is True
    assert config.idle_process_timeout_s == 900


def test_codex_enablement_is_part_of_role_config_and_defaults_on():
    config = parse_config(default_toml())
    assert config.codex_app_server_enabled is True
    assert config.codex_app_server_binary is None
    enabled = parse_config(
        default_toml().replace(
            "[codex_app_server]\nenabled = true",
            '[codex_app_server]\nenabled = true\nbinary = "/opt/codex"',
        )
    )
    assert enabled.codex_app_server_enabled is True
    assert enabled.codex_app_server_binary == "/opt/codex"


def test_manager_bot_is_opt_in_and_can_be_enabled():
    text = default_toml()
    assert parse_config(text).resolve("manager-bot").enabled is False
    enabled = parse_config(
        text.replace(
            '[roles.manager-bot]\ntype = "standard"\nenabled = false',
            '[roles.manager-bot]\ntype = "standard"\nenabled = true',
        )
    )
    assert enabled.resolve("manager-bot").enabled is True


def test_current_legacy_shape_with_enabled_guard_and_hidden_mailman_loads():
    text = (
        legacy_default_toml(guard_enabled=True)
        + '\n[roles.mailman]\nharness = "pi"\nmodel = "legacy"\n'
    )
    config = parse_config(text)
    expected = dict(default_config().roles)
    guard = expected["guard"]
    expected["guard"] = type(guard)(
        guard.harness, guard.model, guard.reasoning_effort, guard.mode, (), True
    )
    assert dict(config.roles) == expected
    assert "mailman" not in config.roles


def test_legacy_role_mismatch_names_role_and_difference():
    with pytest.raises(ConfigError, match=r"roles.builder.*model.*gpt-6-luna"):
        parse_config(valid_toml("gpt-6-luna-custom"))


def test_role_type_rejects_overrides():
    text = new_format_toml().replace(
        'type = "light"', 'type = "light"\nmodel = "custom"', 1
    )
    with pytest.raises(
        ConfigError, match=r"roles.builder cannot override type settings: model"
    ):
        parse_config(text)


def test_type_fallback_chain_is_shared_by_roles():
    text = new_format_toml()
    # Add a second fallback to light and confirm builder and explorer both resolve it.
    text = text.replace(
        "[roles.builder]",
        "[[types.light.fallback]]\n"
        'harness = "pi"\nmodel = "second"\nreasoning_effort = "low"\n\n'
        "[roles.builder]",
    )
    config = parse_config(text)
    assert config.resolve("builder").fallback[-1].model == "second"
    assert config.resolve("explorer").fallback[-1].model == "second"


@pytest.mark.parametrize("type_name", TYPE_DEFINITIONS)
def test_each_type_has_its_fallback_chain(type_name):
    text = new_format_toml().replace(
        f'[roles.orchestrator]\ntype = "{DEFAULT_ROLE_TYPES["orchestrator"]}"',
        f'[roles.orchestrator]\ntype = "{type_name}"',
    )
    assert parse_config(text).resolve("orchestrator").fallback[0].model == (
        "opencode-go/deepseek-v4.1-flash"
    )


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (
            new_format_toml().replace(
                "[types.standard]", "[types.standard]\nmode = 'auto'"
            ),
            "mode is not configurable",
        ),
        (
            new_format_toml().replace(
                "[roles.builder]", "[roles.builder]\nmode = 'auto'"
            ),
            "cannot override type settings",
        ),
        (
            new_format_toml().replace('type = "light"', 'type = "missing"', 1),
            "unknown type",
        ),
        (
            new_format_toml().replace(
                'model = "gpt-6-luna"', 'fallbacks = []\nmodel = "gpt-6-luna"', 1
            ),
            "unknown keys: fallbacks",
        ),
        (
            new_format_toml().replace(
                'type = "light"', 'type = "light"\nenabled = false', 1
            ),
            "unknown keys: enabled",
        ),
        (
            valid_toml().replace(
                'model = "gpt-6-luna"', 'typo = true\nmodel = "gpt-6-luna"'
            ),
            "unknown keys: typo",
        ),
    ],
)
def test_config_rejects_invalid_keys_and_type_references(text, message):
    with pytest.raises(ConfigError, match=message):
        parse_config(text)


def test_type_key_without_types_table_has_clear_error():
    text = valid_toml().replace('harness = "codex-app-server"', 'type = "light"')
    with pytest.raises(
        ConfigError, match=r"roles.builder uses type but no \[types\] table"
    ):
        parse_config(text)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("fallback", 'model = "different"', "fallback"),
        ("mode", 'mode = "auto"', "mode"),
    ],
)
def test_legacy_mismatch_names_fallback_and_mode(field, value, message):
    text = legacy_default_toml()
    if field == "fallback":
        text = text.replace('model = "opencode-go/deepseek-v4.1-flash"', value, 1)
    else:
        text = text.replace('mode = "workspace-write"', value, 1)
    with pytest.raises(ConfigError, match=rf"roles\.[a-z]+.*{message}"):
        parse_config(text)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('model = "gpt-6-luna"', 'model = "gpt-6-sol"', "prohibited model"),
        ('harness = "codex-app-server"', 'harness = "unknown"', "unknown harness"),
    ],
)
def test_new_type_definitions_validate_never_models_and_harnesses(old, new, message):
    with pytest.raises(ConfigError, match=message):
        parse_config(new_format_toml().replace(old, new, 1))


def test_config_accepts_only_injected_harnesses() -> None:
    text = (
        new_format_toml()
        .replace('harness = "codex-app-server"', 'harness = "custom-harness"')
        .replace('harness = "opencode-http"', 'harness = "custom-harness"')
    )

    assert (
        parse_config(text, {"custom-harness", "claude-sdk"}).resolve("builder").harness
        == "custom-harness"
    )
    with pytest.raises(ConfigError, match="unknown harness"):
        parse_config(text, {"another-harness"})


def test_max_no_progress_restarts_defaults_to_three() -> None:
    assert parse_config(valid_toml()).max_no_progress_restarts == 3


def test_guard_is_optional_disabled_by_default_and_has_no_fallback():
    config = parse_config(valid_toml())
    assert config.guard() is None

    guard_text = new_format_toml()
    guard = parse_config(guard_text).roles["guard"]
    assert guard.enabled is False
    assert guard.mode == "read-only"
    assert guard.fallback == ()
    assert parse_config(guard_text).guard() is None

    enabled = parse_config(guard_text.replace("enabled = false", "enabled = true"))
    enabled_guard = enabled.guard()
    assert enabled_guard is not None
    assert enabled_guard.mode == "read-only"


def test_guard_accepts_configured_read_only_harness_even_when_disabled():
    text = new_format_toml().replace(
        '[roles.guard]\ntype = "standard"', '[roles.guard]\ntype = "light"'
    )
    assert parse_config(text).roles["guard"].harness == "codex-app-server"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("model", '"gpt-6-sol"', "prohibited model"),
        ("enabled", '"yes"', "enabled must be a boolean"),
    ],
)
def test_guard_validates_harness_prohibited_models_and_enabled(field, value, message):
    text = new_format_toml()
    if field == "model":
        text = text.replace('model = "claude-sonnet-5-5"', f"model = {value}")
    else:
        text = text.replace("enabled = false", f"enabled = {value}")
    with pytest.raises(ConfigError, match=message):
        parse_config(text)


@pytest.mark.parametrize("value", ["0", "-1", "true", '"3"'])
def test_max_no_progress_restarts_rejects_invalid_values(value: str) -> None:
    text = valid_toml().replace(
        "version = 1", f"version = 1\nmax_no_progress_restarts = {value}"
    )

    with pytest.raises(ConfigError, match="max_no_progress_restarts"):
        parse_config(text)


class Response:
    def __init__(self, status_code, content):
        self.status_code = status_code
        self.content = content
        self.text = content.decode()

    def json(self):
        return json.loads(self.content)


def app_request(app, method, path, *, content=b"", headers=None):
    async def dispatch():
        messages = []
        received = False

        async def receive():
            nonlocal received
            if received:
                return {"type": "http.disconnect"}
            received = True
            return {"type": "http.request", "body": content, "more_body": False}

        async def send(message):
            messages.append(message)

        await app(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": method,
                "scheme": "http",
                "path": path,
                "raw_path": path.encode(),
                "query_string": b"",
                "root_path": "",
                "headers": [
                    (key.lower().encode(), value.encode())
                    for key, value in (headers or {}).items()
                ],
                "client": ("127.0.0.1", 1234),
                "server": ("127.0.0.1", 80),
            },
            receive,
            send,
        )
        start = next(
            message for message in messages if message["type"] == "http.response.start"
        )
        body = b"".join(
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        )
        return Response(start["status"], body)

    return asyncio.run(dispatch())


@pytest.mark.parametrize(
    "text",
    [
        valid_toml("gpt-6-sol"),
        valid_toml().replace("codex-app-server", "unknown"),
        valid_toml().split("[[roles.builder.fallback]]")[0]
        + (
            '\n[policy]\nnever_models=["*-sol"]\n'
            'allow_fallback_only_on=["provider_limit"]\n'
            "create_paseo_projects=false\n"
        ),
    ],
)
def test_loader_rejects_sol_unknown_harness_and_empty_chain(tmp_path, text):
    path = tmp_path / "runner.toml"
    path.write_text(text)
    with pytest.raises(ConfigError):
        load_config(path)


@pytest.mark.parametrize(
    "text",
    [
        valid_toml().replace('model = "gpt-6-luna"', 'model = "GPT-6-SOL"'),
        valid_toml().replace(
            'reasoning_effort = "medium"', 'reasoning_effort = "extreme"'
        ),
        valid_toml().replace('mode = "workspace-write"', 'mode = "unrestricted-ish"'),
    ],
    ids=["case-insensitive-never-model", "unknown-reasoning-effort", "unknown-mode"],
)
def test_loader_rejects_case_insensitive_prohibited_model_and_unknown_values(
    tmp_path, text
):
    path = tmp_path / "runner.toml"
    path.write_text(text)
    with pytest.raises(ConfigError):
        load_config(path)


MAILMAN_TABLE = '[roles.mailman]\nharness = "pi"\nmodel = "x"\n'


def test_mailman_is_not_a_default_role():
    assert "mailman" not in default_config().roles


def test_loader_ignores_unknown_role_tables(tmp_path):
    path = tmp_path / "runner.toml"
    path.write_text(valid_toml().replace("[policy]", MAILMAN_TABLE + "\n[policy]"))
    config = load_config(path)
    assert config.resolve("builder").model == "gpt-6-luna"
    assert config.resolve("manager-bot").enabled is False


def test_loader_fills_omitted_live_roles_and_types_from_defaults():
    fixture = Path(__file__).parent / "fixtures" / "live_runner_legacy.toml"
    config = load_config(fixture)

    assert config.resolve("manager-bot").enabled is False
    assert config.resolve("orchestrator").harness == "claude-cli"
    assert config.resolve("builder").harness == "codex-app-server"


def test_loader_rejects_typoed_role_names(tmp_path):
    path = tmp_path / "runner.toml"
    path.write_text(valid_toml().replace("[roles.builder", "[roles.buidler"))
    with pytest.raises(ConfigError, match="unknown role: buidler"):
        load_config(path)


def test_unknown_role_detection_accepts_quoted_known_names():
    quoted = valid_toml().replace("[roles.builder]", '[roles."builder"]')
    assert unknown_role_blocks(quoted) == ""


def test_loader_requires_one_known_role(tmp_path):
    path = tmp_path / "runner.toml"
    only_unknown = valid_toml().replace("[roles.builder", "[roles.mailman")
    path.write_text(only_unknown)
    with pytest.raises(ConfigError, match="at least one role"):
        load_config(path)


def test_keep_unknown_roles_appends_once_and_leaves_known_roles_out():
    existing = valid_toml() + "\n" + MAILMAN_TABLE
    merged = keep_unknown_roles(valid_toml("gpt-6-luna-new"), existing)
    assert merged.count("[roles.mailman]") == 1
    assert merged.count("[roles.builder]") == 1
    assert keep_unknown_roles(merged, existing) == merged
    assert keep_unknown_roles(valid_toml(), valid_toml()) == valid_toml()


def test_runner_config_directory_uses_override(monkeypatch, tmp_path):
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    assert config_dir() == tmp_path
    assert config_path() == tmp_path / "runner.toml"


def test_live_instance_limit_defaults_to_eight():
    assert parse_config(default_toml()).max_live_instances == 8


@pytest.mark.parametrize("value", [0, -1, "true"])
def test_live_instance_limit_must_be_integer_at_least_one(value):
    text = default_toml().replace(
        "max_live_instances = 8", f"max_live_instances = {value}"
    )
    with pytest.raises(ConfigError, match=r"limits.max_live_instances.*integer >= 1"):
        parse_config(text)


def test_configured_role_and_fallback_are_immutable_snapshots(tmp_path):
    path = tmp_path / "runner.toml"
    path.write_text(default_toml())
    old = load_config(path).resolve("builder")
    path.write_text(
        path.read_text().replace('model = "gpt-6-luna"', 'model = "gpt-6-luna-new"')
    )
    new = load_config(path).resolve("builder")
    assert old.model == "gpt-6-luna"
    assert new.model == "gpt-6-luna-new"
    assert new.fallback[0].harness == "opencode-http"


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            {"error": {"type": "usage_limit_exceeded", "message": "quota exhausted"}},
            True,
        ),
        (
            {
                "error": {
                    "code": "rate_limit_exceeded",
                    "message": "usage limit reached",
                }
            },
            True,
        ),
        (TimeoutError("timed out"), False),
        ({"status": 401, "message": "unauthorized"}, False),
        ({"status": 429}, False),
        ({"error": {"type": "permission_denied"}}, False),
        (RuntimeError("process crashed"), False),
    ],
    ids=[
        "quota-fixture-v1",
        "rate-limit-fixture-v1",
        "timeout",
        "auth",
        "bare-429",
        "permission-denial",
        "crash",
    ],
)
def test_limit_classifier_only_advances_for_structured_quota_payloads(error, expected):
    assert classify_limit_error(error) is expected


def test_check_drift_does_not_write_input_files(tmp_path):
    config = tmp_path / "runner.toml"
    agent = tmp_path / "varde-builder.toml"
    capabilities = tmp_path / "capabilities.json"
    config.write_text(valid_toml())
    agent_text = (
        'model = "old-model"\nmodel_reasoning_effort = "high"\n'
        'sandbox_mode = "read-only"\n'
    )
    agent.write_text(agent_text)
    capabilities.write_text(
        json.dumps(
            {
                "profiles": [
                    {
                        "name": "varde-builder",
                        "models": {
                            "codex": {
                                "model": "old-capability-model",
                                "reasoning_effort": "high",
                                "sandbox_mode": "read-only",
                            }
                        },
                    }
                ]
            }
        )
    )
    paths = (config, agent, capabilities)
    before = {path: path.stat().st_mtime_ns for path in paths}
    report = check_drift(config, [agent], capabilities)
    after = {path: path.stat().st_mtime_ns for path in paths}
    assert "varde-builder.toml" in report
    assert "reasoning_effort" in report
    assert "mode" in report
    assert "capabilities.json:varde-builder" in report
    agent_line = next(
        line for line in report.splitlines() if "varde-builder.toml" in line
    )
    capability_line = next(
        line
        for line in report.splitlines()
        if "capabilities.json:varde-builder" in line
    )
    for field in ("model", "reasoning_effort", "mode"):
        assert field in agent_line
        assert field in capability_line
    assert before == after


def test_editor_browser_viewports(
    tmp_path,
    monkeypatch,
    shared_browser_page,
    browser_server,
    browser_screenshot_dir,
):
    from varde_runner.web import create_app

    class EmptyCLI:
        def read_messages(self):
            return []

        def read_plan(self):
            return {"plans": []}

        def send(self, **kwargs):
            return {}

    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    app = create_app(data_dir=tmp_path / "data", cli=EmptyCLI())
    page = shared_browser_page
    origin = browser_server(app)
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{origin}/")
    page.evaluate("localStorage.clear(); sessionStorage.clear()")
    page.goto(f"{origin}/roles")
    assert page.locator("body").evaluate("el => el.scrollWidth") <= 390
    for control in page.locator("button:visible, textarea:visible").all():
        box = control.bounding_box()
        assert box and box["height"] >= 44
    page.screenshot(
        path=str(browser_screenshot_dir / "roles-390x844.png"), full_page=True
    )
    page.set_viewport_size({"width": 1440, "height": 900})
    assert page.locator("body").evaluate("el => el.scrollWidth") <= 1440
    page.screenshot(
        path=str(browser_screenshot_dir / "roles-1440x900.png"), full_page=True
    )


def test_configured_allowed_hosts_reads_top_level_list() -> None:
    assert configured_allowed_hosts('allowed_hosts = ["a.ts.net", "b"]') == (
        "a.ts.net",
        "b",
    )
    assert configured_allowed_hosts("version = 1") == ()


def test_configured_allowed_hosts_rejects_non_strings() -> None:
    with pytest.raises(ConfigError, match="allowed_hosts"):
        configured_allowed_hosts("allowed_hosts = [1]")
