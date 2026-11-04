from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import UTC, datetime
from itertools import count
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import varde_runner.decisions as decisions_module
from varde_runner.decisions import DecisionProjection, DecisionStore
from varde_runner.web.app import _stored_mailbox_reply

GOLDENS = Path(__file__).parent / "golden" / "decisions"


def _normalize(value: Any, root: Path) -> Any:
    if isinstance(value, dict):
        return {key: _normalize(item, root) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item, root) for item in value]
    if isinstance(value, str):
        return value.replace(str(root), "<DATA>")
    return value


def _capture(store, result, decision_id, key, root) -> dict[str, Any]:
    entry = store.get_entry(key)
    normalized = _normalize(
        {
            "result": asdict(result) if result is not None else None,
            "decision": store.get_decision(decision_id),
            "entry": asdict(entry) if entry else None,
            "audit_rows": store.audit_rows(),
            "audit_jsonl": [
                json.loads(line)
                for line in (
                    store.audit_path.read_text().splitlines()
                    if store.audit_path.exists()
                    else []
                )
            ],
        },
        root,
    )
    assert isinstance(normalized, dict)
    return normalized


def test_decision_scenarios_match_golden(tmp_path, monkeypatch):  # noqa: PLR0915
    ids = count(1)
    monkeypatch.setattr(
        decisions_module.uuid,
        "uuid4",
        lambda: SimpleNamespace(hex=f"entry-{next(ids):02d}"),
    )

    clock = count()

    class IncrementingDateTime:
        @staticmethod
        def now(tz=None):
            return datetime(2026, 10, 22, 12, 0, next(clock), tzinfo=tz or UTC)

    monkeypatch.setattr(decisions_module, "datetime", IncrementingDateTime)
    data = tmp_path / "decisions"
    sent = []
    messages = []
    events = []
    write_back_calls = []

    def send(**kwargs):
        sent.append(kwargs)
        if kwargs["recipient"] == "fail-agent":
            raise RuntimeError("send failed")
        return {"id": f"delivery-{len(sent)}"}

    def write_back(plan_id, question, body):
        write_back_calls.append(
            {"plan_id": plan_id, "question": question, "body": body}
        )

    store = DecisionStore(
        data,
        send=send,
        read_messages=lambda: messages,
        write_back=write_back,
        recorder=lambda event, decision: events.append(
            {"event": event, "decision": decision}
        ),
    )
    snapshots = {}

    def project(name, kind="question", context=None):
        store.project(
            DecisionProjection(
                name,
                name,
                kind,
                f"Title {name}",
                f"Body {name}",
                context or {},
                plan_id="plan-1" if context else None,
            )
        )

    project("project-repeat")
    snapshots["project"] = [_capture(store, None, "project-repeat", "missing", data)]
    store.project(
        DecisionProjection(
            "source-2", "project-repeat", "question", "Updated", "Updated body", {}
        )
    )
    snapshots["project"].append(
        _capture(store, None, "project-repeat", "missing", data)
    )
    result = store.submit_answer("project-repeat", "answer-1", "agent", "yes")
    snapshots["project"].append(
        _capture(store, result, "project-repeat", "answer-1", data)
    )
    store.project(
        DecisionProjection(
            "source-after-answer",
            "project-repeat",
            "question",
            "Changed",
            "Changed body",
            {},
        )
    )
    snapshots["project"].append(
        _capture(store, None, "project-repeat", "answer-1", data)
    )

    project("dismiss-restore")
    snapshots["dismiss_restore"] = []
    dismissed_changed = store.dismiss("dismiss-restore")
    dismissed = _capture(store, None, "dismiss-restore", "missing", data)
    assert isinstance(dismissed, dict)
    snapshots["dismiss_restore"].append(
        {
            "changed": dismissed_changed,
            **dismissed,
        }
    )
    restored_changed = store.restore("dismiss-restore")
    restored = _capture(store, None, "dismiss-restore", "missing", data)
    assert isinstance(restored, dict)
    snapshots["dismiss_restore"].append(
        {
            "changed": restored_changed,
            **restored,
        }
    )

    scenarios = [
        ("send_failure", "send-failure", "send-fail", "fail-agent", "body"),
        ("notes_failure", "notes-failure", "notes-fail", "agent", "body"),
        ("idempotency", "idempotency", "same-key", "agent", "original"),
        ("already_answered", "already-answered", "already-key", "agent", "body"),
        ("permission", "permission", "permission-key", "agent", "allow"),
        ("writeback", "writeback", "writeback-key", "agent", "answer"),
    ]
    original_write = Path.write_bytes
    for name, decision_id, key, recipient, body in scenarios:
        context = {"question": "q-1", "type": "question"} if name == "writeback" else {}
        project(
            decision_id, "permission" if name == "permission" else "question", context
        )
        if name == "notes_failure":
            monkeypatch.setattr(
                Path,
                "write_bytes",
                lambda self, value, original_write=original_write: (
                    (_ for _ in ()).throw(OSError("notes error"))
                    if self.parent == data / "notes"
                    else original_write(self, value)
                ),
            )
        if name == "writeback":
            attempts = count(1)
            store.write_back = lambda *args, attempts=attempts: (
                (_ for _ in ()).throw(RuntimeError("write failed"))
                if next(attempts) == 1
                else None
            )
        first = store.submit_answer(decision_id, key, recipient, body)
        entries = [_capture(store, first, decision_id, key, data)]
        if name == "notes_failure":
            monkeypatch.setattr(Path, "write_bytes", original_write)
        if name == "idempotency":
            entries.append(
                _capture(
                    store,
                    store.submit_answer(decision_id, key, recipient, body),
                    decision_id,
                    key,
                    data,
                )
            )
            entries.append(
                _capture(
                    store,
                    store.submit_answer(decision_id, key, recipient, "different"),
                    decision_id,
                    key,
                    data,
                )
            )
        elif name == "already_answered":
            entries.append(
                _capture(
                    store,
                    store.submit_answer(decision_id, "another-key", recipient, body),
                    decision_id,
                    "another-key",
                    data,
                )
            )
        elif name == "writeback":
            store.retry_plan_writebacks()
            store.retry_plan_writebacks()
            store.retry_plan_writebacks()
            entries.append(_capture(store, None, decision_id, key, data))
        elif name in {"send_failure", "notes_failure"}:
            store.send = lambda **kwargs: {"id": "retry-delivery"}
            retried = store.retry(key)
            entries.append(_capture(store, retried, decision_id, key, data))
        elif name == "permission":
            assert first.entry_id is not None
            entries.append(
                _capture(
                    store,
                    store.resolve_permission(first.entry_id, False),
                    decision_id,
                    key,
                    data,
                )
            )
            entries.append(
                _capture(
                    store,
                    store.resolve_permission(first.entry_id, True),
                    decision_id,
                    key,
                    data,
                )
            )
        snapshots[name] = entries
        entries[-1]["send_calls"] = _normalize(sent, data)
        entries[-1]["write_back_calls"] = _normalize(write_back_calls, data)

    long = store.submit_answer("long-answer", "long-key", "agent", "x" * 20_001)
    snapshots["too_long"] = _capture(store, long, "long-answer", "long-key", data)
    project("reconcile")
    initial = store.submit_answer("reconcile", "reconcile-key", "fail-agent", "body")
    reconcile_entry = store.get_entry("reconcile-key")
    assert reconcile_entry is not None
    store.db.execute(
        "UPDATE answers SET status='stored' WHERE entry_id=?",
        (reconcile_entry.entry_id,),
    )
    store.db.commit()
    messages.append({"id": "reconciled-message", "notes": reconcile_entry.notes_path})
    snapshots["retry_reconciled"] = [
        _capture(store, initial, "reconcile", "reconcile-key", data),
        _capture(
            store, store.retry("reconcile-key"), "reconcile", "reconcile-key", data
        ),
    ]
    project("writeback-cap", context={"question": "cap-q", "type": "question"})
    cap_key = "writeback-cap-key"
    store.write_back = lambda *args: (_ for _ in ()).throw(RuntimeError("write failed"))
    cap_entry = store.submit_answer("writeback-cap", cap_key, "agent", "answer")
    for _ in range(4):
        store.retry_plan_writebacks()
    snapshots["writeback_cap"] = _capture(
        store, cap_entry, "writeback-cap", cap_key, data
    )
    project("recover", context={"question": "recover-q", "type": "question"})
    store.submit_answer("recover", "recover-key", "agent", "recover body")
    recovered_entry = store.get_entry("recover-key")
    assert recovered_entry is not None
    store.db.execute(
        "UPDATE answers SET status='sending' WHERE entry_id=?",
        (recovered_entry.entry_id,),
    )
    store.db.commit()
    messages.append({"id": "recovered-message", "notes": recovered_entry.notes_path})
    snapshots["recover_sending"] = [
        _capture(store, item, "recover", "recover-key", data)
        for item in store.recover_sending()
    ]
    snapshots["mailbox_reply"] = _stored_mailbox_reply(store, "project-repeat")
    snapshots["recorder_events"] = _normalize(events, data)
    snapshots["send_calls"] = _normalize(sent, data)
    snapshots["write_back_calls"] = _normalize(write_back_calls, data)
    store.close()

    rendered = json.dumps(snapshots, ensure_ascii=False, indent=2) + "\n"
    path = GOLDENS / "scenarios.json"
    if os.environ.get("UPDATE_DECISION_GOLDENS") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
    assert path.read_text(encoding="utf-8") == rendered
