from __future__ import annotations

from argparse import Namespace


def test_decision_notes_predicates(tmp_path):
    from varde_workflow.commands.msg import needs_decision_notes, valid_decision_notes

    assert needs_decision_notes("merge-ready", "main")
    assert needs_decision_notes("needs-user", "main")
    assert not needs_decision_notes("info", "main")
    assert not needs_decision_notes("merge-ready", "worker")

    text_notes = tmp_path / "decision.md"
    text_notes.write_text("decision context", encoding="utf-8")
    assert valid_decision_notes(text_notes)
    assert not valid_decision_notes(tmp_path / "missing.md")

    approval = tmp_path / "approval.json"
    approval.write_text('{"type":"approval"}', encoding="utf-8")
    invalid = tmp_path / "report.json"
    invalid.write_text("[]", encoding="utf-8")
    malformed = tmp_path / "broken.json"
    malformed.write_text("not json", encoding="utf-8")
    assert valid_decision_notes(approval)
    assert not valid_decision_notes(invalid)
    assert not valid_decision_notes(malformed)


def test_decision_send_requires_existing_notes(tmp_path, capsys):
    from varde_workflow.commands.msg import run

    args = Namespace(
        message_command="send",
        from_address="builder",
        to="main",
        kind="merge-ready",
        text="ready",
        notes=None,
        reply_to=None,
    )

    assert run(args, tmp_path) == 1
    assert "require --notes" in capsys.readouterr().err


def test_decision_send_accepts_existing_notes(tmp_path, capsys):
    from varde_workflow.commands.msg import run

    notes = tmp_path / "decision.json"
    notes.write_text('{"type":"approval"}', encoding="utf-8")
    args = Namespace(
        message_command="send",
        from_address="builder",
        to="main",
        kind="needs-user",
        text="approve",
        notes=str(notes),
        reply_to=None,
    )

    assert run(args, tmp_path) == 0
    assert "require --notes" not in capsys.readouterr().err
