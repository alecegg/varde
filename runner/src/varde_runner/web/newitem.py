"""New-item form and plan approval actions."""

from __future__ import annotations

import asyncio
import json
import subprocess
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import NoReturn

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from varde_data.errors import Invalid
from varde_data.records.messages import Message
from varde_data.workitem_sync import sync_workitem_message

from varde_runner.config import ConfigError, config_path
from varde_runner.intake import InboxProjector
from varde_runner.web.workspaces import create_workspaces_routes, validate_project
from varde_runner.workitems import MAX_TEXT_LENGTH, WorkItemStore

_PLAN_TEXT_LIMIT = 20_000
_PLAN_TRUNCATION_MARKER = "\n\n[Plan truncated at 20,000 characters.]"


def _raise_validation(error: Exception) -> NoReturn:
    raise error


def _no_plugin() -> None:
    return None


def create_newitem_routes(
    data_dir: Path,
    store: WorkItemStore | None = None,
    get_plugin: Callable | None = None,
    workspaces_service=None,
) -> list[Route]:
    store = store or WorkItemStore(data_dir)
    plugin = get_plugin if get_plugin is not None else _no_plugin
    return [
        *create_workspaces_routes(plugin, store, workspaces_service),
        Route("/api/work-items", _list_handler(store), methods=["GET"]),
        Route(
            "/api/work-items",
            _submit_handler(store, plugin, workspaces_service),
            methods=["POST"],
        ),
        Route("/api/work-items/{item_id:str}", _detail_handler(store), methods=["GET"]),
        Route(
            "/api/work-items/{item_id:str}/decision",
            _decision_handler(store),
            methods=["POST"],
        ),
        Route(
            "/api/work-items/{item_id:str}/plan-ready",
            _plan_ready_handler(store),
            methods=["POST"],
        ),
        Route(
            "/api/work-items/{item_id:str}/questions/{decision_id:str}/answer",
            _answer_handler(store),
            methods=["POST"],
        ),
        Route(
            "/new-item",
            _submit_handler(store, plugin, workspaces_service),
            methods=["POST"],
        ),
        Route(
            "/new-item/{item_id:str}/decision",
            _decision_handler(store),
            methods=["POST"],
        ),
        Route(
            "/new-item/{item_id:str}/plan-ready",
            _plan_ready_handler(store),
            methods=["POST"],
        ),
        Route(
            "/new-item/{item_id:str}/questions/{decision_id:str}/answer",
            _answer_handler(store),
            methods=["POST"],
        ),
    ]


def _list_handler(store: WorkItemStore):
    async def list_items(request: Request) -> JSONResponse:
        _sync_questions(request, store)
        return JSONResponse(
            {"work_items": [_item_json(store, item.id) for item in store.list()]}
        )

    return list_items


def _detail_handler(store: WorkItemStore):
    async def detail(request: Request) -> JSONResponse:
        item_id = request.path_params["item_id"]
        _sync_questions(request, store)
        try:
            return JSONResponse(_item_json(store, item_id))
        except KeyError:
            return JSONResponse({"error": "work item not found"}, status_code=404)

    return detail


def _item_json(store: WorkItemStore, item_id: str) -> dict:
    item = store.get(item_id)
    result = {
        **asdict(item),
        "questions": store.questions(item_id),
        "audit": store.audit(item_id),
    }
    if item.state in {"ready", "queued"}:
        result["plan_text"] = _read_plan_text(item.plan_path)
    return result


def _read_plan_text(plan_path: str | None) -> str:
    if not plan_path:
        return ""
    try:
        text = Path(plan_path).read_text(encoding="utf-8")
    except OSError, UnicodeError:
        return ""
    if len(text) > _PLAN_TEXT_LIMIT:
        return text[:_PLAN_TEXT_LIMIT] + _PLAN_TRUNCATION_MARKER
    return text


def work_items_snapshot(store: WorkItemStore) -> list[dict]:
    return [_item_json(store, item.id) for item in store.list()]


def _sync_questions(request: Request, store: WorkItemStore) -> None:
    source = getattr(request.app.state, "projector", None)
    decisions = getattr(request.app.state, "decisions", None)
    if source is None or decisions is None:
        return
    projector = InboxProjector(
        store.data_dir / "inbox.sqlite3",
        read_messages=source.read_messages,
        read_plan=source.read_plan,
        decision_store=decisions,
    )
    try:
        projector.project()
    finally:
        projector.close()
    messages = getattr(source, "messages_repository", None)
    if messages is None:
        return
    for row in source.read_messages():
        message = _message_record(row)
        if message is not None:
            try:
                sync_workitem_message(
                    store.repository, messages, message, message.from_
                )
            except Invalid as exc:
                raise ValueError(str(exc)) from exc


def _message_record(row: dict) -> Message | None:
    message_id = row.get("id")
    sender = row.get("from")
    if not isinstance(message_id, str) or not isinstance(sender, str):
        return None
    return Message(
        ts=str(row.get("ts", "")),
        from_=sender,
        to=str(row.get("to", "")),
        kind=str(row.get("kind", "")),
        text=str(row.get("text", "")),
        notes=row.get("notes") if isinstance(row.get("notes"), str) else None,
        id=message_id,
    )


def _submit_handler(
    store: WorkItemStore, get_plugin: Callable, workspaces_service=None
):
    async def submit(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
        except json.JSONDecodeError, UnicodeDecodeError:
            return JSONResponse({"error": "invalid JSON"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse(
                {"error": "JSON body must be an object"}, status_code=400
            )
        text, key, project = (
            payload.get("text"),
            payload.get("idempotency_key"),
            payload.get("project"),
        )
        workspace_id = payload.get("workspace_id")
        if (
            not isinstance(text, str)
            or not isinstance(key, str)
            or (not isinstance(project, str) and not isinstance(workspace_id, str))
            or (workspace_id is not None and not isinstance(workspace_id, str))
        ):
            return JSONResponse(
                {
                    "error": "text, idempotency_key and project or workspace_id "
                    "are required"
                },
                status_code=400,
            )
        try:
            project = await validate_project(
                project or "", workspace_id, get_plugin, workspaces_service
            )
            item = store.create(key, text, project)
        except RuntimeError as exc:
            return JSONResponse({"error": str(exc)}, status_code=503)
        except ValueError as exc:
            return JSONResponse(
                {"error": str(exc)},
                status_code=413 if len(text) > MAX_TEXT_LENGTH else 400,
            )
        if store.claim_planner_start(item.id):
            start_planner = getattr(request.app.state, "work_item_start", None)
            if start_planner is None:
                supervisor = getattr(request.app.state, "supervisor", None)
                start_planner = getattr(supervisor, "start_planner_session", None)
            if start_planner is None:
                store.reset_planner_start(item.id)
                return JSONResponse(
                    {"error": "planner start is not configured"}, status_code=503
                )
            try:
                result = start_planner(item.id, Path(item.notes_path), item.project)
                if hasattr(result, "__await__"):
                    result = await result
                session_id = getattr(result, "session_id", result)
                item = store.attach_planner(item.id, str(session_id))
            except Exception as exc:  # noqa: BLE001 - provider failure is retryable.
                store.reset_planner_start(item.id)
                error = (
                    f"planner role is unavailable in {config_path()}: {exc}"
                    if isinstance(exc, ConfigError)
                    else f"planner session failed to start ({type(exc).__name__})"
                )
                return JSONResponse(
                    {
                        "error": error,
                        "state": "new",
                    },
                    status_code=503,
                )
        return JSONResponse(
            {
                "id": item.id,
                "state": item.state,
                "planner_session": item.planner_session,
            }
        )

    return submit


def _answer_handler(store: WorkItemStore):
    async def answer(request: Request) -> JSONResponse:
        item_id, decision_id = (
            request.path_params["item_id"],
            request.path_params["decision_id"],
        )
        try:
            payload = await request.json()
        except json.JSONDecodeError, UnicodeDecodeError:
            return JSONResponse({"error": "invalid JSON"}, status_code=400)
        if not isinstance(payload, dict):
            return JSONResponse(
                {"error": "JSON body must be an object"}, status_code=400
            )
        text, key = payload.get("text"), payload.get("idempotency_key")
        if not isinstance(text, str) or not isinstance(key, str) or not key:
            return JSONResponse(
                {"error": "text and idempotency_key are required"}, status_code=400
            )
        if len(text) > MAX_TEXT_LENGTH:
            return JSONResponse(
                {"error": "text exceeds maximum length"}, status_code=413
            )
        try:
            item = store.get(item_id)
            _sync_questions(request, store)
            question = next(
                (
                    row
                    for row in store.questions(item_id)
                    if row["msg_id"] == decision_id
                ),
                None,
            )
            if question is None:
                return JSONResponse({"error": "question not found"}, status_code=404)
            result = request.app.state.decisions.submit_answer(
                decision_id, key, f"workitem-{item.id[:40]}", text
            )
            if result.status_code != 200:
                return JSONResponse(
                    {"error": result.status}, status_code=result.status_code
                )
            store.answer(item_id, decision_id, text, key)
        except KeyError:
            return JSONResponse({"error": "work item not found"}, status_code=404)
        return JSONResponse(
            {
                "entry_id": result.entry_id,
                "status": result.status,
                "notes_path": result.notes_path,
            }
        )

    return answer


def _decision_handler(store: WorkItemStore):
    async def decision(request: Request) -> JSONResponse:
        item_id = request.path_params["item_id"]
        try:
            payload = await request.json()
            if not isinstance(payload, dict) or not isinstance(
                payload.get("approved"), bool
            ):
                _raise_validation(TypeError("approved must be a boolean"))
            approved = payload["approved"]
            item = store.get(item_id)
            if (
                approved
                and item.state in {"ready", "queued"}
                and not item.launch_request_id
            ):
                cli = getattr(request.app.state, "cli", None)
                if cli is None:
                    return JSONResponse(
                        {"error": "launch request publishing is not configured"},
                        status_code=503,
                    )
                notes_path = store.write_note(
                    item_id,
                    "launch-request.json",
                    json.dumps(
                        {
                            "work_item_event": "launch_request",
                            "item_id": item.id,
                            "plan_path": item.plan_path,
                        },
                        ensure_ascii=False,
                    ),
                )
                if store.claim_launch_request(item_id, Path(notes_path)):
                    try:
                        result = await asyncio.to_thread(
                            cli.send,
                            sender=f"workitem-{item.id[:40]}",
                            recipient="main",
                            kind="needs-user",
                            text="Orchestrator launch requested.",
                            notes=notes_path,
                        )
                    except Exception:
                        store.release_launch_request(item_id)
                        raise
                    message_id = result.get("id") if isinstance(result, dict) else None
                    item = store.record_launch_request(
                        item_id,
                        str(message_id or f"launch-request-{item.id}"),
                        Path(notes_path),
                    )
                else:
                    item = store.get(item_id)
            elif approved:
                item = store.decide(item_id, True)
            else:
                item = store.decide(item_id, False)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except KeyError:
            return JSONResponse({"error": "work item not found"}, status_code=404)
        except subprocess.SubprocessError:
            return JSONResponse(
                {"error": "could not publish orchestrator launch request"},
                status_code=503,
            )
        return JSONResponse(
            {
                "id": item.id,
                "state": item.state,
                "launch_request_id": item.launch_request_id,
            }
        )

    return decision


def _plan_ready_handler(store: WorkItemStore):
    async def plan_ready(request: Request) -> JSONResponse:
        item_id = request.path_params["item_id"]
        try:
            payload = await request.json()
            if not isinstance(payload, dict) or not isinstance(
                payload.get("notes_path"), str
            ):
                _raise_validation(TypeError("notes_path is required"))
            item = store.get(item_id)
            if item.plan_ready_id:
                return JSONResponse(
                    {
                        "id": item.id,
                        "state": item.state,
                        "message_id": item.plan_ready_id,
                    }
                )
            notes_path = Path(payload["notes_path"]).resolve(strict=True)
            if not store.owns_note(item_id, str(notes_path)):
                _raise_validation(
                    ValueError(
                        "notes_path must be inside this work item's notes directory"
                    )
                )
            context = json.loads(notes_path.read_text(encoding="utf-8"))
            if (
                not isinstance(context, dict)
                or context.get("work_item_event") != "plan_ready"
            ):
                _raise_validation(ValueError("notes must identify a plan_ready event"))
            plan_path = Path(context.get("plan_path", ""))
            if not plan_path.is_file():
                _raise_validation(
                    ValueError("plan_path must name an existing plan file")
                )
            context.update({"kind": "plan_ready", "plan_id": item.id})
            outgoing = store.write_note(
                item_id,
                f"plan-ready-{notes_path.name}",
                json.dumps(context, ensure_ascii=False),
            )
            # InboxProjector consumes needs-user/info/blocked/permission message kinds;
            # plan_ready is kept as a notes marker and context kind for compatibility.
            result = request.app.state.cli.send(
                sender=f"workitem-{item.id[:40]}",
                recipient="main",
                kind="needs-user",
                text="Plan ready for approval; see notes.",
                notes=outgoing,
            )
            message_id = result.get("id") if isinstance(result, dict) else None
            item = store.plan_ready(
                item_id, plan_path.resolve(), str(message_id or f"plan-ready-{item_id}")
            )
        except (
            json.JSONDecodeError,
            UnicodeDecodeError,
            TypeError,
            ValueError,
            OSError,
        ) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        except KeyError:
            return JSONResponse({"error": "work item not found"}, status_code=404)
        except subprocess.SubprocessError:
            return JSONResponse(
                {"error": "could not publish plan-ready item"}, status_code=503
            )
        return JSONResponse(
            {"id": item.id, "state": item.state, "message_id": item.plan_ready_id}
        )

    return plan_ready
