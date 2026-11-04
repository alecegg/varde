"""HTTP routes for listing and editing role identity profiles."""

from __future__ import annotations

import contextlib
import dataclasses
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from varde_runner.bot_taint import bot_visible_rows
from varde_runner.config import ROLE_NAMES, config_dir
from varde_runner.identity_groups import EXPANDED_ROLES, group
from varde_runner.identity_profile import (
    PROFILE_IDS,
    Profile,
    ProfileError,
    defaults,
    parse,
    render,
    validate,
)
from varde_runner.registry import SessionRegistry
from varde_runner.web.agents_route import _agent_rows, _supervisor


def _profiles(directory: Path) -> tuple[dict[str, Profile], dict[str, str]]:
    profiles = defaults(ROLE_NAMES)
    errors: dict[str, str] = {}
    for identity_id in profiles:
        path = directory / f"{identity_id}.toml"
        if not path.exists():
            continue
        try:
            profiles[identity_id] = parse(path.read_text(encoding="utf-8"), identity_id)
        except (OSError, ProfileError) as exc:
            errors[identity_id] = str(exc).splitlines()[0]
    for path in directory.iterdir() if directory.exists() else ():
        if (
            path.is_file()
            and path.suffix == ".toml"
            and not path.name.startswith(".")
            and path.stem not in PROFILE_IDS
        ):
            errors[path.stem] = "unknown identity"
    return profiles, errors


def _identity_json(
    identity: dict[str, Any], error: str | None = None
) -> dict[str, Any]:
    if error:
        identity["error"] = error
    return identity


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            return
        try:
            with contextlib.suppress(OSError):
                os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temp.unlink(missing_ok=True)


async def _caller_rows(supervisor: Any, request: Request) -> list[dict]:
    rows = await _agent_rows(supervisor)
    identity = request.scope.get("bot_identity")
    if identity is None:
        return rows
    return bot_visible_rows(identity.actor, rows)


def create_identities_routes(get_supervisor: Callable[[], Any]) -> list[Route]:
    async def identities(request: Request) -> JSONResponse:
        supervisor = await _supervisor(get_supervisor)
        directory = config_dir() / "identities"
        profiles, errors = _profiles(directory)
        groups = group(
            await _caller_rows(supervisor, request),
            SessionRegistry(
                supervisor.data_dir / "registry.json"
            ).bindings_by_session_id(),
            profiles,
        )
        for entry in groups:
            if entry["id"] not in EXPANDED_ROLES:
                entry["instances"] = None
        for identity_id, error in errors.items():
            if identity_id in profiles:
                continue
            groups.append(_identity_json(_identity_default(identity_id), error))
        for entry in groups:
            if entry["id"] in errors:
                entry["error"] = errors[entry["id"]]
        return JSONResponse({"identities": groups})

    async def instances(request: Request) -> JSONResponse:
        identity_id = request.path_params["identity_id"]
        profiles, _ = _profiles(config_dir() / "identities")
        if identity_id not in profiles and identity_id != "other":
            return JSONResponse({"error": "unknown identity"}, status_code=404)
        supervisor = await _supervisor(get_supervisor)
        groups = group(
            await _caller_rows(supervisor, request),
            SessionRegistry(
                supervisor.data_dir / "registry.json"
            ).bindings_by_session_id(),
            profiles,
        )
        found = next((entry for entry in groups if entry["id"] == identity_id), None)
        return JSONResponse({"instances": found["instances"] if found else []})

    async def update(request: Request) -> JSONResponse:
        identity_id = request.path_params["identity_id"]
        if identity_id not in PROFILE_IDS:
            return JSONResponse({"error": "unknown identity"}, status_code=404)
        try:
            payload = await request.json()
        except ValueError, UnicodeDecodeError:
            return JSONResponse(
                {"errors": {"body": "invalid JSON body"}}, status_code=400
            )
        if not isinstance(payload, dict):
            return JSONResponse(
                {"errors": {"body": "expected an object"}}, status_code=400
            )
        errors = validate({**payload, "role": identity_id}, file_stem=identity_id)
        for field in payload.keys() - {"name", "label", "description"}:
            errors[field] = "field is read-only or unknown"
        if errors:
            return JSONResponse({"errors": errors}, status_code=400)
        profile = Profile(
            identity_id,
            payload["name"],
            payload["label"],
            payload["description"],
            identity_id,
        )
        try:
            _write_atomic(
                config_dir() / "identities" / f"{identity_id}.toml", render(profile)
            )
        except OSError:
            return JSONResponse({"error": "could not save identity"}, status_code=500)
        supervisor = await _supervisor(get_supervisor)
        profiles, _ = _profiles(config_dir() / "identities")
        identity = next(
            entry
            for entry in group(
                await _agent_rows(supervisor),
                SessionRegistry(
                    supervisor.data_dir / "registry.json"
                ).bindings_by_session_id(),
                profiles,
            )
            if entry["id"] == identity_id
        )
        if identity_id not in EXPANDED_ROLES:
            identity["instances"] = None
        return JSONResponse(dataclasses.asdict(profile) | identity)

    return [
        Route("/api/identities", identities, methods=["GET"]),
        Route(
            "/api/identities/{identity_id:str}/instances", instances, methods=["GET"]
        ),
        Route("/api/identities/{identity_id:str}", update, methods=["PUT"]),
    ]


def _identity_default(identity_id: str) -> dict[str, Any]:
    return {
        "id": identity_id,
        "name": identity_id,
        "label": identity_id,
        "description": "",
        "role": identity_id,
        "kind": "unknown",
        "count": 0,
        "worst_state": None,
        "instances": None,
    }
