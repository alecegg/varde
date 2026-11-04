from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import asdict
from itertools import count
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import varde_runner.workitems as workitems_module
from starlette.applications import Starlette
from varde_runner.web.newitem import create_newitem_routes
from varde_runner.workitems import WorkItemStore

GOLDENS = Path(__file__).parent / "golden" / "workitems"


def snapshot(store: WorkItemStore, item_id: str, returned=None) -> dict:
    return {
        "returned": asdict(returned)
        if returned is not None
        else asdict(store.get(item_id)),
        "questions": store.questions(item_id),
        "audit": store.audit(item_id),
    }


def normalize(value, root: Path):
    if isinstance(value, dict):
        return {key: normalize(item, root) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize(item, root) for item in value]
    if isinstance(value, str):
        return re.sub(r"[0-9a-f]{32}", "<ID>", value.replace(str(root), "<DATA>"))
    return value


async def request_json(app, path: str) -> dict:
    messages = []
    delivered = False

    async def receive():
        nonlocal delivered
        if delivered:
            return {"type": "http.disconnect"}
        delivered = True
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await app(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "query_string": b"",
            "headers": [],
            "server": ("test", 80),
            "client": ("test", 1),
            "scheme": "http",
            "http_version": "1.1",
        },
        receive,
        send,
    )
    body = next(
        message["body"]
        for message in messages
        if message["type"] == "http.response.body"
    )
    return json.loads(body)


async def _api_snapshots(app, item_id: str) -> dict:
    return {
        "list": await request_json(app, "/api/work-items"),
        "detail": await request_json(app, f"/api/work-items/{item_id}"),
    }


def test_workitem_scenarios_match_golden(tmp_path, monkeypatch):  # noqa: PLR0915
    # UPDATE_WORKITEM_GOLDENS must run against this unchanged store implementation.
    identifiers = count(1)
    monkeypatch.setattr(
        workitems_module.uuid,
        "uuid4",
        lambda: SimpleNamespace(hex=f"golden-{next(identifiers):02d}"),
    )
    data = tmp_path / "data"
    store = WorkItemStore(data)
    result = {}

    item = store.create("create-key", "A deterministic request", "workspace")
    result["create"] = [snapshot(store, item.id, item)]
    repeated = store.create("create-key", "ignored text", "ignored-project")
    result["create"].append(snapshot(store, item.id, repeated))

    item = store.create("planner-key", "Plan this", "workspace")
    steps = [snapshot(store, item.id, item)]
    item = store.start_planning(item.id, "planner-session")
    steps.append(snapshot(store, item.id, item))
    claimed_item = store.create("claim-key", "Claim this", "workspace")
    claimed = store.claim_planner_start(claimed_item.id)
    steps.append({"claimed": claimed, **snapshot(store, claimed_item.id)})
    reset = store.reset_planner_start(claimed_item.id)
    steps.append(snapshot(store, claimed_item.id, reset))
    result["planning_claim_reset"] = steps

    item = store.create("question-key", "Need clarification", "workspace")
    steps = [snapshot(store, item.id, item)]
    item = store.start_planning(item.id, "planner-question")
    steps.append(snapshot(store, item.id, item))
    payload = {"asked": "Which target?", "options": ["A", "B"]}
    added = store.question(item.id, "question-1", payload)
    steps.append({"added": added, **snapshot(store, item.id)})
    answered = store.answer(item.id, "question-1", "A", "answer-key")
    steps.append({"answered": answered, **snapshot(store, item.id)})
    plan_path = data / "plans" / "plan.md"
    plan_path.parent.mkdir()
    plan_path.write_text("# Deterministic plan\n", encoding="utf-8")
    ready = store.plan_ready(item.id, plan_path, "ready-message")
    steps.append(snapshot(store, item.id, ready))
    result["question_answer_ready"] = steps

    for name, approved in (("approve", True), ("reject", False)):
        item = store.create(f"{name}-key", f"{name} me", "workspace")
        store.start_planning(item.id, f"planner-{name}")
        ready = store.plan_ready(item.id, plan_path, f"{name}-ready")
        ready_snapshot = snapshot(store, item.id, ready)
        decided = store.decide(item.id, approved)
        result[name] = [ready_snapshot, snapshot(store, item.id, decided)]

    item = store.create("fail-key", "Fail this", "workspace")
    store.start_planning(item.id, "planner-fail")
    failed = store.fail(item.id, "planner crashed")
    result["fail"] = [snapshot(store, item.id, failed)]

    item = store.create("launch-key", "Launch this", "workspace")
    store.start_planning(item.id, "planner-launch")
    store.plan_ready(item.id, plan_path, "launch-ready")
    store.decide(item.id, True)
    note = data / "launch.md"
    claimed = store.claim_launch_request(item.id, note)
    steps = [{"claimed": claimed, **snapshot(store, item.id)}]
    recorded = store.record_launch_request(item.id, "launch-message", note)
    steps.append(snapshot(store, item.id, recorded))
    store.release_launch_request(item.id)
    steps.append(snapshot(store, item.id))
    result["launch_request"] = steps

    item = store.create("sync-key", "Sync this", "workspace")
    store.start_planning(item.id, "planner-sync")
    message_notes = data / "message.json"
    message_notes.write_text(
        json.dumps({"work_item_event": "question", "asked": "Proceed?"}),
        encoding="utf-8",
    )
    question_synced = store.sync_message(
        {
            "id": "sync-question",
            "from": f"workitem-{item.id[:40]}",
            "kind": "needs-user",
            "notes": str(message_notes),
        },
        f"workitem-{item.id[:40]}",
    )
    steps = [{"synced": question_synced, **snapshot(store, item.id)}]
    plan_path.write_text("# Synced plan\n", encoding="utf-8")
    message_notes.write_text(
        json.dumps({"work_item_event": "plan_ready", "plan_path": str(plan_path)}),
        encoding="utf-8",
    )
    ready_synced = store.sync_message(
        {
            "id": "sync-ready",
            "from": f"workitem-{item.id[:40]}",
            "kind": "message",
            "notes": str(message_notes),
        },
        f"workitem-{item.id[:40]}",
    )
    steps.append({"synced": ready_synced, **snapshot(store, item.id)})
    result["sync_message"] = steps

    api_data = tmp_path / "api-data"
    api_store = WorkItemStore(api_data)
    api_item = api_store.create("api-key", "API request", "workspace")
    app = Starlette(routes=create_newitem_routes(api_data, api_store))
    result["api"] = normalize(asyncio.run(_api_snapshots(app, api_item.id)), api_data)
    payloads = cast("dict[str, Any]", normalize(result, data))
    store.close()
    api_store.close()

    for name, payload in payloads.items():
        path = GOLDENS / f"{name}.json"
        rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        if os.environ.get("UPDATE_WORKITEM_GOLDENS") == "1":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(rendered, encoding="utf-8")
        assert path.read_text(encoding="utf-8") == rendered, name


def test_edge_scenarios_match_golden(tmp_path, monkeypatch):  # noqa: PLR0915
    identifiers = count(100)
    monkeypatch.setattr(
        workitems_module.uuid,
        "uuid4",
        lambda: SimpleNamespace(hex=f"golden-{next(identifiers):02d}"),
    )
    data = tmp_path / "edge-data"
    store = WorkItemStore(data)
    result: dict[str, Any] = {}
    item = store.create("edge", "Request", "workspace")
    by_key = store.by_key("edge")
    assert by_key is not None
    result["new"] = {
        "item": asdict(item),
        "by_key": asdict(by_key),
        "list": [asdict(row) for row in store.list()],
    }
    result["attach_in_new"] = asdict(store.attach_planner(item.id, "ignored"))
    result["first_claim"] = store.claim_planner_start(item.id)
    result["second_claim"] = store.claim_planner_start(item.id)
    result["reset_claim"] = asdict(store.reset_planner_start(item.id))
    store.start_planning(item.id, "session")
    session_item = store.for_planner_session("session")
    assert session_item is not None
    result["session_lookup"] = asdict(session_item)

    multi = store.create("multi", "Questions", "workspace")
    store.start_planning(multi.id, "multi-session")
    result["question_first"] = store.question(multi.id, "q-b", {"asked": "B"})
    result["question_duplicate"] = store.question(
        multi.id, "q-b", {"asked": "duplicate"}
    )
    store.question(multi.id, "q-a", {"asked": "A"})
    result["question_order"] = [row["msg_id"] for row in store.questions(multi.id)]
    result["recovery_context"] = store.recovery_context(multi.id)
    result["answer_first"] = store.answer(multi.id, "q-a", "A", "key-a")
    result["state_after_one_answer"] = store.get(multi.id).state
    result["answer_last"] = store.answer(multi.id, "q-b", "B", "key-b")
    result["answer_duplicate"] = store.answer(multi.id, "q-b", "B2", "key-b2")
    try:
        store.answer(multi.id, "unknown", "x", "x")
    except KeyError as exc:
        result["unknown_answer"] = type(exc).__name__

    nonready = store.create("nonready", "Not ready", "workspace")
    try:
        store.decide(nonready.id, True)
    except ValueError as exc:
        result["decide_nonready"] = type(exc).__name__
    try:
        store.plan_ready(nonready.id, data / "plan.md", "wrong")
    except ValueError as exc:
        result["ready_wrong_state"] = type(exc).__name__
    try:
        store.question(nonready.id, "wrong", {})
    except ValueError as exc:
        result["question_wrong_state"] = type(exc).__name__
    result["claim_launch_from_new"] = store.claim_launch_request(
        nonready.id, data / "notes.md"
    )

    sync_item = store.create("sync-edge", "Sync", "workspace")
    store.start_planning(sync_item.id, "sync-session")
    address = f"workitem-{sync_item.id[:40]}"
    sync_cases = {
        "wrong_sender": (
            {
                "from": "other",
                "kind": "needs-user",
                "id": "wrong-sender",
                "notes": str(data / "sync.json"),
            },
            {"asked": "ignored"},
        ),
        "launch_request": (
            {
                "from": address,
                "kind": "needs-user",
                "id": "launch-event",
                "notes": str(data / "sync.json"),
            },
            {"work_item_event": "launch_request"},
        ),
        "non_dict": (
            {
                "from": address,
                "kind": "needs-user",
                "id": "non-dict",
                "notes": str(data / "sync.json"),
            },
            [],
        ),
        "wrong_kind": (
            {
                "from": address,
                "kind": "message",
                "id": "wrong-kind",
                "notes": str(data / "sync.json"),
            },
            {"asked": "ignored"},
        ),
        "missing_plan": (
            {
                "from": address,
                "kind": "message",
                "id": "missing-plan",
                "notes": str(data / "sync.json"),
            },
            {"work_item_event": "plan_ready", "plan_path": str(data / "absent.md")},
        ),
    }
    for name, (message, payload) in sync_cases.items():
        note = data / "sync.json"
        note.write_text(json.dumps(payload), encoding="utf-8")
        result[f"sync_{name}"] = store.sync_message(message, address)
    result["sync_missing_note"] = store.sync_message(
        {
            "from": address,
            "kind": "needs-user",
            "id": "missing-note",
            "notes": str(data / "absent.json"),
        },
        address,
    )
    result["sync_unreadable_note"] = store.sync_message(
        {"from": address, "kind": "needs-user", "id": "unreadable", "notes": str(data)},
        address,
    )

    for state in ("queued", "rejected", "failed"):
        terminal = store.create(f"fail-{state}", state, "workspace")
        store.start_planning(terminal.id, "terminal-session")
        store.plan_ready(terminal.id, data / "plan.md", f"ready-{state}")
        if state != "failed":
            store.decide(terminal.id, state == "queued")
        else:
            store.fail(terminal.id, "failed")
        before = snapshot(store, terminal.id)
        store.fail(terminal.id, "ignored")
        result[f"fail_{state}_noop"] = before == snapshot(store, terminal.id)
        if state in {"queued", "rejected"}:
            result[f"decide_{state}_noop"] = asdict(
                store.decide(terminal.id, state == "queued")
            )

    launch = store.create("launch", "Launch", "workspace")
    store.start_planning(launch.id, "launch-session")
    store.plan_ready(launch.id, data / "plan.md", "launch-ready")
    store.decide(launch.id, True)
    result["launch_claim"] = store.claim_launch_request(launch.id, data / "launch.md")
    result["launch_second_claim"] = store.claim_launch_request(
        launch.id, data / "launch.md"
    )
    store.release_launch_request(launch.id)
    result["launch_release_sending"] = asdict(store.get(launch.id))
    store.claim_launch_request(launch.id, data / "launch.md")
    store.record_launch_request(launch.id, "launch-id", data / "launch.md")
    before_release = asdict(store.get(launch.id))
    store.release_launch_request(launch.id)
    result["launch_release_recorded_noop"] = before_release == asdict(
        store.get(launch.id)
    )
    store.close()

    payload = cast("dict[str, Any]", normalize(result, data))
    path = GOLDENS / "edge_cases.json"
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if os.environ.get("UPDATE_WORKITEM_GOLDENS") == "1":
        path.write_text(rendered, encoding="utf-8")
    assert path.read_text(encoding="utf-8") == rendered
