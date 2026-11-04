"""Write handlers: each calls a library function and returns JSON-safe data."""

from __future__ import annotations

import json
from typing import Any

from varde_data.config_keys import write_allowed
from varde_data.errors import Invalid
from varde_learn.docs.pages.comments import append_reply
from varde_learn.docs.pages.store import DecisionDenied, sources_for, store_comment
from varde_learn.loop import friction_repository
from varde_learn.loop.store import write as friction_write
from varde_learn.loop.store.paths import resolve_store_dir
from varde_learn.loop.store.types import FrictionAddMode, FrictionAddRequest
from varde_workflow.commands.msg import OutgoingMessage, SendError, send_message

from varde_serve.api.docs import plan_store, resolve_doc
from varde_serve.api.errors import ApiError
from varde_serve.project import Project

SOURCE = "serve"
SENDER = "serve"
AGENT_KINDS = ("comment", "suggestion")
MAX_TITLE = 80


def reorder_queue(project: Project) -> dict[str, Any]:
    """Not wired: serve's order file is read by nothing that dispatches."""
    raise ApiError(
        501,
        "reorder_not_wired",
        "queue reorder is not connected to the runner's ordering yet",
    )


def add_friction(project: Project, text: str, tags: list[str]) -> dict[str, Any]:
    if not text.strip():
        raise ApiError(400, "bad_request", "text must not be blank")
    title = " ".join(text.split())[:MAX_TITLE]
    request = FrictionAddRequest(
        FrictionAddMode.create(SOURCE, title, None, False),
        text,
        project.repository,
        list(tags),
    )
    try:
        item = friction_repository.with_repository(
            lambda repository: friction_write.add_friction(repository, request),
            resolve_store_dir(project.config_dir),
        )
    except Exception as error:  # library validation errors carry the message
        raise ApiError(400, "bad_request", str(error)) from error
    return {"id": item.id, "slug": item.slug}


def add_comment(project: Project, path: str, body: dict[str, Any]) -> dict[str, Any]:
    if body.get("kind", "comment") not in AGENT_KINDS:
        raise ApiError(400, "bad_request", "kind must be comment or suggestion")
    doc = resolve_doc(project, path)
    raw = json.dumps(body).encode()
    try:
        sources = sources_for(doc, raw, plan_store(project))
        return store_comment(doc, raw, decisions_open=False, sources=sources)
    except (ValueError, DecisionDenied) as error:
        raise ApiError(400, "bad_request", str(error)) from error


def add_reply(
    project: Project, path: str, comment_id: str, text: str
) -> dict[str, Any]:
    doc = resolve_doc(project, path)
    if not text.strip():
        raise ApiError(400, "bad_request", "text must not be blank")
    try:
        return append_reply(doc, comment_id, text)
    except ValueError as error:
        raise ApiError(404, "not_found", str(error)) from error


def answer_decision(
    project: Project, path: str, did: str, answer: str
) -> dict[str, Any]:
    doc = resolve_doc(project, path)
    body = {
        "kind": "answer",
        "anchor": did,
        "item": did,
        "value": answer,
        "text": "",
    }
    try:
        return store_comment(doc, json.dumps(body).encode(), decisions_open=True)
    except ValueError as error:
        raise ApiError(400, "bad_request", str(error)) from error


def send_mail(project: Project, to: str, kind: str, text: str) -> dict[str, Any]:
    try:
        message = send_message(OutgoingMessage(SENDER, to, kind, text), project.working)
    except SendError as error:
        raise ApiError(400, "bad_request", str(error)) from error
    return message.to_dict()


def set_config(project: Project, key: str, value: object) -> dict[str, Any]:
    try:
        return {"key": key, "value": write_allowed(project.config_dir, key, value)}
    except Invalid as error:
        raise ApiError(400, "bad_request", str(error)) from error
