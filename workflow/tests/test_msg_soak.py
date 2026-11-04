from __future__ import annotations

import json
import subprocess
from argparse import Namespace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from varde_workflow import binding, cli
from varde_workflow.commands import msg_soak
from varde_workflow.commands.msg_soak import (
    _active_orchestrators,
    _ordered_relay_events,
    gather,
    run,
)
from varde_workflow.msg_status import build_report, filter_retired
from varde_workflow.relay_state import record as record_relay
from varde_workflow.soak import evaluate

NOW = datetime(2026, 10, 23, 12, tzinfo=UTC)


def _git(repository: Path, *args: str) -> str:
    result = subprocess.run(  # noqa: S603 - The fixture uses fixed git arguments.
        ["git", "-C", str(repository), *args],  # noqa: S607 - Git is required by this fixture.
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _plan(working: Path, name: str, branch: str, approved_at: str) -> None:
    directory = working / "plans" / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "plan.md").write_text(
        f"---\nmerge_approved_at: {approved_at}\nbranch: {branch}\nstatus: done\n---\n",
        encoding="utf-8",
    )


def _message(message_id: str, to: str, kind: str = "info") -> dict[str, str]:
    return {
        "id": message_id,
        "ts": "2026-10-23T10:00:00Z",
        "from": "main",
        "to": to,
        "kind": kind,
        "text": message_id,
    }


def test_gather_fixture_covers_status_requests_aliases_merges_and_history(  # noqa: PLR0915
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    working = tmp_path / "working"
    repository = tmp_path / "repo"
    inbox = working / ".cache" / "inbox"
    inbox.mkdir(parents=True)
    repository.mkdir()
    _git(repository, "init", "-b", "main")
    _git(repository, "config", "user.email", "test@example.invalid")
    _git(repository, "config", "user.name", "Test")
    (repository / "base").write_text("base")
    _git(repository, "add", "base")
    _git(repository, "commit", "-m", "base")
    _git(repository, "branch", "worktree/merged")
    _git(repository, "branch", "worktree/unmerged")
    _git(repository, "checkout", "worktree/unmerged")
    (repository / "extra").write_text("extra")
    _git(repository, "add", "extra")
    _git(repository, "commit", "-m", "unmerged")
    _git(repository, "checkout", "main")

    _plan(working, "merged", "worktree/merged", "2026-10-23T11:00:00Z")
    _plan(working, "deleted", "worktree/deleted", "2026-10-23T11:00:00Z")
    _plan(working, "unmerged", "worktree/unmerged", "2026-10-23T10:00:00Z")
    (inbox / "slots").mkdir()
    (inbox / "slots" / "orchestrator-1.json").write_text(
        json.dumps({"slot": "orchestrator-1", "aliases": ["plan-alias"]})
    )
    rows = [
        _message("to-alias", "plan-alias"),
        _message("seen-request", "main", "blocked"),
        _message("open-request", "main", "needs-user"),
    ]
    messages_path = inbox / "messages.jsonl"
    serialized = [json.dumps(row) + "\n" for row in rows]
    messages_path.write_text("".join(serialized))
    prefix_size = sum(len(row.encode()) for row in serialized[:2])
    (inbox / "index").mkdir()
    (inbox / "index" / "main.json").write_text(json.dumps({"watermark": prefix_size}))
    deliveries = [
        {
            "message_id": "to-alias",
            "reader": "plan-alias",
            "event": "delivered",
            "at": "2026-10-23T10:00:30Z",
        },
        {
            "message_id": "to-alias",
            "reader": "plan-alias",
            "event": "acked",
            "at": "2026-10-23T10:01:00Z",
        },
    ]
    delivery_path = inbox / "deliveries.jsonl"
    delivery_path.write_text("".join(json.dumps(row) + "\n" for row in deliveries))
    metrics = working / "metrics" / "mail-soak"
    metrics.mkdir(parents=True)
    (metrics / "2026-10-22.json").write_text('{"all_ok":true}')
    (metrics / "2026-10-23.json").write_text('{"all_ok":false}')
    (metrics / "2026-10-24.json").write_text('{"all_ok":true}')
    (metrics / "2026-10-21.json").write_text("{bad json")

    retired_report = {
        "addresses": [{"address": "retired-slot", "unread": 0}],
        "unbound_pending": ["retired-slot"],
        "events": [{"address": "retired-slot"}],
        "overdue": [],
        "runner_relay_down_with_urgent_mail": False,
        "mailmen": [],
        "stopped_reading": [],
        "bad": True,
        "exit_code": 1,
    }
    monkeypatch.setattr(msg_soak, "load_report", lambda _working, _now: retired_report)
    monkeypatch.setattr(
        msg_soak, "load_retired", lambda _working: {"retired-slot": "old"}
    )
    # Opening the address store creates its lock file lazily; include that setup
    # effect before checking that gather itself leaves the records unchanged.
    msg_soak._resolve_readers([{"to": "warmup"}], [], working)
    msg_soak.status_messages(inbox)
    before = {
        path.relative_to(working): path.read_bytes()
        for path in working.rglob("*")
        if path.is_file()
    }

    data = gather(working, NOW, repository)

    assert data["status"] == {"exit_code": 0}
    assert [item["to"] for item in data["messages"]] == [
        "orchestrator-1",
        "main",
        "main",
    ]
    assert [item["reader"] for item in data["deliveries"]] == [
        "orchestrator-1",
        "orchestrator-1",
    ]
    assert [item["id"] for item in data["open_requests"]] == ["open-request"]
    approved = {item["plan"]: item for item in data["approved_merges"]}
    assert approved["merged"]["merged"] is True
    assert approved["deleted"]["merged"] is True
    assert approved["unmerged"]["merged"] is False
    deleted_report = evaluate(
        {**data, "approved_merges": [approved["deleted"]], "open_requests": []},
        3,
        NOW,
        {},
    )
    unmerged_report = evaluate(
        {**data, "approved_merges": [approved["unmerged"]], "open_requests": []},
        3,
        NOW,
        {},
    )
    assert (
        next(
            item for item in deleted_report["criteria"] if item["id"] == "merge-guard"
        )["ok"]
        is True
    )
    assert (
        next(
            item for item in unmerged_report["criteria"] if item["id"] == "merge-guard"
        )["ok"]
        is False
    )
    assert data["prior_days"] == [{"date": "2026-10-22", "all_ok": True}]
    assert data["active_orchestrators_today"] == 1
    assert before == {
        path.relative_to(working): path.read_bytes()
        for path in working.rglob("*")
        if path.is_file()
    }


def test_gather_report_contract_reaches_mail_soak_card_formatter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    working = tmp_path / "working"
    repository = tmp_path / "repo"
    (working / ".cache" / "inbox").mkdir(parents=True)
    repository.mkdir()
    message = _message("contract", "orchestrator-1")
    monkeypatch.setattr(msg_soak, "status_messages", lambda _inbox: [message])
    monkeypatch.setattr(
        msg_soak,
        "_resolve_readers",
        lambda messages, deliveries, _working: (messages, deliveries),
    )
    monkeypatch.setattr(msg_soak, "load_relay", lambda _working: {})
    monkeypatch.setattr(
        msg_soak, "load_report", lambda _working, _now: {"exit_code": 0}
    )
    monkeypatch.setattr(msg_soak, "_approved_merges", lambda _working, _repo: [])
    monkeypatch.setattr(msg_soak, "load_nudges", lambda _working: [])
    monkeypatch.setattr(
        msg_soak,
        "_prior_days",
        lambda _working, _today: [
            {"date": "2026-10-21", "all_ok": True},
            {"date": "2026-10-22", "all_ok": True},
        ],
    )
    monkeypatch.setattr(msg_soak, "filter_retired", lambda status, _retired: status)

    data = gather(working, NOW, repository)
    report = evaluate(data, 7, NOW, {})
    report_json = json.dumps(report)
    parsed = json.loads(report_json)

    assert set(parsed) == {
        "date",
        "window_days",
        "undeliverable",
        "criteria",
        "active_orchestrators",
        "all_ok",
        "days_ok_streak",
        "wakes",
        "missed",
        "distinct_recipients",
        "max_delivered_latency_s",
    }
    script = """
      import { createInterface } from 'node:readline';
      import {
        criterionPresentation, streakPresentation,
      } from './runner/ui/src/lib/mailSoak.ts';
      let input = '';
      for await (const line of createInterface({ input: process.stdin })) input += line;
      const report = JSON.parse(input);
      process.stdout.write(JSON.stringify({
        streak: streakPresentation(report),
        criteria: report.criteria.map(criterionPresentation),
      }));
    """
    formatted = subprocess.run(  # noqa: S603 - The subprocess runs a fixed local test script.
        [  # noqa: S607 - Node is required to exercise the runner UI formatter.
            "node",
            "--experimental-strip-types",
            "--input-type=module",
            "-e",
            script,
        ],
        input=json.dumps(parsed),
        check=True,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    card = json.loads(formatted.stdout)
    assert card["streak"] == "Soak passed · 3 of 3 passing days"
    assert [item["label"] for item in card["criteria"]] == [
        "Typical delivery time (95th percentile)",
        "Acknowledgement time (95th percentile)",
        "Main nudges",
        "Message replays",
        "Message status",
        "Send without mailman",
        "Merge guard",
    ]


def test_gather_extracts_send_liveness_and_live_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    working = tmp_path / "working"
    repository = tmp_path / "repo"
    (working / ".cache" / "inbox").mkdir(parents=True)
    repository.mkdir()
    store = binding.BindingStore(working)
    marker = store.issue("orchestrator-1", now=NOW)
    assert store.redeem(marker, "session", "codex", "/repo", now=NOW)
    record_relay(working, "send-liveness", now=NOW, alive=False)
    monkeypatch.setattr(msg_soak, "load_report", lambda *_args: {"exit_code": 0})
    monkeypatch.setattr(msg_soak, "filter_retired", lambda status, _retired: status)
    monkeypatch.setattr(msg_soak, "_approved_merges", lambda *_args: [])
    monkeypatch.setattr(msg_soak, "load_nudges", lambda *_args: [])
    monkeypatch.setattr(msg_soak, "_prior_days", lambda *_args: [])

    data = gather(working, NOW, repository)

    assert data["live_addresses"] == {"orchestrator-1"}
    assert data["relay_events"] == [
        {"event": "send-liveness", "at": "2026-10-23T12:00:00Z", "alive": False}
    ]


def test_active_orchestrators_counts_distinct_utc_day_activity_and_live_bindings() -> (
    None
):
    messages = [
        {"from": "orchestrator-1", "to": "main", "ts": "2026-10-23T00:01:00Z"},
        {"from": "main", "to": "orchestrator-1", "ts": "2026-10-23T01:00:00Z"},
        {"from": "main", "to": "orchestrator-2", "ts": "2026-10-22T23:59:00Z"},
    ]
    deliveries = [
        {"reader": "orchestrator-2", "event": "acked", "at": "2026-10-23T02:00:00Z"}
    ]
    active = _active_orchestrators(
        messages, deliveries, {"orchestrator-3", "main"}, NOW
    )

    assert active == 3


def test_run_exit_codes_and_output_modes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    data = {
        "messages": [],
        "deliveries": [],
        "relay_events": [],
        "live_addresses": {"orchestrator-1"},
        "nudges": [],
        "status": {"exit_code": 0},
        "approved_merges": [],
        "open_requests": [],
        "active_orchestrators_today": 1,
        "prior_days": [],
    }
    monkeypatch.setattr(msg_soak, "gather", lambda *_args, **_kwargs: data)
    args = Namespace(window_days=3, write=False, json=True)

    assert run(args, tmp_path, now=NOW, repository=tmp_path) == 0
    assert json.loads(capsys.readouterr().out)["all_ok"] is True
    args.json = False
    assert run(args, tmp_path, now=NOW, repository=tmp_path) == 0
    assert "Mail soak 2026-10-23: PASS" in capsys.readouterr().out

    monkeypatch.setattr(
        msg_soak,
        "gather",
        lambda *_args, **_kwargs: {
            **data,
            "messages": [_message("status-error", "orchestrator-1")],
            "status": {"exit_code": 1},
        },
    )
    args.json = True
    assert run(args, tmp_path, now=NOW, repository=tmp_path) == 1
    capsys.readouterr()
    monkeypatch.setattr(
        msg_soak,
        "gather",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("broken")),
    )
    assert run(args, tmp_path, now=NOW, repository=tmp_path) == 70


def test_write_twice_replaces_single_daily_file(tmp_path: Path) -> None:
    args = Namespace(window_days=3, write=True, json=True)

    assert run(args, tmp_path, now=NOW, repository=tmp_path) == 1
    first = next((tmp_path / "metrics" / "mail-soak").glob("*.json")).read_bytes()
    assert run(args, tmp_path, now=NOW, repository=tmp_path) == 1

    reports = list((tmp_path / "metrics" / "mail-soak").glob("*.json"))
    assert len(reports) == 1
    assert list((tmp_path / "metrics" / "mail-soak").glob("*.tmp")) == []
    assert reports[0].read_bytes() == first
    assert json.loads(reports[0].read_text(encoding="utf-8"))["date"] == reports[0].stem


def test_status_clean_accepts_retired_dead_address_with_unread_mail() -> None:
    report = build_report([_message("old-unread", "dead-address")], [], [], [], NOW)
    status = filter_retired(report, {"dead-address": "2026-10-23T11:00:00Z"})
    result = evaluate(
        {
            "messages": [],
            "deliveries": [],
            "relay_events": [],
            "live_addresses": {"orchestrator-1"},
            "nudges": [],
            "status": status,
            "approved_merges": [],
            "open_requests": [],
            "active_orchestrators_today": 1,
            "prior_days": [],
        },
        3,
        NOW,
        {},
    )

    criterion = next(
        item for item in result["criteria"] if item["id"] == "status-clean"
    )
    assert status["addresses"] == []
    assert criterion["ok"] is True


def test_unresolved_working_directory_blocks_soak_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        binding,
        "resolve_working_dir_with_source",
        lambda _cwd: (tmp_path, False),
    )

    assert cli.run(["msg", "soak", "--write"]) == 2
    assert not (tmp_path / "metrics" / "mail-soak").exists()


def test_cli_soak_route_uses_resolved_working_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        binding,
        "resolve_working_dir_with_source",
        lambda _cwd: (tmp_path, True),
    )
    monkeypatch.setattr(msg_soak, "run", lambda _args, _working: 19)

    assert cli.run(["msg", "soak", "--json"]) == 19


def test_cli_soak_accepts_repeatable_threshold_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = {}
    monkeypatch.setattr(
        binding,
        "resolve_working_dir_with_source",
        lambda _cwd: (tmp_path, True),
    )

    def capture(args, _working):
        seen["thresholds"] = args.threshold
        return 0

    monkeypatch.setattr(msg_soak, "run", capture)

    assert (
        cli.run(
            [
                "msg",
                "soak",
                "--threshold",
                "delivered-latency=60",
                "--threshold",
                "minimum_messages=20",
                "--json",
            ]
        )
        == 0
    )
    assert seen["thresholds"] == [("delivered-latency", 60), ("minimum_messages", 20)]


def test_cli_soak_rejects_unknown_or_negative_thresholds() -> None:
    assert cli.run(["msg", "soak", "--threshold", "unknown=1"]) == 2
    assert cli.run(["msg", "soak", "--threshold", "main-nudges=-1"]) == 2


def test_run_applies_thresholds_and_reports_gate_metrics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    data = {
        "messages": [
            _message("wake", "orchestrator-1"),
            _message("late", "orchestrator-1"),
        ],
        "deliveries": [
            {
                "message_id": "wake",
                "reader": "orchestrator-1",
                "event": "delivered",
                "at": "2026-10-23T10:00:30Z",
            }
        ],
        "relay_events": [],
        "live_addresses": {"orchestrator-1"},
        "nudges": [],
        "status": {"exit_code": 0},
        "approved_merges": [],
        "open_requests": [],
        "active_orchestrators_today": 1,
        "prior_days": [],
    }
    monkeypatch.setattr(msg_soak, "gather", lambda *_args, **_kwargs: data)
    args = Namespace(
        window_days=1,
        write=False,
        json=True,
        threshold=[("delivered-latency", 60), ("minimum_messages", 20)],
    )

    assert run(args, tmp_path, now=NOW, repository=tmp_path) == 0
    report = json.loads(capsys.readouterr().out)

    assert report["wakes"] == 1
    assert report["missed"] == 1
    assert report["distinct_recipients"] == 1
    assert report["max_delivered_latency_s"] == 30.0
    delivered = next(
        row for row in report["criteria"] if row["id"] == "delivered-latency"
    )
    assert delivered["threshold"] == 60
    assert report["all_ok"] is True


def test_relay_events_are_chronological_and_ties_keep_list_order() -> None:
    deliveries = [
        {"event": "acked", "at": "2026-10-23T12:00:00Z"},
        {"event": "delivered", "at": "2026-10-23T12:00:00Z"},
    ]
    sleeps = [{"event": "slept", "at": "2026-10-23T11:59:59Z"}]

    ordered = _ordered_relay_events(deliveries, sleeps)

    assert [item["event"] for item in ordered] == ["slept", "acked", "delivered"]
