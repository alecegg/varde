"""Pi RPC source must not inspect or inject account credentials."""

import ast
import re
from pathlib import Path

PLUGIN_DIR = Path(__file__).parents[1] / "src" / "varde_runner" / "plugins" / "pi_rpc"
FORBIDDEN = ("keychain", "keyring", "credentials.json", "auth.json", ".pi/agent/auth")
CREDENTIAL_NAME = re.compile(
    r"[a-z0-9_]*(?:api_key|oauth|access_token|refresh_token)[a-z0-9_]*",
    re.IGNORECASE,
)


def test_pi_rpc_source_does_not_access_credentials():
    for path in PLUGIN_DIR.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert not any(term in source.casefold() for term in FORBIDDEN)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert not CREDENTIAL_NAME.fullmatch(node.value), (path, node.value)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr != "putenv"
