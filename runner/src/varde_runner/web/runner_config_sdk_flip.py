"""Preview and apply the reviewed Claude SDK default change."""

from __future__ import annotations

import hashlib
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from varde_runner import config_io
from varde_runner.config import (
    ConfigError,
    adapter_state_root,
    config_path,
    default_toml,
    parse_config,
)
from varde_runner.config_changes import append_changes
from varde_runner.guard_policy import validate_guard_role
from varde_runner.runner_config_edit import EditError, _edit_table

_FLIP_KEYS = (
    "claude_cli.enabled",
    "types.standard.harness",
    "types.heavy.harness",
    "claude_sdk.enabled",
    "claude_sdk.stream_idle_timeout_s",
    "roles.manager-bot.type",
    "roles.manager-bot.enabled",
)
ROUTE_POLICIES = {
    ("POST", "/api/runner/config/sdk-flip/preview"): "user_only",
    ("POST", "/api/runner/config/sdk-flip/apply"): "user_only",
}


def _edit(text: str, key: str, value: Any) -> str | EditError:
    table, field = key.rsplit(".", 1)
    return _edit_table(text, table, field, value)


def _candidate(text: str, registry: Any) -> str | EditError:
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return EditError("runner config is invalid")
    types = document.get("types")
    roles = document.get("roles")
    if not isinstance(types, dict) or not {"standard", "heavy"} <= types.keys():
        return EditError("required runner types are missing")
    if not isinstance(roles, dict):
        return EditError("runner roles are invalid")

    result = text
    values = {
        "claude_cli.enabled": False,
        "types.standard.harness": "claude-sdk",
        "types.heavy.harness": "claude-sdk",
    }
    for key, value in values.items():
        result = _edit(result, key, value)
        if isinstance(result, EditError):
            return result

    sdk = document.get("claude_sdk")
    sdk_values: list[tuple[str, Any]] = [("claude_sdk.enabled", True)]
    if not isinstance(sdk, dict):
        sdk_values.append(("claude_sdk.stream_idle_timeout_s", 300))
    for key, value in sdk_values:
        result = _edit(result, key, value)
        if isinstance(result, EditError):
            return result

    manager = roles.get("manager-bot")
    if manager is None:
        for key, value in (
            ("roles.manager-bot.type", "standard"),
            ("roles.manager-bot.enabled", False),
        ):
            result = _edit(result, key, value)
            if isinstance(result, EditError):
                return result

    try:
        parsed = parse_config(result, registry.known_harnesses())
        validate_guard_role(parsed.roles["guard"], registry)
    except ConfigError, AttributeError, KeyError, LookupError:
        return EditError("Claude SDK settings fail runner config validation")
    return result


def _preview_id(original: str, result: str) -> str:
    return hashlib.sha256((original + "\0" + result).encode()).hexdigest()


def _diff(original: str, result: str) -> list[dict[str, Any]]:
    before = tomllib.loads(original)
    after = tomllib.loads(result)
    rows = []
    for key in _FLIP_KEYS:
        old: Any = before
        new: Any = after
        for part in key.split("."):
            old = old.get(part) if isinstance(old, dict) else None
            new = new.get(part) if isinstance(new, dict) else None
        if old != new:
            rows.append({"key": key, "before": old, "after": new})
    return rows


def create_sdk_flip_routes(
    registry_getter: Callable[[], Any],
    *,
    config_file: Callable[[], Path] = config_path,
    state_root: Callable[[], Path] = adapter_state_root,
) -> list[Route]:
    def read_text(path: Path) -> str:
        return path.read_text(encoding="utf-8") if path.exists() else default_toml()

    async def preview(_request: Request) -> JSONResponse:
        path = config_file()
        try:
            original = read_text(path)
        except OSError, UnicodeError:
            return JSONResponse(
                {"error": "runner config cannot be read"}, status_code=409
            )
        result = _candidate(original, registry_getter())
        if isinstance(result, EditError):
            return JSONResponse({"error": result.hint}, status_code=400)
        changes = _diff(original, result)
        return JSONResponse(
            {
                "preview_id": _preview_id(original, result),
                "diff": changes,
                "restart_required": bool(changes),
            }
        )

    async def apply(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except ValueError, UnicodeError:
            return JSONResponse(
                {"error": "request must be valid JSON"}, status_code=400
            )
        if not isinstance(payload, dict) or payload.get("confirm") is not True:
            return JSONResponse(
                {"error": "explicit confirmation is required"}, status_code=400
            )
        expected_id = payload.get("preview_id")
        if not isinstance(expected_id, str):
            return JSONResponse({"error": "preview_id is required"}, status_code=400)

        path = config_file()
        try:
            original = read_text(path)
        except OSError, UnicodeError:
            return JSONResponse(
                {"error": "runner config cannot be read"}, status_code=409
            )
        result = _candidate(original, registry_getter())
        if isinstance(result, EditError):
            return JSONResponse({"error": result.hint}, status_code=400)
        if expected_id != _preview_id(original, result):
            return JSONResponse(
                {"error": "preview is stale; review it again"}, status_code=409
            )
        changes = _diff(original, result)
        if changes:
            audit = {row["key"]: (row["before"], row["after"]) for row in changes}
            try:
                config_io.write_config(path, result)
                append_changes(state_root() / "config-changes.jsonl", audit)
            except OSError:
                return JSONResponse(
                    {"error": "runner config could not be saved"}, status_code=500
                )
        return JSONResponse(
            {
                "applied": bool(changes),
                "restart_required": bool(changes),
                "changed": [row["key"] for row in changes],
            }
        )

    return [
        Route("/api/runner/config/sdk-flip/preview", preview, methods=["POST"]),
        Route("/api/runner/config/sdk-flip/apply", apply, methods=["POST"]),
    ]
