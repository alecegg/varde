"""Role configuration editor endpoints."""

from __future__ import annotations

import difflib
import json
import os  # noqa: F401 - retained for the role editor's atomic-write test seam.
import re
import secrets
import tomllib
from collections import OrderedDict
from dataclasses import replace
from pathlib import Path
from typing import NoReturn

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from varde_runner.config import (
    DEFAULT_ROLE_TYPES,
    TYPE_DEFINITIONS,
    TYPE_FALLBACK,
    ConfigError,
    config_path,
    default_config,
    default_toml,
    keep_unknown_roles,
    legacy_type_name,
    parse_config,
)
from varde_runner.config_io import write_config as _write_config


def _raise_validation(error: Exception) -> NoReturn:
    raise error


def _fallback_payload(
    harness: str, model: str, effort: str, mode: str | None = None
) -> dict:
    payload = {
        "harness": harness,
        "model": model,
        "reasoning_effort": effort,
    }
    if mode is not None:
        payload["mode"] = mode
    return payload


def _type_payload(data: dict, legacy: bool, registry=None) -> dict:
    def eligible(harness: str) -> bool:
        return bool(registry and registry.capabilities(harness).guard_read_only)

    if legacy:
        return {
            name: {
                "harness": harness,
                "model": model,
                "reasoning_effort": effort,
                "fallback": [_fallback_payload(*TYPE_FALLBACK)],
                "guard_eligible": eligible(harness),
            }
            for name, (harness, model, effort) in TYPE_DEFINITIONS.items()
        }

    return {
        name: {
            "harness": definition["harness"],
            "model": definition["model"],
            "reasoning_effort": definition["reasoning_effort"],
            "fallback": [
                _fallback_payload(
                    item["harness"], item["model"], item["reasoning_effort"]
                )
                for item in definition.get("fallback", [])
            ],
            "guard_eligible": eligible(definition["harness"]),
        }
        for name, definition in data.get("types", {}).items()
    }


def _role_type(name: str, raw_role, resolved_role, legacy: bool) -> str | None:
    if not legacy:
        return raw_role.get("type") if isinstance(raw_role, dict) else None
    return legacy_type_name(name, resolved_role)


def _role_payload(name: str, role, type_name: str | None) -> dict:
    result = {
        "type": type_name,
        "harness": role.harness,
        "model": role.model,
        "reasoning_effort": role.reasoning_effort,
        "mode": role.mode,
        "fallback": [
            _fallback_payload(
                item.harness, item.model, item.reasoning_effort, item.mode
            )
            for item in role.fallback
        ],
    }
    if name in {"guard", "manager-bot"}:
        result["enabled"] = role.enabled
    return result


def _guard_type(data: dict, legacy: bool) -> str | None:
    if legacy or "guard" in data.get("roles", {}):
        return None
    type_name = DEFAULT_ROLE_TYPES["guard"]
    return type_name if type_name in data.get("types", {}) else None


def _roles_payload(current: str, registry=None) -> dict:
    try:
        config = parse_config(current)
    except ConfigError as exc:
        return {
            "toml": current,
            "error": str(exc),
            "legacy": False,
            "guard_in_file": False,
            "types": {},
            "roles": {},
        }
    data = tomllib.loads(current)
    legacy = "types" not in data
    resolved_roles = dict(config.roles)
    guard_in_file = "guard" in resolved_roles
    guard_type = _guard_type(data, legacy)
    if not guard_in_file:
        guard = default_config().roles["guard"]
        if guard_type is not None:
            definition = data["types"][guard_type]
            guard = replace(
                guard,
                harness=definition["harness"],
                model=definition["model"],
                reasoning_effort=definition["reasoning_effort"],
            )
        resolved_roles["guard"] = guard
    types = _type_payload(data, legacy, registry)
    return {
        "toml": current,
        "guard_in_file": guard_in_file,
        "legacy": legacy,
        "types": types,
        "roles": {
            name: _role_payload(
                name,
                role,
                _role_type(name, data.get("roles", {}).get(name), role, legacy)
                or (guard_type if name == "guard" else None),
            )
            for name, role in resolved_roles.items()
        },
    }


def create_roles_route(path: Path | None = None, registry_getter=None) -> Route:
    target = path or config_path()
    pending_previews: OrderedDict[str, str] = OrderedDict()

    async def submitted_text(request: Request) -> tuple[dict, str] | JSONResponse:
        try:
            payload = await request.json()
            if not isinstance(payload, dict) or not isinstance(
                payload.get("toml"), str
            ):
                _raise_validation(TypeError("toml must be a string"))
            existing = target.read_text(encoding="utf-8") if target.exists() else ""
            text = keep_unknown_roles(payload["toml"], existing)
            parse_config(text)
        except (
            json.JSONDecodeError,
            UnicodeDecodeError,
            TypeError,
            ConfigError,
        ) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return payload, text

    def diff(text: str) -> str:
        before = target.read_text(encoding="utf-8") if target.exists() else ""
        return "".join(
            difflib.unified_diff(
                before.splitlines(True),
                text.splitlines(True),
                fromfile="current",
                tofile="proposed",
            )
        )

    async def preview(request: Request) -> JSONResponse:
        parsed = await submitted_text(request)
        if isinstance(parsed, JSONResponse):
            return parsed
        _, text = parsed
        token = secrets.token_urlsafe(24)
        pending_previews[token] = text
        if len(pending_previews) > 128:
            pending_previews.popitem(last=False)
        return JSONResponse({"diff": diff(text), "preview_token": token})

    async def save(request: Request) -> JSONResponse:
        parsed = await submitted_text(request)
        if isinstance(parsed, JSONResponse):
            return parsed
        payload, text = parsed
        token = payload.get("preview_token")
        if not isinstance(token, str) or pending_previews.get(token) != text:
            return JSONResponse(
                {"error": "preview this exact config before saving"}, status_code=409
            )
        _write_config(target, text)
        del pending_previews[token]
        return JSONResponse({"diff": diff(text), "saved": True})

    async def dispatch(request: Request) -> JSONResponse:
        path = request.url.path
        if request.method == "GET" and path == "/api/roles":
            current = (
                target.read_text(encoding="utf-8")
                if target.exists()
                else default_toml()
            )
            registry = registry_getter() if registry_getter else None
            return JSONResponse(_roles_payload(current, registry))
        if request.method == "POST" and path == "/api/roles/preview":
            return await preview(request)
        if request.method == "POST" and path == "/api/roles/save":
            return await save(request)
        if path in {
            "/api/roles",
            "/api/roles/preview",
            "/api/roles/save",
        }:
            return JSONResponse({"error": "method not allowed"}, status_code=405)
        return JSONResponse({"error": "not found"}, status_code=404)

    route = Route("/roles", dispatch, methods=["GET", "POST"])
    route.path_regex = re.compile(r"^/api/roles(?:/(?:preview|save))?$")
    return route
