"""Allowlisted runner config read and write endpoints."""

from __future__ import annotations

import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from varde_runner import config_io
from varde_runner.config import adapter_state_root, config_path, default_toml
from varde_runner.config_changes import append_changes
from varde_runner.runner_config_edit import EditError, allowlist, apply
from varde_runner.web.runner_config_schema import config_choices

ROUTE_POLICIES = {
    ("GET", "/api/runner/config"): "read",
    ("PUT", "/api/runner/config"): "user_only",
}

_LABELS = {
    "limits.max_live_instances": (
        "Maximum live instances",
        "Limits concurrent runner sessions.",
        "limits",
    ),
}


def _value(document: dict[str, Any], key: str, default: Any) -> Any:
    current: Any = document
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def _restart_required(key: str) -> bool:
    return key.startswith(("types.", "roles.", "policy.")) or key.endswith(".enabled")


def _items(text: str, registry: Any) -> list[dict[str, Any]]:
    document = tomllib.loads(text)
    defaults = tomllib.loads(default_toml())
    fields = allowlist(registry, text)
    if not callable(getattr(registry, "config_choices", None)):
        fields = {
            key: field for key, field in fields.items() if not key.startswith("types.")
        }
    result = []
    for key, field in fields.items():
        fallback = _value(defaults, key, False if field.value_type is bool else 0)
        value = _value(document, key, fallback)
        label, hint, group = _LABELS.get(key, _structured_label(key, field.value_type))
        bounds = (
            {"min": field.minimum, "max": field.maximum}
            if field.minimum is not None or field.maximum is not None
            else None
        )
        result.append(
            {
                "key": key,
                "label": label,
                "hint": hint,
                "type": _field_type(field.value_type),
                "bounds": bounds,
                "value": value,
                "default": fallback,
                "restart_required": _restart_required(key),
                "group": group,
            }
        )
    return result


def _field_type(value_type: type) -> str:
    return {bool: "boolean", int: "integer", str: "string", list: "array"}.get(
        value_type, "string"
    )


def _structured_label(key: str, value_type: type) -> tuple[str, str, str]:
    section = key.split(".", 1)[0]
    group = {"bot": "bot", "types": "types", "roles": "roles", "policy": "policy"}.get(
        section, "harnesses"
    )
    label = key.rsplit(".", 1)[-1].replace("_", " ").title()
    hint = "Edit the ordered fallback list." if key.endswith(".fallback") else ""
    if value_type is bool:
        hint = "Enable or disable this setting."
    return label, hint, group


def create_runner_config_routes(
    registry_getter: Callable[[], Any],
    *,
    config_file: Callable[[], Path] = config_path,
    state_root: Callable[[], Path] = adapter_state_root,
) -> list[Route]:
    async def read_config(_request: Request) -> JSONResponse:
        path = config_file()
        registry = registry_getter()
        try:
            text = path.read_text(encoding="utf-8") if path.exists() else default_toml()
            items = _items(text, registry)
        except OSError, UnicodeError, tomllib.TOMLDecodeError:
            return JSONResponse(
                {"error": "runner config cannot be read"}, status_code=409
            )
        return JSONResponse({"items": items, "choices": config_choices(registry)})

    async def write_config(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except ValueError, UnicodeError:
            return JSONResponse(
                {"errors": {"_": "request must be valid JSON"}}, status_code=400
            )
        changes = payload.get("changes") if isinstance(payload, dict) else None
        if not isinstance(changes, dict) or not changes:
            return JSONResponse(
                {"errors": {"_": "changes must be a non-empty object"}}, status_code=400
            )

        path = config_file()
        try:
            old_text = (
                path.read_text(encoding="utf-8") if path.exists() else default_toml()
            )
        except OSError, UnicodeError:
            return JSONResponse(
                {"error": "runner config cannot be read"}, status_code=409
            )
        registry = registry_getter()
        result = apply(old_text, changes, registry)
        if isinstance(result, EditError):
            if "by hand" in result.hint:
                return JSONResponse(
                    {"error": "edit this setting by hand", "hint": result.hint},
                    status_code=409,
                )
            errors = _errors(changes, registry, old_text)
            if not errors:
                errors = dict.fromkeys(
                    changes, "resulting config is invalid; review dependent settings"
                )
            return JSONResponse({"errors": errors}, status_code=400)

        preview = payload.get("preview") is True
        try:
            old_document = tomllib.loads(old_text)
            new_document = tomllib.loads(result)
            changed = {
                key: (_value(old_document, key, None), _value(new_document, key, None))
                for key in changes
                if _value(old_document, key, None) != _value(new_document, key, None)
            }
            items = _items(result, registry)
            restart_required = any(_restart_required(key) for key in changed)
            if preview:
                return JSONResponse(
                    {
                        "items": items,
                        "choices": config_choices(registry),
                        "preview": True,
                        "changed": list(changed),
                        "restart_required": restart_required,
                    }
                )
            config_io.write_config(path, result)
            append_changes(state_root() / "config-changes.jsonl", changed)
        except OSError, UnicodeError, tomllib.TOMLDecodeError:
            return JSONResponse(
                {"error": "runner config could not be saved"}, status_code=500
            )
        return JSONResponse(
            {
                "items": items,
                "choices": config_choices(registry),
                "restart_required": restart_required,
            }
        )

    return [
        Route(
            "/api/runner/config",
            read_config,
            methods=["GET"],
            name="read_runner_config",
        ),
        Route(
            "/api/runner/config",
            write_config,
            methods=["PUT"],
            name="user_only_runner_config",
        ),
    ]


def _errors(changes: dict[str, Any], registry: Any, text: str) -> dict[str, str]:
    from varde_runner.runner_config_edit import validate

    return validate(changes, registry, text)
