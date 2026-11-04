from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from test_web import app_request
from varde_runner.bot_lifecycle import ManagerBotLifecycle
from varde_runner.config import default_config, default_toml, load_config
from varde_runner.harness_map import paseo_settings
from varde_runner.plugins import RunnerCapabilities, SessionRef, SessionSpec
from varde_runner.supervisor import Supervisor
from varde_runner.web import app as web_app
from varde_runner.web import create_app
from varde_runner.web import registry as web_registry

REAL_LIST_MODELS_FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "paseo-list-models-codex.json").read_text()
)


def _runner_config_without_manager_bot() -> str:
    return default_toml().replace(
        '[roles.manager-bot]\ntype = "standard"\nenabled = false\n\n', ""
    )


def test_startup_missing_manager_role_disables_bot_without_traceback(
    tmp_path, monkeypatch, caplog
):
    config = tmp_path / "runner.toml"
    config.write_text(_runner_config_without_manager_bot(), encoding="utf-8")
    monkeypatch.setattr(web_app, "config_path", lambda: config)
    monkeypatch.setattr(web_registry.PaseoPlugin, "from_environment", object)
    polls = []

    async def run_manager(_self):
        polls.append("run")

    monkeypatch.setattr(ManagerBotLifecycle, "run", run_manager)

    class FakeSupervisor:
        def __init__(self, *_args):
            self.store = SimpleNamespace(sessions=list)

        async def start(self):
            pass

        async def shutdown(self):
            pass

    monkeypatch.setattr(web_app, "Supervisor", FakeSupervisor)
    app = create_app(data_dir=tmp_path / "data", cli=EmptyCLI())
    caplog.set_level("DEBUG", logger=web_app.__name__)

    async def start_app():
        async with app.router.lifespan_context(app):
            assert app.state.manager_lifecycle is not None

    asyncio.run(start_app())

    messages = [record.getMessage() for record in caplog.records]
    assert not any(record.levelname == "ERROR" for record in caplog.records)
    assert not any("Traceback" in message for message in messages)
    assert messages.count("manager bot is disabled: manager-bot role is absent") == 1
    assert polls == []


def test_startup_present_manager_role_keeps_start_behavior(tmp_path, monkeypatch):
    config = tmp_path / "runner.toml"
    config.write_text(
        default_toml().replace(
            '[roles.manager-bot]\ntype = "standard"\nenabled = false',
            '[roles.manager-bot]\ntype = "standard"\nenabled = true',
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(web_app, "config_path", lambda: config)
    monkeypatch.setattr(web_registry.PaseoPlugin, "from_environment", object)
    starts = []
    polls = []

    async def start_manager(_self):
        starts.append("start")

    async def run_manager(_self):
        polls.append("run")

    monkeypatch.setattr(ManagerBotLifecycle, "start", start_manager)
    monkeypatch.setattr(ManagerBotLifecycle, "run", run_manager)

    class FakeSupervisor:
        def __init__(self, *_args):
            self.store = SimpleNamespace(sessions=list)

        async def start(self):
            pass

        async def shutdown(self):
            pass

    monkeypatch.setattr(web_app, "Supervisor", FakeSupervisor)
    app = create_app(data_dir=tmp_path / "data", cli=EmptyCLI())

    async def start_app():
        async with app.router.lifespan_context(app):
            await asyncio.sleep(0)

    asyncio.run(start_app())
    assert starts == ["start"]
    assert polls == ["run"]


def test_paseo_model_catalog_subprocess_success(monkeypatch):
    async def communicate():
        return json.dumps(REAL_LIST_MODELS_FIXTURE).encode(), b""

    async def create_subprocess(*args, **kwargs):
        return SimpleNamespace(communicate=communicate, returncode=0)

    monkeypatch.setattr(web_app.asyncio, "create_subprocess_exec", create_subprocess)

    assert asyncio.run(web_app._paseo_model_catalog()) == REAL_LIST_MODELS_FIXTURE


def test_paseo_model_catalog_subprocess_timeout(monkeypatch):
    async def communicate():
        await asyncio.sleep(1)
        return b"{}", b""

    async def create_subprocess(*args, **kwargs):
        async def wait():
            return None

        return SimpleNamespace(communicate=communicate, kill=lambda: None, wait=wait)

    monkeypatch.setattr(web_app.asyncio, "create_subprocess_exec", create_subprocess)

    async def timeout(awaitable, **kwargs):
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr(web_app.asyncio, "wait_for", timeout)

    with pytest.raises(RuntimeError, match="timed out"):
        asyncio.run(web_app._paseo_model_catalog())


def test_paseo_model_catalog_subprocess_failure(monkeypatch):
    async def communicate():
        return b"", b"sidecar failed"

    async def create_subprocess(*args, **kwargs):
        return SimpleNamespace(communicate=communicate, returncode=1)

    monkeypatch.setattr(web_app.asyncio, "create_subprocess_exec", create_subprocess)

    with pytest.raises(RuntimeError, match="sidecar failed"):
        asyncio.run(web_app._paseo_model_catalog())


def test_create_app_default_work_item_starter_starts_one_supervisor(
    tmp_path, monkeypatch
):
    plugin = object()
    monkeypatch.setattr(web_registry.PaseoPlugin, "from_environment", lambda: plugin)
    created = []

    class FakeSupervisor:
        store = SimpleNamespace(sessions=list)
        data_dir = tmp_path / "fake-state"

        def approval_waits_for_mailbox(self):
            return []

        def __init__(self, data_dir, plugins):
            self.data_dir = data_dir
            self.plugins = plugins
            self.started = 0
            self.planner_calls = []
            self.shutdown_calls = 0
            created.append(self)

        async def start(self):
            self.started += 1

        async def start_planner_session(self, item_id, notes_path, project):
            self.planner_calls.append((item_id, notes_path, project))
            return SessionRef("codex", "planner-session")

        async def shutdown(self):
            self.shutdown_calls += 1

    monkeypatch.setattr(web_app, "Supervisor", FakeSupervisor)
    app = create_app(
        data_dir=tmp_path / "data",
        cli=EmptyCLI(),
    )

    response = app_request(
        app,
        "POST",
        "/api/work-items",
        content=json.dumps(
            {
                "text": "Plan this",
                "idempotency_key": "key-1",
                "project": str(tmp_path),
            }
        ).encode(),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 200
    assert response.json()["planner_session"] == "planner-session"
    second_response = app_request(
        app,
        "POST",
        "/api/work-items",
        content=json.dumps(
            {
                "text": "Plan another thing",
                "idempotency_key": "key-2",
                "project": str(tmp_path),
            }
        ).encode(),
        headers={"content-type": "application/json"},
    )

    assert second_response.status_code == 200
    assert len(created) == 1
    assert created[0].data_dir == tmp_path / "data" / "sessions"
    assert created[0].started == 1
    assert len(created[0].plugins.plugins()) == 5
    assert len(created[0].planner_calls) == 2

    async def close_app():
        async with app.router.lifespan_context(app):
            pass

    asyncio.run(close_app())
    assert created[0].shutdown_calls == 1


def test_create_app_retries_supervisor_after_start_failure(tmp_path, monkeypatch):
    class FakePlugin:
        async def close(self):
            return None

    monkeypatch.setattr(web_registry.PaseoPlugin, "from_environment", FakePlugin)
    created = []

    class FakeSupervisor:
        store = SimpleNamespace(sessions=list)
        data_dir = tmp_path / "fake-state"

        def approval_waits_for_mailbox(self):
            return []

        def __init__(self, data_dir, plugins):
            self.start_calls = 0
            self.shutdown_calls = 0
            created.append(self)

        async def start(self):
            self.start_calls += 1
            if len(created) == 1:
                raise RuntimeError("startup failed")

        async def start_planner_session(self, item_id, notes_path, project):
            return SessionRef("codex", "planner-session")

        async def shutdown(self):
            self.shutdown_calls += 1

    monkeypatch.setattr(web_app, "Supervisor", FakeSupervisor)
    app = create_app(data_dir=tmp_path / "data", cli=EmptyCLI())

    def submit(key):
        return app_request(
            app,
            "POST",
            "/api/work-items",
            content=json.dumps(
                {"text": "Plan this", "idempotency_key": key, "project": str(tmp_path)}
            ).encode(),
            headers={"content-type": "application/json"},
        )

    assert submit("startup-retry-1").status_code == 503
    assert submit("startup-retry-2").status_code == 200
    assert len(created) == 2
    assert app.state.supervisor is created[1]

    async def close_app():
        async with app.router.lifespan_context(app):
            pass

    asyncio.run(close_app())
    assert created[1].shutdown_calls == 1


def test_dashboard_lifespan_keeps_supervisor_lazy_after_start_failure(
    tmp_path, monkeypatch
):
    class BrokenSupervisor:
        def __init__(self, *_args):
            self.start_calls = 0

        async def start(self):
            self.start_calls += 1
            raise OSError("Paseo unavailable")

        async def shutdown(self):
            pass

    monkeypatch.setattr(web_app, "Supervisor", BrokenSupervisor)
    app = create_app(data_dir=tmp_path / "data", cli=EmptyCLI())

    async def exercise():
        async with app.router.lifespan_context(app):
            assert getattr(app.state, "supervisor", None) is None

    asyncio.run(exercise())


class EmptyCLI:
    models: Callable[[], Any] | None = None

    def read_messages(self):
        return []

    def read_plan(self):
        return {"plans": []}

    def send(self, **kwargs):
        return {}


class RecordingPlugin:
    capabilities = RunnerCapabilities()

    def __init__(self):
        self.specs = []

    async def start(self, spec):
        self.specs.append(spec)
        return SessionRef("fake", f"session-{len(self.specs)}")

    async def resume(self, ref):
        return ref

    async def send(self, ref, prompt):
        return None

    async def events(self, ref):
        if False:
            yield None

    async def respond_permission(self, ref, request_id, decision):
        return None

    async def stop(self, ref):
        return None

    async def close(self):
        return None


def config_text(model="gpt-6-luna"):
    return f'''version = 1
[types.standard]
harness = "claude-sdk"
model = "claude-sonnet-5-5"
reasoning_effort = "medium"

[[types.standard.fallback]]
harness = "opencode-http"
model = "opencode-go/deepseek-v4.1-flash"
reasoning_effort = "high"

[types.heavy]
harness = "claude-sdk"
model = "claude-sonnet-5-5"
reasoning_effort = "high"

[[types.heavy.fallback]]
harness = "opencode-http"
model = "opencode-go/deepseek-v4.1-flash"
reasoning_effort = "high"

[types.light]
harness = "codex-app-server"
model = "{model}"
reasoning_effort = "medium"

[[types.light.fallback]]
harness = "opencode-http"
model = "opencode-go/deepseek-v4.1-flash"
reasoning_effort = "high"

[roles.builder]
type = "light"
[opencode_http]
enabled = true
[policy]
never_models = ["*-sol"]
allow_fallback_only_on = ["provider_limit"]
create_paseo_projects = false
'''


def legacy_config_text():
    return """version = 1
[roles.builder]
harness = "codex-app-server"
model = "gpt-6-luna"
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
"""


def app_with_models(data_dir, models, cli=None):
    resolved_cli = cli or EmptyCLI()
    resolved_cli.models = models
    return create_app(data_dir=data_dir, cli=resolved_cli)


def test_invalid_config_post_is_4xx_and_preserves_file(tmp_path, monkeypatch):
    path = tmp_path / "runner.toml"
    original = config_text()
    path.write_text(original)
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    app = create_app(data_dir=tmp_path / "data", cli=EmptyCLI())
    invalid_configs = (
        config_text("gpt-6-sol"),
        config_text().replace("codex-app-server", "unknown"),
        config_text().replace(
            '\n[[types.light.fallback]]\nharness = "opencode-http"\n'
            'model = "opencode-go/deepseek-v4.1-flash"\n'
            'reasoning_effort = "high"\n',
            "\n",
        ),
    )
    for invalid in invalid_configs:
        response = app_request(
            app,
            "POST",
            "/api/roles/preview",
            content=json.dumps({"toml": invalid}).encode(),
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 400
        assert path.read_text() == original


def test_valid_config_post_is_atomic_backed_up_and_visible_to_new_resolver(
    tmp_path, monkeypatch
):
    path = tmp_path / "runner.toml"
    path.write_text(config_text())
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    existing_session = load_config(path).resolve("builder")
    from varde_runner.web import roles

    replaced = []
    real_replace = roles.os.replace

    def observe_replace(source, target):
        replaced.append((Path(source), Path(target)))
        return real_replace(source, target)

    monkeypatch.setattr(roles.os, "replace", observe_replace)
    app = create_app(data_dir=tmp_path / "data", cli=EmptyCLI())
    proposed = config_text("gpt-6-luna-new")
    preview = app_request(
        app,
        "POST",
        "/api/roles/preview",
        content=json.dumps({"toml": proposed}).encode(),
        headers={"content-type": "application/json"},
    )
    assert preview.status_code == 200
    assert path.read_text() == config_text()
    preview_token = preview.json()["preview_token"]
    response = app_request(
        app,
        "POST",
        "/api/roles/save",
        content=json.dumps({"toml": proposed, "preview_token": preview_token}).encode(),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 200
    assert replaced and replaced[-1][1] == path
    backup = next(iter(tmp_path.glob("runner.toml.*.bak")), None)
    assert backup and backup.read_text() == config_text()
    assert existing_session.model == "gpt-6-luna"
    assert load_config(path).resolve("builder").model == "gpt-6-luna-new"


MAILMAN_TABLES = """[roles.mailman]
# legacy role, no longer managed
harness = "pi"
model = "keep-me"
reasoning_effort = "low"
mode = "auto"

[[roles.mailman.fallback]]
harness = "pi"
model = "keep-me-too"
reasoning_effort = "low"
mode = "auto"
"""


def test_save_keeps_unknown_role_tables_untouched(tmp_path, monkeypatch):
    path = tmp_path / "runner.toml"
    original = config_text() + "\n" + MAILMAN_TABLES
    path.write_text(original)
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    app = create_app(data_dir=tmp_path / "data", cli=EmptyCLI())
    roles = app_request(app, "GET", "/api/roles").json()["roles"]
    assert list(roles) == ["builder", "guard"]
    proposed = config_text("gpt-6-luna-new")
    body = json.dumps({"toml": proposed}).encode()
    headers = {"content-type": "application/json"}
    preview = app_request(
        app, "POST", "/api/roles/preview", content=body, headers=headers
    )
    assert preview.status_code == 200
    assert "mailman" not in "".join(
        line for line in preview.json()["diff"].splitlines() if line.startswith("-")
    )
    save_body = json.dumps(
        {"toml": proposed, "preview_token": preview.json()["preview_token"]}
    ).encode()
    saved = app_request(
        app, "POST", "/api/roles/save", content=save_body, headers=headers
    )
    assert saved.status_code == 200
    text = path.read_text()
    assert MAILMAN_TABLES.strip() in text
    assert load_config(path).resolve("builder").model == "gpt-6-luna-new"


def test_save_migrates_legacy_file_and_preserves_hidden_role(tmp_path, monkeypatch):
    path = tmp_path / "runner.toml"
    original = legacy_config_text() + MAILMAN_TABLES
    path.write_text(original)
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    app = create_app(data_dir=tmp_path / "data", cli=EmptyCLI())
    proposed = config_text()
    headers = {"content-type": "application/json"}

    preview = app_request(
        app,
        "POST",
        "/api/roles/preview",
        content=json.dumps({"toml": proposed}).encode(),
        headers=headers,
    )

    assert preview.status_code == 200
    assert "[types.standard]" in preview.json()["diff"]
    assert "mailman" not in "".join(
        line for line in preview.json()["diff"].splitlines() if line.startswith("-")
    )
    saved = app_request(
        app,
        "POST",
        "/api/roles/save",
        content=json.dumps(
            {"toml": proposed, "preview_token": preview.json()["preview_token"]}
        ).encode(),
        headers=headers,
    )

    assert saved.status_code == 200
    assert "[types.standard]" in path.read_text()
    assert MAILMAN_TABLES.strip() in path.read_text()


def test_guard_role_round_trip_preserves_existing_role_text(tmp_path, monkeypatch):
    path = tmp_path / "runner.toml"
    original = config_text()
    path.write_text(original)
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    app = create_app(data_dir=tmp_path / "data", cli=EmptyCLI())
    guard = '[roles.guard]\ntype = "standard"\nenabled = false\n\n'
    proposed = original.replace("[policy]", guard + "[policy]")
    headers = {"content-type": "application/json"}
    payload = json.dumps({"toml": proposed}).encode()
    preview = app_request(
        app, "POST", "/api/roles/preview", content=payload, headers=headers
    )
    assert preview.status_code == 200
    saved = app_request(
        app,
        "POST",
        "/api/roles/save",
        content=json.dumps(
            {"toml": proposed, "preview_token": preview.json()["preview_token"]}
        ).encode(),
        headers=headers,
    )
    assert saved.status_code == 200
    saved_text = path.read_text()
    assert saved_text.partition("[roles.guard]")[0] == original.partition("[policy]")[0]
    assert load_config(path).guard() is None


def test_roles_api_returns_guard_enabled_state_and_default_config_has_off_guard(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path / "missing"))
    app = create_app(data_dir=tmp_path / "data", cli=EmptyCLI())
    roles = app_request(app, "GET", "/api/roles").json()["roles"]
    assert roles["guard"]["enabled"] is False
    assert roles["guard"]["type"] == "light"
    assert roles["guard"]["model"] == "gpt-6-luna"
    assert roles["guard"]["mode"] == "read-only"
    assert roles["guard"]["fallback"] == []
    assert roles["manager-bot"]["enabled"] is False


def test_roles_api_returns_manager_bot_enabled_state(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config = config_dir / "runner.toml"
    config.write_text(
        default_toml().replace(
            '[roles.manager-bot]\ntype = "standard"\nenabled = false',
            '[roles.manager-bot]\ntype = "standard"\nenabled = true',
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(config_dir))
    app = create_app(data_dir=tmp_path / "data", cli=EmptyCLI())

    roles = app_request(app, "GET", "/api/roles").json()["roles"]

    assert roles["manager-bot"]["enabled"] is True


def test_roles_api_reports_whether_file_has_guard(tmp_path, monkeypatch):
    path = tmp_path / "runner.toml"
    path.write_text(config_text())
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    app = create_app(data_dir=tmp_path / "data", cli=EmptyCLI())
    without = app_request(app, "GET", "/api/roles").json()
    assert without["guard_in_file"] is False
    assert without["legacy"] is False
    assert without["types"]["light"]["model"] == "gpt-6-luna"
    assert "guard" in without["roles"]
    assert without["roles"]["guard"]["type"] == "light"
    guard = '[roles.guard]\ntype = "light"\nenabled = true\n\n'
    text = config_text().replace(
        "[codex_app_server]\nenabled = false",
        "[codex_app_server]\nenabled = true",
    )
    path.write_text(text.replace("[policy]", guard + "[policy]"))
    assert app_request(app, "GET", "/api/roles").json()["guard_in_file"] is True


def test_roles_api_resolves_guard_using_nonstandard_type(tmp_path, monkeypatch):
    path = tmp_path / "runner.toml"
    text = config_text().replace(
        "[roles.builder]",
        '[roles.guard]\ntype = "heavy"\nenabled = false\n\n[roles.builder]',
    )
    path.write_text(text)
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    app = create_app(data_dir=tmp_path / "data", cli=EmptyCLI())

    guard = app_request(app, "GET", "/api/roles").json()["roles"]["guard"]

    assert guard["type"] == "heavy"
    assert guard["harness"] == "claude-sdk"
    assert guard["model"] == "claude-sonnet-5-5"
    assert guard["reasoning_effort"] == "high"
    assert guard["mode"] == "read-only"
    assert guard["fallback"] == []
    assert guard["enabled"] is False
    payload = app_request(app, "GET", "/api/roles").json()
    assert payload["types"]["heavy"]["guard_eligible"] is False


def test_roles_api_returns_types_and_resolved_role_settings(tmp_path, monkeypatch):
    path = tmp_path / "runner.toml"
    path.write_text(config_text("gpt-6-luna-custom"))
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    app = create_app(data_dir=tmp_path / "data", cli=EmptyCLI())

    payload = app_request(app, "GET", "/api/roles").json()

    assert payload["types"]["light"] == {
        "harness": "codex-app-server",
        "model": "gpt-6-luna-custom",
        "reasoning_effort": "medium",
        "fallback": [
            {
                "harness": "opencode-http",
                "model": "opencode-go/deepseek-v4.1-flash",
                "reasoning_effort": "high",
            }
        ],
        "guard_eligible": True,
    }
    assert payload["roles"]["builder"] == {
        "type": "light",
        "harness": "codex-app-server",
        "model": "gpt-6-luna-custom",
        "reasoning_effort": "medium",
        "mode": "workspace-write",
        "fallback": [
            {
                "harness": "opencode-http",
                "model": "opencode-go/deepseek-v4.1-flash",
                "reasoning_effort": "high",
                "mode": "workspace-write",
            }
        ],
    }


def test_roles_api_returns_legacy_file_as_is_with_builtin_type_mapping(
    tmp_path, monkeypatch
):
    path = tmp_path / "runner.toml"
    original = legacy_config_text()
    path.write_text(original)
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    app = create_app(data_dir=tmp_path / "data", cli=EmptyCLI())

    payload = app_request(app, "GET", "/api/roles").json()

    assert payload["legacy"] is True
    assert payload["toml"] == original
    assert payload["roles"]["builder"]["type"] == "light"
    assert payload["types"]["light"]["model"] == "gpt-6-luna"
    assert payload["roles"]["guard"]["type"] == "light"
    assert payload["roles"]["guard"]["harness"] == "codex-app-server"
    assert payload["roles"]["guard"]["enabled"] is False
    assert "mailman" not in payload["roles"]


def test_roles_api_uses_edited_default_type_for_absent_guard(tmp_path, monkeypatch):
    path = tmp_path / "runner.toml"
    path.write_text(
        config_text("gpt-6-luna-custom").replace(
            'model = "claude-sonnet-5-5"', 'model = "claude-standard-custom"', 1
        )
    )
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    app = create_app(data_dir=tmp_path / "data", cli=EmptyCLI())

    guard = app_request(app, "GET", "/api/roles").json()["roles"]["guard"]

    assert guard["type"] == "light"
    assert guard["harness"] == "codex-app-server"
    assert guard["model"] == "gpt-6-luna-custom"
    assert guard["reasoning_effort"] == "medium"
    assert guard["mode"] == "read-only"
    assert guard["fallback"] == []
    assert guard["enabled"] is False


def test_roles_api_invalid_config_returns_editor_payload(tmp_path, monkeypatch):
    path = tmp_path / "runner.toml"
    invalid = config_text().replace('type = "light"', 'type = "unknown"', 1)
    path.write_text(invalid)
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    app = create_app(data_dir=tmp_path / "data", cli=EmptyCLI())

    response = app_request(app, "GET", "/api/roles")

    assert response.status_code == 200
    assert response.json() == {
        "toml": invalid,
        "error": "roles.builder has unknown type: 'unknown'",
        "legacy": False,
        "guard_in_file": False,
        "types": {},
        "roles": {},
    }


def test_unknown_type_reference_is_rejected_by_preview_and_save(tmp_path, monkeypatch):
    path = tmp_path / "runner.toml"
    original = config_text()
    path.write_text(original)
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    app = create_app(data_dir=tmp_path / "data", cli=EmptyCLI())
    invalid = original.replace('type = "light"', 'type = "missing"')
    headers = {"content-type": "application/json"}

    preview = app_request(
        app,
        "POST",
        "/api/roles/preview",
        content=json.dumps({"toml": invalid}).encode(),
        headers=headers,
    )
    saved = app_request(
        app,
        "POST",
        "/api/roles/save",
        content=json.dumps({"toml": invalid, "preview_token": "unused"}).encode(),
        headers=headers,
    )

    assert preview.status_code == 400
    assert saved.status_code == 400
    assert path.read_text() == original


def test_role_preview_tokens_are_isolated_and_single_use(tmp_path, monkeypatch):
    path = tmp_path / "runner.toml"
    original = config_text()
    path.write_text(original)
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    app = create_app(data_dir=tmp_path / "data", cli=EmptyCLI())
    first_text = config_text("gpt-6-luna-first")
    second_text = config_text("gpt-6-luna-second")

    def preview(text):
        return app_request(
            app,
            "POST",
            "/api/roles/preview",
            content=json.dumps({"toml": text}).encode(),
            headers={"content-type": "application/json"},
        )

    first = preview(first_text)
    second = preview(second_text)
    first_token = first.json()["preview_token"]
    second_token = second.json()["preview_token"]
    assert first_token != second_token
    assert path.read_text() == original

    wrong_confirmation = app_request(
        app,
        "POST",
        "/api/roles/save",
        content=json.dumps(
            {"toml": first_text, "preview_token": second_token}
        ).encode(),
        headers={"content-type": "application/json"},
    )
    assert wrong_confirmation.status_code == 409
    assert path.read_text() == original

    for text, token in ((first_text, first_token), (second_text, second_token)):
        response = app_request(
            app,
            "POST",
            "/api/roles/save",
            content=json.dumps({"toml": text, "preview_token": token}).encode(),
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 200


def test_role_routes_are_exact_and_missing_file_is_read_only(
    tmp_path, monkeypatch, runner_ui_built
):
    config_dir = tmp_path / "config"
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(config_dir))
    app = create_app(data_dir=tmp_path / "data", cli=EmptyCLI())
    editor = app_request(app, "GET", "/roles")
    assert editor.status_code == 200
    assert "<html" in editor.text.lower()
    assert not (config_dir / "runner.toml").exists()

    for path, method in (("/rolesXYZ", "GET"), ("/roles/anything", "POST")):
        response = app_request(app, method, path, content=b"{}")
        assert response.status_code == 404
    assert app_request(app, "POST", "/roles", content=b"{}").status_code == 405


def test_default_orchestrator_uses_paseo_claude_provider():
    role = default_config().resolve("orchestrator")
    settings = paseo_settings(
        {
            "harness": role.harness,
            "model": role.model,
            "reasoning_effort": role.reasoning_effort,
            "mode": role.mode,
        }
    )
    assert settings["paseo_provider"] is not None
    assert settings["model"] is not None
    assert settings["paseo_provider"] == "claude"
    assert role.model == "claude-sonnet-5-5"


def test_existing_supervisor_session_keeps_launch_spec_after_config_save(
    tmp_path, monkeypatch
):
    path = tmp_path / "runner.toml"
    path.write_text(config_text())
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    role = load_config(path).resolve("builder")
    settings = paseo_settings(
        {
            "harness": role.harness,
            "model": role.model,
            "reasoning_effort": role.reasoning_effort,
            "mode": role.mode,
        }
    )
    assert settings["paseo_provider"] is not None
    assert settings["model"] is not None
    launch_spec = SessionSpec(
        provider=settings["paseo_provider"],
        model=settings["model"],
        workspace_id="workspace",
        cwd=str(tmp_path),
        reasoning_effort=settings["thinking_option_id"],
        mode_id=settings["mode_id"],
    )
    plugin = RecordingPlugin()
    supervisor = Supervisor(tmp_path / "sessions", {"codex": plugin})
    asyncio.run(supervisor.start_session(launch_spec, "builder"))
    original_launch_spec = copy.deepcopy(plugin.specs[0])

    app = create_app(data_dir=tmp_path / "data", cli=EmptyCLI())
    proposed = config_text("gpt-6-luna-updated")
    preview_token = app_request(
        app,
        "POST",
        "/api/roles/preview",
        content=json.dumps({"toml": proposed}).encode(),
        headers={"content-type": "application/json"},
    ).json()["preview_token"]
    saved = app_request(
        app,
        "POST",
        "/api/roles/save",
        content=json.dumps({"toml": proposed, "preview_token": preview_token}).encode(),
        headers={"content-type": "application/json"},
    )
    assert saved.status_code == 200
    assert plugin.specs[0] == original_launch_spec
    assert load_config(path).resolve("builder").model == "gpt-6-luna-updated"
    asyncio.run(supervisor.shutdown())


def test_backup_rotation_keeps_only_five_previous_configs(tmp_path):
    from varde_runner.web.roles import _write_config

    path = tmp_path / "runner.toml"
    path.write_text(config_text("gpt-6-luna-initial"))
    for index in range(7):
        _write_config(path, config_text(f"gpt-6-luna-{index}"))
    backups = sorted(tmp_path.glob("runner.toml.*.bak"))
    assert len(backups) == 5
    assert path.read_text() == config_text("gpt-6-luna-6")


def test_roles_editor_renders_preview_and_controls(
    tmp_path, monkeypatch, runner_ui_built
):
    path = tmp_path / "runner.toml"
    path.write_text(config_text())
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    app = create_app(data_dir=tmp_path / "data", cli=EmptyCLI())
    response = app_request(app, "GET", "/roles")
    assert response.status_code == 200
    assert "<html" in response.text.lower()
    role_data = app_request(app, "GET", "/api/roles").json()
    assert "gpt-6-luna" in role_data["toml"]


def test_role_models_use_real_paseo_shape_and_preserve_exact_ids(tmp_path, monkeypatch):
    path = tmp_path / "runner.toml"
    path.write_text(config_text("gpt-6-luna"))
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    catalog = {
        "codex": {
            "provider": "codex",
            "models": [
                {
                    "provider": "codex",
                    "id": "gpt-6-luna",
                    "label": "GPT-6 Luna",
                    "thinkingOptions": [{"id": "medium", "label": "Medium"}],
                    "defaultThinkingOptionId": "medium",
                },
                {
                    "provider": "codex",
                    "id": "gpt-6-astra-preview[1m]",
                    "label": "Astra Preview 1M",
                    "thinkingOptions": [{"id": "high", "label": "High"}],
                    "defaultThinkingOptionId": "high",
                },
            ],
        },
        "pi": {
            "provider": "pi",
            "models": [
                {
                    "provider": "pi",
                    "id": "deepseek/deepseek-v4-flash",
                    "label": "DeepSeek",
                }
            ],
        },
        "claude": {"provider": "claude", "models": []},
    }
    app = app_with_models(tmp_path / "data", lambda: catalog)

    response = app_request(app, "GET", "/api/roles/models")

    assert response.status_code == 200
    assert response.json()["providers"]["codex"] == catalog["codex"]["models"]
    assert response.json()["providers"]["pi"] == catalog["pi"]["models"]
    assert {item["id"] for item in response.json()["fallback"]["codex"]} >= {
        "gpt-6-luna"
    }
    assert {
        item["id"] for item in response.json()["models_by_harness"]["opencode-http"]
    } >= {"opencode-go/deepseek-v4.1-flash"}
    assert "opencode-http" in response.json()["harnesses"]
    assert path.read_text() == config_text("gpt-6-luna")
    exact_id = "gpt-6-astra-preview[1m]"
    proposed = config_text(exact_id)
    preview = app_request(
        app,
        "POST",
        "/api/roles/preview",
        content=json.dumps({"toml": proposed}).encode(),
        headers={"content-type": "application/json"},
    ).json()
    saved = app_request(
        app,
        "POST",
        "/api/roles/save",
        content=json.dumps(
            {"toml": proposed, "preview_token": preview["preview_token"]}
        ).encode(),
        headers={"content-type": "application/json"},
    )
    assert saved.status_code == 200
    assert load_config(path).resolve("builder").model == exact_id


def test_role_models_fall_back_to_config_when_paseo_is_unavailable(
    tmp_path, monkeypatch
):
    path = tmp_path / "runner.toml"
    path.write_text(config_text())
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))

    def unavailable():
        raise RuntimeError("sidecar offline")

    app = app_with_models(tmp_path / "data", unavailable)
    response = app_request(app, "GET", "/api/roles/models")

    assert response.status_code == 200
    assert response.json()["error"] == "sidecar offline"
    assert {item["id"] for item in response.json()["fallback"]["codex"]} == {
        "gpt-6-luna"
    }
    assert {
        item["id"] for item in response.json()["models_by_harness"]["opencode-http"]
    } == {"opencode-go/deepseek-v4.1-flash"}
    assert path.read_text() == config_text()


def test_role_models_publish_active_native_harnesses_and_configured_models(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("VARDE_RUNNER_STATE_DIR", str(tmp_path / "state"))
    app = app_with_models(tmp_path / "data", dict)
    response = app_request(app, "GET", "/api/roles/models")

    payload = response.json()
    assert {"claude-sdk", "codex-app-server", "pi-rpc", "opencode-http"} <= set(
        payload["native_harnesses"]
    )
    assert {item["id"] for item in payload["models_by_harness"]["opencode-http"]} == {
        "opencode-go/deepseek-v4.1-flash"
    }
    assert payload["error"] == "pi model list is empty"


def test_browser_route_opens_role_types_settings(
    tmp_path, monkeypatch, browser_session, shared_browser_page, browser_server
):
    path = tmp_path / "runner.toml"
    original = config_text()
    path.write_text(original)
    monkeypatch.setenv("VARDE_RUNNER_CONFIG_DIR", str(tmp_path))
    catalog = {
        "codex": {
            "provider": "codex",
            "models": [
                REAL_LIST_MODELS_FIXTURE["models"][0],
                {
                    "provider": "codex",
                    "id": "gpt-6-astra-preview[1m]",
                    "label": "Astra 1M",
                },
            ],
        },
        "pi": {
            "provider": "pi",
            "models": [
                {
                    "provider": "pi",
                    "id": "deepseek/deepseek-v4-flash",
                    "label": "DeepSeek",
                }
            ],
        },
        "claude": {"provider": "claude", "models": []},
    }
    app = app_with_models(tmp_path / "data", lambda: catalog)
    page = shared_browser_page
    origin = browser_server(app)
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(f"{origin}/")
    page.evaluate("localStorage.clear(); sessionStorage.clear()")
    page.goto(f"{origin}/roles")
    page.wait_for_url("**/settings/role-types")
    page.get_by_role("heading", name="Role types", level=1).wait_for()
    page.goto(f"{origin}/settings/role-types")
    page.get_by_role("heading", name="Role types", level=1).wait_for()
    card_heading = page.get_by_role("heading", name="Role types", exact=True, level=2)
    assert card_heading.count() == 0
    assert path.read_text() == original
    page.get_by_label("builder").select_option("standard")
    page.get_by_role("button", name="Preview role changes").click()
    page.get_by_role("button", name="Save role changes").wait_for()
    assert "builder" in page.get_by_label("Role change summary").inner_text().lower()
    page.get_by_role("button", name="Save role changes").click()
    page.locator('[role="status"]').filter(
        has_text="Role settings saved. Restart the runner to apply them."
    ).wait_for()
    saved_builder = load_config(path).resolve("builder")
    assert (saved_builder.harness, saved_builder.model) == (
        "claude-sdk",
        "claude-sonnet-5-5",
    )

    def unavailable():
        raise RuntimeError("sidecar offline")

    fallback_app = app_with_models(tmp_path / "fallback-data", unavailable)
    fallback_origin = browser_server(fallback_app)
    page.goto(f"{fallback_origin}/settings/role-types")
    page.get_by_role("heading", name="Role types", level=1).wait_for()


LONG_UNLABELLED_MODEL = "openrouter/openrouter-model-name-long-12345678"
LONG_LABELLED_MODEL = "openrouter/long-context-model"
LONG_MODEL_LABEL = "DeepSeek V4.1 Flash Long Context"
NORMAL_MODEL = "deepseek/deepseek-v4-flash"


def write_roles_browser_fixture(config_dir: Path) -> None:
    role_names = ["orchestrator", "planner", "builder", "explorer", "reviewer", "judge"]
    role_blocks = ["version = 1", ""]
    for name in role_names:
        type_name = f"fixture_{name}"
        model = (
            "claude-sonnet-5.5"
            if name == "orchestrator"
            else LONG_LABELLED_MODEL
            if name == "builder"
            else NORMAL_MODEL
            if name == "reviewer"
            else LONG_UNLABELLED_MODEL
        )
        role_blocks.extend(
            [
                f"[types.{type_name}]",
                'harness = "claude-sdk"'
                if name == "orchestrator"
                else 'harness = "pi"',
                f'model = "{model}"',
                'reasoning_effort = "high"',
                "",
            ]
        )
        fallback_count = 3 if name == "orchestrator" else 1
        for index in range(fallback_count):
            fallback_model = (
                LONG_LABELLED_MODEL
                if name == "planner" and index == 0
                else LONG_UNLABELLED_MODEL
            )
            role_blocks.extend(
                [
                    f"[[types.{type_name}.fallback]]",
                    'harness = "pi"',
                    f'model = "{fallback_model}"',
                    'reasoning_effort = "medium"',
                    "",
                ]
            )
    for name in role_names:
        role_blocks.extend([f"[roles.{name}]", f'type = "fixture_{name}"', ""])
    role_blocks.extend(
        [
            "[roles.mailman]",
            'harness = "pi"',
            'model = "unknown-mailman"',
            'reasoning_effort = "medium"',
            'mode = "workspace-write"',
            "",
        ]
    )
    role_blocks.extend(
        [
            "[policy]",
            'never_models = ["*-sol"]',
            'allow_fallback_only_on = ["provider_limit"]',
            "create_paseo_projects = false",
            "",
        ]
    )
    (config_dir / "runner.toml").write_text("\n".join(role_blocks))


def test_retired_roles_route_uses_settings_shell(
    tmp_path, monkeypatch, browser_session, shared_browser_page, browser_server
):
    app = app_with_models(tmp_path / "data", dict)
    page = shared_browser_page
    origin = browser_server(app)
    page.goto(f"{origin}/roles")
    page.wait_for_url("**/settings/role-types")
    page.get_by_role("heading", name="Role types", level=1).wait_for()
