"""Routing and actions for `varde learn docs serve|watch|comments|reply`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from varde_learn.docs import cli
from varde_learn.docs.pages import cli as pages_cli
from varde_learn.docs.pages.comments import append_comment, append_reply


@pytest.fixture
def doc(tmp_path: Path) -> Path:
    path = tmp_path / "plan.md"
    path.write_text("# Goal\n\nText.\n")
    return path


def test_help_text_for_each_command_and_doc_lists_all():
    for name in ("serve", "watch", "comments", "reply"):
        assert cli.help_text(f"doc {name}").strip()
        assert f"Usage: varde learn docs {name}" in cli.help_text(f"doc {name}")
        assert f"  {name} " in cli.help_text("doc")


def test_comments_text_and_json(doc, capsys):
    first = append_comment(doc, "goal", "Text", "fix this")
    append_comment(doc, "goal/1", "q", "other")
    append_reply(doc, first["id"], "done")
    assert cli.run(["comments", str(doc)]) == 0
    out = capsys.readouterr().out
    assert first["id"] in out and "reply agent: done" in out
    assert cli.run(["comments", str(doc), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]["comments"]
    assert [c["text"] for c in data] == ["fix this", "other"]


def test_reply_appends_and_rejects_unknown_id(doc, capsys):
    comment = append_comment(doc, "goal", "Text", "fix")
    assert cli.run(["reply", str(doc), comment["id"], "--note", "done"]) == 0
    assert "replied" in capsys.readouterr().out
    assert cli.run(["comments", str(doc), "--json"]) == 0
    reply = json.loads(capsys.readouterr().out)["data"]["comments"][0]["replies"]
    assert reply[0]["text"] == "done"
    assert cli.run(["reply", str(doc), "cnope", "--note", "x", "--json"]) == 2
    assert "unknown comment id" in capsys.readouterr().err


def test_open_listing_excludes_answered_comments(doc, capsys):
    answered = append_comment(doc, "goal", "Text", "fix")
    pending = append_comment(doc, "goal/1", "q", "other")
    assert cli.run(["reply", str(doc), answered["id"], "--note", "done"]) == 0
    capsys.readouterr()
    assert cli.run(["comments", str(doc), "--open", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]["comments"]
    assert [c["id"] for c in data] == [pending["id"]]


def test_reply_and_missing_args_are_usage_errors(doc, capsys):
    assert cli.run(["reply", str(doc), "c1"]) == 2
    assert "--note <NOTE>" in capsys.readouterr().err
    assert cli.run(["serve"]) == 2
    assert "<DOC>" in capsys.readouterr().err
    assert cli.run(["serve", str(doc), "--port", "x"]) == 2
    assert "--port" in capsys.readouterr().err
    assert cli.run(["watch", str(doc), "extra"]) == 2
    assert "unexpected argument 'extra'" in capsys.readouterr().err


def test_missing_doc_is_input_error(tmp_path, capsys):
    assert cli.run(["comments", str(tmp_path / "no.md"), "--json"]) == 2
    assert "doc_pages_input" in capsys.readouterr().err


def test_watch_bad_interval_and_stream(doc, capsys):
    assert cli.run(["watch", str(doc), "--interval", "0s"]) == 2
    assert "bad interval" in capsys.readouterr().err

    def lines(path, interval, backlog):
        assert (interval, backlog) == ("5s", True)
        yield "comment c1 goal hi"
        raise KeyboardInterrupt

    assert pages_cli.watch_doc(doc, "5s", True, lines) == 0
    assert capsys.readouterr().out == "comment c1 goal hi\n"


def test_serve_passes_port_and_prints_url(doc, monkeypatch, capsys):
    seen = {}

    def fake_serve(path, port, on_ready, host="127.0.0.1", allow_edit=False):
        seen["args"] = (path, port)
        on_ready("http://127.0.0.1:1234/")

    monkeypatch.setattr(pages_cli.serve_module, "serve", fake_serve)
    assert cli.run(["serve", str(doc), "--port", "1234"]) == 0
    assert seen["args"] == (doc, 1234)
    assert capsys.readouterr().out == "http://127.0.0.1:1234/\n"
