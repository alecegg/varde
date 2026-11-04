"""Read-only, redacted view of the runner TOML."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import tomlkit
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from tomlkit.exceptions import ParseError
from tomlkit.items import Array, InlineTable, Table
from tomlkit.toml_document import TOMLDocument

from varde_runner.config import config_path, configured_allowed_hosts, default_toml

_SENSITIVE_PARTS = (
    "token",
    "secret",
    "password",
    "auth",
    "credential",
    "private_key",
    "api_key",
    "access_key",
    "binary",
    "executable",
    "path",
    "file",
    "_dir",
    "_root",
    "cwd",
    "workdir",
    "directory",
    "storage_dir",
    "command",
    "arguments",
    "args",
    "key_env",
)


def _redact_value(value: Any, *, environment: bool = False) -> Any:
    if isinstance(value, (TOMLDocument, Table, InlineTable)):
        for key in list(value):
            key_text = str(key).casefold()
            child = value[key]
            if environment or any(part in key_text for part in _SENSITIVE_PARTS):
                value[key] = "[redacted]"
            else:
                value[key] = _redact_value(
                    child, environment=key_text in {"env", "environment"}
                )
        return value
    if isinstance(value, Array):
        for index, item in enumerate(value):
            value[index] = _redact_value(item, environment=environment)
        return value
    if isinstance(value, list):
        return [_redact_value(item, environment=environment) for item in value]
    return "[redacted]" if environment else value


def redact_runner_config(text: str) -> str:
    """Redact sensitive values by key while preserving TOML comments and layout."""
    try:
        document = tomlkit.parse(text)
    except ParseError, UnicodeError:
        return "# Invalid TOML; content omitted for safety.\n"
    redacted = _redact_value(document)
    return tomlkit.dumps(redacted)


def config_view(text: str, *, path: Path | None = None) -> dict[str, Any]:
    """Return the redacted TOML and the validated read-only host allowlist."""
    return {
        "toml": redact_runner_config(text),
        "allowed_hosts": list(configured_allowed_hosts(text)),
        "path": str(path) if path is not None else "",
    }


def create_runner_config_toml_view_route(*, config_file: Path | None = None) -> Route:
    path = config_file or config_path()

    async def read_view(_request: Request) -> JSONResponse:
        try:
            text = path.read_text(encoding="utf-8") if path.exists() else default_toml()
            return JSONResponse(config_view(text, path=path))
        except OSError, UnicodeError, ValueError:
            return JSONResponse(
                {"error": "runner config cannot be read"}, status_code=409
            )

    return Route(
        "/api/runner/config/toml",
        read_view,
        methods=["GET"],
        name="runner_config_toml_view",
    )
