import json

from varde_runner.comments import append_event, fold_comments, read_comments
from varde_workflow.plan_comments import read_comments as workflow_read_comments


def test_fold_comments_applies_addressed_events_and_ignores_bad_lines():
    rows = [
        {
            "id": "c1",
            "ts": "now",
            "target": "plan",
            "text": "Fix it",
            "state": "open",
            "kind": "stored",
            "actor": "bot:manager",
        },
        {"id": "c1", "ts": "later", "event": "addressed", "note": "Done"},
    ]
    assert fold_comments(rows) == [
        {
            "id": "c1",
            "ts": "now",
            "target": "plan",
            "text": "Fix it",
            "state": "addressed",
            "kind": "stored",
            "actor": "bot:manager",
            "resolution_note": "Done",
        }
    ]
    assert (
        len(read_comments_from_text("\n".join(map(json.dumps, rows)) + "\nnot-json\n"))
        == 1
    )


def test_append_and_read_jsonl(tmp_path):
    path = tmp_path / "comments.jsonl"
    append_event(
        path,
        {
            "id": "c1",
            "ts": "now",
            "target": "plan",
            "text": "Fix",
            "state": "open",
            "kind": "stored",
        },
    )
    append_event(path, {"id": "c1", "event": "addressed", "note": "Done"})
    assert read_comments(path)[0]["state"] == "addressed"


def test_runner_and_workflow_comment_folding_agree(tmp_path):
    path = tmp_path / "comments.jsonl"
    rows = [
        {"id": "c1", "ts": "now", "text": "Fix", "state": "open"},
        {"id": "c2", "ts": "now", "text": "New", "state": "resolved"},
        {"id": "c1", "state": "resolved"},
        {"id": "c1", "state": "open"},
    ]
    path.write_text("\n".join(map(json.dumps, rows)) + "\n", encoding="utf-8")

    assert read_comments(path) == workflow_read_comments(path)
    assert fold_comments(rows) == workflow_read_comments(path)


def read_comments_from_text(text):
    from varde_runner.comments import parse_comments

    return parse_comments(text)
