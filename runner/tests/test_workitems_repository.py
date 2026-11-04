from __future__ import annotations

from pathlib import Path

import pytest
import varde_runner.workitems as workitems_module
from varde_data.errors import Invalid
from varde_data.workitems import open_workitems
from varde_runner.workitems import WorkItemStore


def test_facade_and_repository_share_full_work_item_scenario(tmp_path: Path) -> None:
    store = WorkItemStore(tmp_path)
    repository = open_workitems(tmp_path)
    item = store.create("scenario", "describe the work", "project-a")
    assert store.create("scenario", "ignored duplicate", "project-a") == item
    store.start_planning(item.id, "planner-session")
    question = {"asked": "Which target?", "options": ["A", "B"]}
    assert store.question(item.id, "question-1", question)
    assert store.answer(item.id, "question-1", "A", "answer-key")

    note_path = store.write_note(item.id, "plan.md", "plan contents")
    assert store.owns_note(item.id, note_path)
    assert not store.owns_note(item.id, str(tmp_path / "outside.md"))
    ready = store.plan_ready(item.id, Path(note_path), "ready-1")
    queued = store.decide(ready.id, True)
    assert store.claim_launch_request(item.id, Path(note_path))
    launched = store.record_launch_request(item.id, "launch-1", Path(note_path))

    assert repository.get(item.id) == launched
    assert repository.questions(item.id)[0].payload == question
    assert repository.questions(item.id)[0].answer == "A"
    assert [entry.new_state for entry in repository.audit(item.id)] == [
        entry["new_state"] for entry in store.audit(item.id)
    ]
    assert repository.audit(item.id)[-1].detail == "launch request claimed"
    assert queued.state == "queued"
    store.close()
    close = getattr(repository, "close", None)
    if close is not None:
        close()


def test_work_item_stores_share_writes_for_one_data_directory(tmp_path: Path) -> None:
    first = WorkItemStore(tmp_path)
    second = WorkItemStore(tmp_path)

    item = first.create("shared", "visible to both stores", "project-a")
    assert second.get(item.id) == item
    second.start_planning(item.id, "shared-planner")
    assert first.get(item.id).planner_session == "shared-planner"

    first.close()
    second.close()


def test_sync_message_caches_repository_and_maps_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = WorkItemStore(tmp_path)
    opened = []
    original_open_data = workitems_module.open_data

    def counting_open_data(*args, **kwargs):
        opened.append(args)
        return original_open_data(*args, **kwargs)

    def invalid_sync(*args, **kwargs):
        raise Invalid("bad message state")

    monkeypatch.setattr(workitems_module, "open_data", counting_open_data)
    monkeypatch.setattr(workitems_module, "sync_workitem_message", invalid_sync)
    with pytest.raises(ValueError, match="bad message state"):
        store.sync_message(
            {"id": "message-1", "from": "workitem-item"}, "workitem-item"
        )
    assert len(opened) == 1

    with pytest.raises(ValueError, match="bad message state"):
        store.sync_message(
            {"id": "message-2", "from": "workitem-item"}, "workitem-item"
        )
    assert len(opened) == 1
    store.close()
