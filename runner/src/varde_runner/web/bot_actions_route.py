"""Bot-only say, notes, mailbox and backlog-body actions."""

from __future__ import annotations

import asyncio
import json
import os
import stat
import tempfile
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from varde_data.errors import Locked
from varde_data.locking import atomic_write, file_lock
from varde_data.repos.chat import ChatRepository

from varde_runner.bot_actions import replace_plan_body
from varde_runner.bot_taint import is_bot_rooted
from varde_runner.web.queue import _plan_record

MAX_ACTION_TEXT = 20_000


def _json_object(value: Any) -> dict[str, Any] | JSONResponse:
    if not isinstance(value, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    return value


def _identity(request: Request) -> JSONResponse | None:
    identity = request.scope.get("bot_identity")
    if identity is None or not is_bot_rooted(identity.actor):
        return JSONResponse({"error": "bot identity required"}, status_code=403)
    return None


def create_bot_action_routes(
    *,
    chat: ChatRepository,
    cli: Any,
    working_dir: Path,
    data_dir: Path,
) -> list[Route]:
    return [
        Route("/api/bot/say", partial(_say, chat=chat), methods=["POST"]),
        Route(
            "/api/bot/notes",
            partial(_notes, working_dir=working_dir),
            methods=["POST"],
        ),
        Route(
            "/api/bot/mailbox",
            partial(_mailbox, cli=cli, data_dir=data_dir),
            methods=["POST"],
        ),
        Route(
            "/api/plans/{plan_id:str}/body",
            partial(_edit_body, cli=cli, working_dir=working_dir),
            methods=["PUT"],
        ),
    ]


async def _say(request: Request, *, chat: ChatRepository) -> JSONResponse:
    if refusal := _identity(request):
        return refusal
    payload = _json_object(await _request_json(request))
    if isinstance(payload, JSONResponse):
        return payload
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_ACTION_TEXT:
        return JSONResponse(
            {"error": "text must be non-empty and at most 20000 characters"},
            status_code=400,
        )
    message = await asyncio.to_thread(
        chat.append_event, "say", text.strip(), None, "main"
    )
    return JSONResponse({"message_id": message.id}, status_code=201)


async def _notes(request: Request, *, working_dir: Path) -> JSONResponse:
    if refusal := _identity(request):
        return refusal
    payload = _json_object(await _request_json(request))
    if isinstance(payload, JSONResponse):
        return payload
    text = payload.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_ACTION_TEXT:
        return JSONResponse(
            {"error": "text must be non-empty and at most 20000 characters"},
            status_code=400,
        )
    path = working_dir / "session-notes" / "manager-bot" / "notes.md"
    try:
        await asyncio.to_thread(_append_note, path, text.strip())
    except OSError:
        return JSONResponse(
            {"error": "manager notes could not be saved"}, status_code=500
        )
    return JSONResponse({"path": str(path)})


async def _mailbox(request: Request, *, cli: Any, data_dir: Path) -> JSONResponse:
    if refusal := _identity(request):
        return refusal
    payload = _json_object(await _request_json(request))
    if isinstance(payload, JSONResponse):
        return payload
    asked, why, options = (
        payload.get("asked"),
        payload.get("why", ""),
        payload.get("options"),
    )
    if (
        not isinstance(asked, str)
        or not asked.strip()
        or len(asked) > 2_000
        or not isinstance(why, str)
        or len(why) > 4_000
        or not isinstance(options, list)
        or not options
        or len(options) > 8
        or any(
            not isinstance(item, str) or not item.strip() or len(item) > 200
            for item in options
        )
    ):
        return JSONResponse(
            {"error": "asked, why and up to eight non-empty options are required"},
            status_code=400,
        )
    notes_dir = data_dir / "manager-bot" / "mailbox"
    try:
        notes_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError:
        return JSONResponse(
            {"error": "mailbox notes directory is unavailable"}, status_code=500
        )
    notes = notes_dir / f"question-{os.urandom(12).hex()}.json"
    document = {
        "type": "question",
        "asked": asked.strip(),
        "why": why.strip(),
        "options": options,
        "created_at": datetime.now(UTC).isoformat(),
    }
    try:
        atomic_write(
            notes,
            (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode(),
            mode=0o600,
        )
    except OSError:
        return JSONResponse(
            {"error": "mailbox notes could not be saved"}, status_code=500
        )
    try:
        result = await asyncio.to_thread(
            cli.send,
            sender="manager",
            recipient="main",
            kind="needs-user",
            text=f"Manager bot asks: {asked.strip()}",
            notes=str(notes),
        )
    except Exception as exc:  # noqa: BLE001 - CLI adapters vary by deployment.
        notes.unlink(missing_ok=True)
        return JSONResponse(
            {"error": f"mailbox item could not be sent ({type(exc).__name__})"},
            status_code=503,
        )
    return JSONResponse({"message_id": result.get("id")}, status_code=201)


async def _edit_body(  # noqa: PLR0911 - each failure returns a specific HTTP response.
    request: Request, *, cli: Any, working_dir: Path
) -> JSONResponse:
    if refusal := _identity(request):
        return refusal
    payload = _json_object(await _request_json(request))
    if isinstance(payload, JSONResponse):
        return payload
    body = payload.get("body")
    if not isinstance(body, str) or len(body) > 100_000:
        return JSONResponse(
            {"error": "body must be text no longer than 100000 characters"},
            status_code=400,
        )
    plan_id = request.path_params["plan_id"]
    record = await asyncio.to_thread(_plan_record, working_dir, plan_id)
    if record is None:
        return JSONResponse({"error": "plan not found"}, status_code=404)
    if record.status != "backlog":
        return JSONResponse(
            {"error": "only backlog plans can be edited"}, status_code=409
        )
    path = Path(record.path)
    try:
        _write_plan_body(path, body, cli)
    except TimeoutError, Locked:
        return JSONResponse({"error": "plan is being edited; retry"}, status_code=409)
    except OSError:
        return JSONResponse({"error": "plan body could not be saved"}, status_code=500)
    except Exception as exc:  # noqa: BLE001 - validator returns command exceptions.
        return JSONResponse(
            {"error": f"updated plan is invalid ({type(exc).__name__})"},
            status_code=400,
        )
    return JSONResponse({"plan_id": plan_id, "saved": True})


def _write_plan_body(path: Path, body: str, cli: Any) -> None:
    with file_lock(path.with_name(f".{path.name}.bot-edit.lock"), timeout=2):
        original = path.read_bytes()
        updated = replace_plan_body(original, body)
        if updated is None:
            raise ValueError("plan frontmatter is missing or invalid")
        candidate = _candidate_path(path, updated)
        try:
            cli._json("plan", "validate", str(candidate))
        finally:
            candidate.unlink(missing_ok=True)
        mode = stat.S_IMODE(path.stat().st_mode)
        atomic_write(path, updated, mode=mode)


async def _request_json(request: Request) -> Any:
    try:
        return await request.json()
    except ValueError, UnicodeError:
        return None


def _append_note(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = path.with_name(f".{path.name}.lock")
    with file_lock(lock, timeout=2):
        previous = path.read_text(encoding="utf-8") if path.exists() else ""
        separator = "" if not previous or previous.endswith("\n") else "\n"
        data = f"{previous}{separator}{text}\n".encode()
        atomic_write(path, data, mode=0o600)


def _candidate_path(path: Path, body: bytes) -> Path:
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=".bot-plan-candidate-", suffix=".md", delete=False
    ) as candidate:
        candidate.write(body)
        candidate.flush()
        os.fsync(candidate.fileno())
        return Path(candidate.name)
