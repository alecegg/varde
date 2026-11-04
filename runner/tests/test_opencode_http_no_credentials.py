"""OpenCode adapter must not inspect user/provider credentials."""

import ast
import re
from pathlib import Path

PLUGIN_DIR = (
    Path(__file__).parents[1] / "src" / "varde_runner" / "plugins" / "opencode_http"
)
FORBIDDEN = ("auth.json", ".opencode/auth", "credentials.json", "keychain", "keyring")
CREDENTIAL = re.compile(
    r"[a-z0-9_]*(?:api_key|oauth|access_token|refresh_token)[a-z0-9_]*", re.IGNORECASE
)


def test_opencode_source_does_not_access_credentials():
    for path in PLUGIN_DIR.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert not any(term in source.casefold() for term in FORBIDDEN)
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                assert not CREDENTIAL.fullmatch(node.value), (path, node.value)
