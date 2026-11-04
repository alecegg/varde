"""Guard the Claude CLI adapter against credential discovery and injection."""

import ast
import re
from pathlib import Path

import pytest

PLUGIN_DIR = (
    Path(__file__).parents[1] / "src" / "varde_runner" / "plugins" / "claude_cli"
)
REMOVED_ENV = {
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
}
FORBIDDEN_TEXT = (
    "Keychain",
    "keychain",
    "security find-generic-password",
    ".credentials",
    "credentials.json",
    ".claude.json",
    "keyring",
)
ENV_NAME = re.compile(r"[A-Z0-9_]*(?:API_KEY|OAUTH)[A-Z0-9_]*")


def _is_env_name(value: object) -> bool:
    return isinstance(value, str) and (
        value in REMOVED_ENV or bool(ENV_NAME.fullmatch(value))
    )


def _allowed_removal_tuple(tree: ast.Module) -> tuple[ast.Assign, set[int]] | None:
    """Find the sole top-level tuple that names exactly the stripped variables."""
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id != "REMOVED_ENV_VARS":
            continue
        if not isinstance(node.value, (ast.Tuple, ast.List)):
            continue
        values = {
            item.value for item in node.value.elts if isinstance(item, ast.Constant)
        }
        if values == REMOVED_ENV and len(node.value.elts) == len(REMOVED_ENV):
            return node, {id(child) for child in ast.walk(node)}
    return None


def _credential_violations(source: str, filename: str = "<adapter>") -> list[str]:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return [f"invalid Python: {exc}"]

    allowed = _allowed_removal_tuple(tree)
    violations: list[str] = []
    violations.extend(
        f"forbidden credential access text: {token}"
        for token in FORBIDDEN_TEXT
        if token in source
    )
    if re.search(r"\bimport\s+keyring\b|\bfrom\s+keyring\b", source):
        violations.append("forbidden keyring import")

    allowed_nodes = allowed[1] if allowed else set()
    for node in ast.walk(tree):
        if id(node) in allowed_nodes:
            continue
        if isinstance(node, ast.Constant) and _is_env_name(node.value):
            violations.append(
                f"credential environment name outside removal tuple: {node.value}"
            )
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(
                _is_env_name(name)
                for target in targets
                for name in _target_names(target)
            ):
                violations.append("assignment to API-key/OAuth variable")
        if isinstance(node, ast.Call):
            function = node.func
            if (
                isinstance(function, ast.Attribute)
                and function.attr in {"setdefault", "putenv"}
                and node.args
                and _is_env_name(_literal(node.args[0]))
            ):
                violations.append(f"forbidden environment call: {function.attr}")
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.ctx, ast.Store)
            and _is_env_subscript(node)
        ):
            violations.append("assignment to os.environ credential key")
        if isinstance(node, ast.Dict) and any(
            key is not None and _is_env_name(_literal(key)) for key in node.keys
        ):
            violations.append("credential key in environment dictionary")
    return violations


def _literal(node: ast.AST) -> object:
    return node.value if isinstance(node, ast.Constant) else None


def _target_names(node: ast.AST) -> set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        return set().union(*(_target_names(item) for item in node.elts))
    return set()


def _is_env_subscript(node: ast.Subscript) -> bool:
    value = node.value
    is_env = (
        isinstance(value, ast.Attribute)
        and value.attr == "environ"
        and isinstance(value.value, ast.Name)
        and value.value.id == "os"
    )
    return is_env and _is_env_name(_literal(node.slice))


def test_adapter_source_never_discovers_or_sets_credentials():
    assert PLUGIN_DIR.is_dir()
    violations = []
    for path in sorted(PLUGIN_DIR.glob("*.py")):
        violations.extend(
            f"{path.name}: {message}"
            for message in _credential_violations(
                path.read_text(encoding="utf-8"), str(path)
            )
        )
    assert not violations, "\n".join(violations)


@pytest.mark.parametrize(
    "source",
    [
        'value = "Keychain"',
        'value = "security find-generic-password"',
        'value = ".credentials"',
        'value = "credentials.json"',
        'value = ".claude.json"',
        "import keyring",
        'ANTHROPIC_API_KEY = "x"',
        'os.environ["ANTHROPIC_AUTH_TOKEN"] = "x"',
        'os.environ.setdefault("CLAUDE_CODE_OAUTH_TOKEN", "x")',
        'os.putenv("SOME_API_KEY", "x")',
        'env = {"SOME_OAUTH_TOKEN": "x"}',
    ],
)
def test_scanner_rejects_credential_patterns(source):
    assert _credential_violations(source)


def test_scanner_allows_only_named_removal_tuple():
    source = """REMOVED_ENV_VARS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_OAUTH_TOKEN",
)
"""
    assert _credential_violations(source) == []


def test_runtime_child_environment_strips_credentials(monkeypatch):
    plugin_path = PLUGIN_DIR / "plugin.py"
    if not plugin_path.exists():
        pytest.skip(
            "runtime guard waits for parallel t2 plugin.py and fake claude process"
        )
    import asyncio
    import json

    from varde_runner.plugins import SessionSpec
    from varde_runner.plugins.claude_cli.plugin import ClaudeCliPlugin, ProcessIdentity

    fake = Path(__file__).parent / "fakes" / "fake_claude.py"
    for name in REMOVED_ENV:
        monkeypatch.setenv(name, "must-not-leak")

    async def check_child_environment():
        plugin = ClaudeCliPlugin(
            fake,
            process_inspector=lambda _pid, command: ProcessIdentity(
                "test-start", " ".join(command)
            ),
        )
        ref = await plugin.start(
            SessionSpec("claude-cli", "model", "agent", str(Path.cwd()))
        )
        try:
            event = await asyncio.wait_for(anext(plugin.events(ref)), 2)
            report = json.loads(event.payload["text"])
            assert report["stripped"] is True
        finally:
            await plugin.close()

    asyncio.run(check_child_environment())
