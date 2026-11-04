from pathlib import Path

from varde_learn.docs.pages.comments import append_comment
from varde_serve.events.buffer import EventBuffer
from varde_serve.events.watchers import (
    doc_comment_watcher,
    plan_state_watcher,
    run_watchers,
)


def test_doc_comment_watcher_ignores_backlog_then_reports_new(tmp_path: Path) -> None:
    doc = tmp_path / "a.md"
    doc.write_text("# A\n")
    append_comment(doc, "top", "", "old")
    watcher = doc_comment_watcher(tmp_path)
    assert watcher() == []
    append_comment(doc, "top", "", "new")
    changes = watcher()
    assert [(kind, subject) for kind, subject, _ in changes] == [
        ("doc.comment", "a.md")
    ]
    assert watcher() == []


def test_plan_state_watcher_reports_status_change(tmp_path: Path) -> None:
    plan = tmp_path / "plans" / "p"
    (plan / "tasks").mkdir(parents=True)
    (plan / "plan.md").write_text("---\ntype: plan\nstatus: backlog\n---\n")
    watcher = plan_state_watcher(tmp_path)
    assert watcher() == []
    (plan / "plan.md").write_text("---\ntype: plan\nstatus: in_progress\n---\n")
    [(kind, subject, data)] = watcher()
    assert (kind, subject) == ("plan.state", "p")
    assert data["states"]["status"] == "in_progress"


def test_run_watchers_publishes() -> None:
    buf = EventBuffer(gen="g")
    assert run_watchers(buf, [lambda: [("doc.comment", "x", {"a": 1})]]) == 1
    assert buf.since("g:0")[0][0]["subject"] == "x"


def test_answer_and_decision_rows_emit_doc_decision(tmp_path: Path) -> None:
    doc = tmp_path / "a.md"
    doc.write_text("# A\n")
    watcher = doc_comment_watcher(tmp_path)
    assert watcher() == []
    append_comment(doc, "go", "", "x", extra={"kind": "answer", "item": "go"})
    append_comment(doc, "go", "", "y", extra={"kind": "decision", "item": "go"})
    append_comment(doc, "top", "", "z")
    kinds = [kind for kind, _, _ in watcher()]
    assert kinds == ["doc.decision", "doc.decision", "doc.comment"]
