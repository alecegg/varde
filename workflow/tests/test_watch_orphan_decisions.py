from __future__ import annotations

import json
import time


def test_orphan_decisions_require_recent_approval_and_live_plan(tmp_path):
    from varde_workflow.orphan_decisions import orphan_decisions

    live = tmp_path / "live" / "plan.md"
    terminal = tmp_path / "done" / "plan.md"
    recent = tmp_path / "live" / "notes" / "recent.json"
    old = tmp_path / "live" / "notes" / "old.json"
    not_approval = tmp_path / "live" / "notes" / "report.json"
    relative_reference = "live/notes/recent.json"
    now = time.time()
    files = [
        (live.parent, recent, True, now - 60),
        (live.parent, old, True, now - 3 * 24 * 60 * 60),
        (live.parent, not_approval, False, now - 60),
        (terminal.parent, terminal.parent / "notes" / "approval.json", True, now - 60),
    ]

    found = orphan_decisions(
        [(live, "active"), (terminal, "terminal")],
        files,
        [relative_reference],
        now,
    )

    assert found == [recent]


def test_orphan_decisions_match_normalized_absolute_message_paths(tmp_path):
    from varde_workflow.orphan_decisions import orphan_decisions

    plan = tmp_path / "plan" / "plan.md"
    decision = plan.parent / "notes" / "decision.json"
    now = time.time()
    assert (
        orphan_decisions(
            [(plan, "active")],
            [(plan.parent, decision, True, now - 1)],
            [str(decision.parent / ".." / "notes" / "decision.json")],
            now,
        )
        == []
    )


def test_watch_treats_all_decision_types_as_referenced_orphans(tmp_path):
    from varde_workflow.commands.watch import _is_decision_file
    from varde_workflow.orphan_decisions import orphan_decisions

    plan = tmp_path / "plan" / "plan.md"
    now = time.time()
    types = ("design", "choice", "decision", "approval", "design_decision", "question")
    files = []
    paths = []
    for decision_type in types:
        path = plan.parent / "notes" / f"decision-{decision_type}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"type": decision_type}), encoding="utf-8")
        assert _is_decision_file(path)
        paths.append(path)
        files.append((plan.parent, path, _is_decision_file(path), now - 1))

    assert orphan_decisions([(plan, "active")], files, map(str, paths[:-1]), now) == [
        paths[-1]
    ]
    assert orphan_decisions([(plan, "active")], files, map(str, paths), now) == []


def test_watch_emits_each_orphan_decision_once(tmp_path, monkeypatch, capsys):
    from argparse import Namespace

    from varde_workflow.commands import watch

    working = tmp_path / "working"
    plan = working / "plans" / "sample"
    (plan / "notes").mkdir(parents=True)
    (plan / "plan.md").write_text(
        "---\ntype: plan\nstatus: active\n---\n# Sample\n", encoding="utf-8"
    )
    decision = plan / "notes" / "decision.json"
    decision.write_text('{"type":"approval"}', encoding="utf-8")
    monkeypatch.setattr(watch, "scan", lambda *_args: [])
    args = Namespace(
        working=working,
        repo=tmp_path,
        interval=0,
        stale=1200,
        once=True,
        no_inbox=False,
        no_wake=True,
        notes=None,
        json=False,
    )

    assert watch.run_watch(args, clock=lambda: 0) == 0
    assert watch.run_watch(args, clock=lambda: 0) == 0
    assert capsys.readouterr().out == ""
    messages = [
        json.loads(line)
        for line in (working / ".cache/inbox/messages.jsonl").read_text().splitlines()
    ]
    assert len(messages) == 1
    assert messages[0]["kind"] == "needs-user"
    assert messages[0]["notes"] == str(decision)


def test_watch_rate_limits_orphan_scan(tmp_path, monkeypatch):
    from argparse import Namespace

    from varde_workflow.commands import watch

    scans = []
    monkeypatch.setattr(watch, "scan", lambda *_args: [])

    def count_scan(_working, _facts=None):
        scans.append(1)
        return []

    monkeypatch.setattr(watch, "_orphan_decisions", count_scan)
    args = Namespace(
        working=tmp_path / "working",
        repo=tmp_path,
        interval=0,
        stale=1200,
        once=False,
        no_inbox=False,
        no_wake=True,
        notes=None,
        json=False,
    )
    monotonic_values = iter([0, 30, 60, 119])

    assert (
        watch.run_watch(
            args,
            frame_limit=4,
            clock=lambda: 0,
            monotonic=lambda: next(monotonic_values),
        )
        == 0
    )
    assert len(scans) == 2
