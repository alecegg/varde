"""Guard the Codex app-server adapter against credential discovery and injection."""

import ast
import asyncio
import json
import os
import re
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

PLUGIN_DIR = (
    Path(__file__).parents[1] / "src" / "varde_runner" / "plugins" / "codex_app_server"
)
ENV_NAME = re.compile(
    r"[a-z0-9_]*(?:api_key|oauth|access_token|openai_token|codex_token)[a-z0-9_]*"
)
FORBIDDEN_TEXT = (
    "auth.json",
    "keyring",
    "keychain",
    "security find-generic-password",
)
SAFE_ACCOUNT_METHODS = {
    "account/rateLimits/read",
    "account/read",
    "account/chatgptAuthTokens/refresh",
}
INBOUND_ACCOUNT_METHODS = {"account/rateLimits/updated"}
RUNNER_SPEC_DIR = ".codex/agents"


def _is_credential_name(value: object) -> bool:
    return isinstance(value, str) and bool(ENV_NAME.fullmatch(value.casefold()))


def _fold_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Div)):
        left = _fold_string(node.left)
        right = _fold_string(node.right)
        if left is not None and right is not None:
            return f"{left}/{right}" if isinstance(node.op, ast.Div) else left + right
    if isinstance(node, ast.JoinedStr):
        parts = [
            value.value
            for value in node.values
            if isinstance(value, ast.Constant) and isinstance(value.value, str)
        ]
        return "".join(parts)
    return None


def _path_parts(node: ast.AST) -> list[str]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Div)):
        return _path_parts(node.left) + _path_parts(node.right)
    value = _fold_string(node)
    return [value] if value is not None else []


def _is_runner_spec_path(node: ast.AST) -> bool:
    parts = _path_parts(node)
    joined = "/".join(parts).replace("\\", "/").casefold()
    return re.search(r"(?:^|/)\.codex/agents(?:/|$)", joined) is not None


def _target_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        return set().union(*(_target_names(item) for item in node.elts))
    return set()


def _credential_violations(source: str, filename: str = "<adapter>") -> list[str]:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return [f"invalid Python: {exc}"]

    violations: list[str] = []
    lowered_source = source.casefold()
    violations.extend(
        f"forbidden credential access text: {token}"
        for token in FORBIDDEN_TEXT
        if token in lowered_source
    )
    if re.search(r"\bimport\s+(?:[a-z0-9_]*\.)?keyring\b", lowered_source):
        violations.append("forbidden keyring import")

    runner_spec_nodes = {
        id(child)
        for candidate in ast.walk(tree)
        if _is_runner_spec_path(candidate)
        for child in ast.walk(candidate)
    }
    for node in ast.walk(tree):
        value = _fold_string(node)
        if value is not None:
            lowered = value.casefold()
            violations.extend(
                f"forbidden credential access text: {token}"
                for token in FORBIDDEN_TEXT
                if token in lowered and token not in lowered_source
            )
            if ".codex" in lowered and id(node) not in runner_spec_nodes:
                violations.append("path under ~/.codex")
            if (
                lowered.startswith("account/")
                and len(lowered) > len("account/")
                and value not in SAFE_ACCOUNT_METHODS | INBOUND_ACCOUNT_METHODS
            ):
                violations.append(f"unsupported account method: {value}")
            if _is_credential_name(value):
                violations.append(f"credential environment name: {value}")

        if isinstance(node, ast.keyword) and node.arg and _is_credential_name(node.arg):
            violations.append(f"credential environment keyword: {node.arg}")

        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(
                _is_credential_name(name)
                for target in targets
                for name in _target_names(target)
            ):
                violations.append("assignment to credential environment variable")

        if isinstance(node, ast.Dict) and any(
            key is not None and _is_credential_name(_fold_string(key))
            for key in node.keys
        ):
            violations.append("credential key in environment dictionary")

        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.ctx, ast.Store)
            and _is_credential_name(_fold_string(node.slice))
        ):
            violations.append("assignment to credential environment key")

    return violations


def _file_violations(path: Path) -> list[str]:
    return _credential_violations(path.read_text(encoding="utf-8"), str(path))


def test_adapter_source_never_discovers_or_sets_credentials():
    assert PLUGIN_DIR.is_dir()
    violations = []
    for path in sorted(PLUGIN_DIR.rglob("*.py")):
        violations.extend(
            f"{path.relative_to(PLUGIN_DIR)}: {message}"
            for message in _file_violations(path)
        )
    assert not violations, "\n".join(violations)


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ('value = "auth" + ".json"', "forbidden credential access text: auth.json"),
        ('value = ".co" + "dex/auth"', "path under ~/.codex"),
        ('value = Path.home() / ".codex"', "path under ~/.codex"),
        (
            'Path.home().joinpath(".codex", "data").read_text()',
            "path under ~/.codex",
        ),
        ('open("/home/user/.codex/config.toml")', "path under ~/.codex"),
        ('env.update(OPENAI_API_KEY="x")', "credential environment keyword"),
        ('env = {"openai_api_key": "x"}', "credential key in environment dictionary"),
        ('env = {"OPENAI_TOKEN": "x"}', "credential key in environment dictionary"),
        ('target: str = "x"; OPENAI_API_KEY: str = "x"', "assignment to credential"),
        ('(CODEX_API_KEY, other) = ("x", "y")', "assignment to credential"),
        ('(CODEX_ACCESS_TOKEN := "x")', "assignment to credential"),
        ("import KeyRing", "forbidden credential access text: keyring"),
        ("import KEYCHAIN", "forbidden credential access text: keychain"),
        ('method = "account/" + "logout"', "unsupported account method"),
    ],
)
def test_scanner_rejects_credential_patterns(
    tmp_path: Path, source: str, expected: str
) -> None:
    module = tmp_path / "adapter.py"
    module.write_text(source, encoding="utf-8")
    assert any(expected in violation for violation in _file_violations(module))


def test_scanner_allows_runner_owned_spec_directory():
    source = 'path = Path.home() / ".codex" / "agents" / "runner.toml"'
    assert _credential_violations(source) == []
    assert RUNNER_SPEC_DIR == ".codex/agents"


def test_wire_refuses_auth_refresh_and_only_uses_safe_account_methods():
    from varde_runner.plugins.codex_app_server import wire

    response = json.loads(
        wire.encode_server_response(
            "account/chatgptAuthTokens/refresh", "refresh", "allow"
        )
    )
    assert response["error"]["code"] == -32601
    assert "result" not in response

    methods = set(wire.REQUIRED_CLIENT_METHODS)
    account_methods = {method for method in methods if method.startswith("account/")}
    assert account_methods <= {
        "account/rateLimits/read",
        "account/read",
    }
    assert not {"account/login/start", "account/logout"} & methods


def test_runtime_child_environment_contains_parent_plus_varde_keys(monkeypatch):
    plugin_path = PLUGIN_DIR / "plugin.py"
    fake = Path(__file__).parent / "fakes" / "fake_codex_app_server.py"
    if not plugin_path.exists() or not fake.exists():
        pytest.skip("runtime guard waits for t2 plugin.py and fake Codex process")

    from varde_runner.plugins import SessionSpec
    from varde_runner.plugins.codex_app_server.plugin import CodexAppServerPlugin

    monkeypatch.setenv("CODEX_API_KEY", "parent-test-value")
    parent_env = dict(os.environ)
    real_create = asyncio.create_subprocess_exec
    create_spy = AsyncMock(wraps=real_create)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_spy)

    async def check_child_environment():
        plugin = CodexAppServerPlugin(executable=str(fake))
        await plugin.start(
            SessionSpec("codex-app-server", "model", "agent", str(Path.cwd()))
        )
        try:
            child_env = next(
                call.kwargs["env"]
                for call in create_spy.call_args_list
                if "env" in call.kwargs
            )
            expected_env = {
                key: value
                for key, value in parent_env.items()
                if not key.startswith("PASEO_")
                and key
                not in {
                    "VARDE_ADDRESS",
                    "VARDE_AGENT_ID",
                    "VARDE_HARNESS",
                    "VARDE_RUNNER_ENDPOINT",
                }
            }
            expected_env.update(
                {"VARDE_AGENT_ID": "agent", "VARDE_HARNESS": "codex-app-server"}
            )
            assert child_env == expected_env
        finally:
            await plugin.close()

    asyncio.run(check_child_environment())
