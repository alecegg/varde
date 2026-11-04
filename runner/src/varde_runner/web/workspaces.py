"""Shared workspace listing for the dashboard."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from varde_runner.plugins.registry import PluginRegistry
from varde_runner.workitems import WorkItemStore
from varde_runner.workspaces_service import WorkspaceError


async def _list_workspaces(source: Any) -> list[dict[str, Any]]:
    if source is None:
        return []
    if isinstance(source, PluginRegistry):
        result = []
        for plugin in source.plugins():
            method = getattr(plugin, "list_workspaces", None)
            if callable(method):
                value = method()
                workspaces = await value if inspect.isawaitable(value) else value
                if isinstance(workspaces, list):
                    result.extend(workspaces)
        return result
    return await source.list_workspaces()


def create_workspaces_routes(
    get_plugin: Callable[[], Any], store: WorkItemStore, service: Any = None
) -> list[Route]:
    async def list_workspaces(request: Request) -> JSONResponse:
        native = []
        native_answered = False
        source_error = None
        if service is not None:
            try:
                native = await service.list()
                native_answered = True
            except (RuntimeError, OSError) as exc:
                source_error = str(exc)
        try:
            plugin_source = get_plugin()
            plugin_workspaces = await _list_workspaces(plugin_source)
            plugin_answered = plugin_source is not None
        except (RuntimeError, OSError) as exc:
            source_error = str(exc)
            plugin_answered = False
            plugin_workspaces = []
        if not native_answered and not plugin_answered:
            return JSONResponse(
                {"error": source_error or "workspace sources unavailable"},
                status_code=503,
            )
        workspaces = list(native)
        native_cwds = {workspace.get("cwd") for workspace in native}
        workspaces.extend(
            workspace
            for workspace in plugin_workspaces
            if service is None or workspace.get("cwd") not in native_cwds
        )
        workspace_ids = {workspace["id"] for workspace in workspaces}
        latest_project = next(
            (
                item.project
                for item in reversed(store.list())
                if item.project in workspace_ids
            ),
            None,
        )
        return JSONResponse(
            {
                "workspaces": [
                    {
                        "id": workspace["id"],
                        "title": workspace["title"],
                        "cwd": workspace["cwd"],
                        "last_used": workspace["id"] == latest_project,
                        **{
                            key: workspace[key]
                            for key in ("kind", "branch", "repo", "head")
                            if key in workspace
                        },
                    }
                    for workspace in workspaces
                ]
            }
        )

    async def create_workspace(request: Request) -> JSONResponse:
        if service is None:
            return JSONResponse(
                {"error": "native workspaces are unavailable"}, status_code=404
            )
        try:
            payload = await request.json()
        except ValueError, UnicodeDecodeError:
            return JSONResponse({"error": "invalid JSON"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse(
                {"error": "JSON body must be an object"}, status_code=400
            )
        try:
            result = await service.create(
                payload.get("repo", ""),
                payload.get("id", ""),
                base=payload.get("base"),
                caller=payload.get("caller"),
            )
            return JSONResponse(result, status_code=201)
        except WorkspaceError as exc:
            return JSONResponse(
                {"error": str(exc), "code": exc.code}, status_code=exc.status
            )
        except RuntimeError as exc:
            return JSONResponse(
                {"error": str(exc), "code": "git_failed"}, status_code=500
            )
        except (ValueError, TypeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)

    async def remove_workspace(request: Request) -> JSONResponse:
        if service is None:
            return JSONResponse(
                {"error": "native workspaces are unavailable"}, status_code=404
            )
        query = request.query_params
        try:
            discard_value = query.get("discard", "false").lower()
            if discard_value not in {"true", "false"}:
                return JSONResponse(
                    {"error": "discard must be true or false"}, status_code=422
                )
            discard = discard_value == "true"
            result = await service.remove(
                query.get("repo", ""),
                query.get("id", ""),
                caller=query.get("caller"),
                discard=discard,
            )
            return JSONResponse(result)
        except WorkspaceError as exc:
            return JSONResponse(
                {"error": str(exc), "code": exc.code}, status_code=exc.status
            )
        except RuntimeError as exc:
            return JSONResponse(
                {"error": str(exc), "code": "git_failed"}, status_code=500
            )
        except (ValueError, TypeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)

    return [
        Route("/api/workspaces", list_workspaces, methods=["GET"]),
        Route("/api/workspaces", create_workspace, methods=["POST"]),
        Route("/api/workspaces", remove_workspace, methods=["DELETE"]),
    ]


async def validate_project(
    project: str,
    workspace_id: str | None,
    get_plugin: Callable[[], Any],
    service: Any = None,
) -> str:
    selected = workspace_id or project
    if Path(project).is_dir() and workspace_id is None:
        return project
    plugin = get_plugin()
    try:
        workspaces = await _list_workspaces(plugin) if plugin is not None else []
    except RuntimeError, OSError:
        return selected
    if service is not None:
        try:
            native = await service.list()
        except RuntimeError, OSError:
            native = []
        if plugin is None and not native:
            return selected
        seen = {workspace.get("cwd") for workspace in native}
        workspaces = native + [
            workspace for workspace in workspaces if workspace.get("cwd") not in seen
        ]
    elif plugin is None:
        return selected
    if any(workspace.get("id") == selected for workspace in workspaces):
        return selected
    raise ValueError("project must be an existing directory or listed workspace")
