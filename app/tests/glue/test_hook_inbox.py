from __future__ import annotations

import contextlib
import io
import json
import statistics
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from varde.glue.hook import dispatch
from varde.glue.inbox_hook import _owner_reader
from varde_workflow.binding import BindingStore
from varde_workflow.commands.msg import append_message
from varde_workflow.inbox import delivery_events, unread


def _now():
    return datetime.now(UTC)


def _environment(monkeypatch, working: Path) -> None:
    monkeypatch.chdir(working)
    monkeypatch.setenv("PWD", str(working))
    config = working / "config"
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))
    monkeypatch.setenv("HOME", str(working / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(working / "xdg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(working / "data"))
    monkeypatch.delenv("VARDE_ADDRESS", raising=False)
    monkeypatch.setenv("VARDE_RUNNER_ENABLED", "1")


def _submit(harness: str, session_id: str, prompt: str = "") -> str:
    # Capture the real hook stdout shape while exercising dispatch.
    output = io.StringIO()
    payload = json.dumps({"session_id": session_id, "prompt": prompt}).encode()
    with contextlib.redirect_stdout(output):
        assert dispatch({"event": "user-prompt-submit", "input": payload}, harness) == 0
    return output.getvalue()


def test_unbound_session_reads_nothing_and_leaves_main_unread(tmp_path, monkeypatch):
    _environment(monkeypatch, tmp_path)
    append_message("sender", "main", "info", "held", working=tmp_path)

    assert _submit("claude", "unbound") == ""
    assert [item.text for item in unread(tmp_path, "main")] == ["held"]
    assert delivery_events(tmp_path) == []


def test_prompt_hook_latency_stays_within_data_messages_bound(tmp_path, monkeypatch):
    from varde.glue.inbox_hook import prompt_inbox
    from varde_data.config import load_data_config
    from varde_data.open import open_data
    from varde_data.records.addresses import ReaderContext
    from varde_data.records.messages import NewMessage

    _environment(monkeypatch, tmp_path)
    now = datetime(2026, 10, 22, 12, tzinfo=UTC)
    data = open_data(tmp_path, load_data_config())
    data.messages.append(NewMessage("sender", "worker", "info", "hook delivery"))
    marker = data.addresses.issue("worker", now=now)
    assert data.addresses.redeem(
        marker,
        "session",
        "claude",
        ReaderContext(cwd=str(tmp_path)),
        now=now,
    )

    payload = json.dumps({"session_id": "session", "prompt": ""}).encode()
    samples = []
    for _ in range(30):
        started = time.perf_counter()
        prompt_inbox("claude", payload, banner_enabled=False)
        samples.append((time.perf_counter() - started) * 1000)

    assert statistics.median(samples) <= 106.32


def test_marker_binds_and_delivers_first_mail_resume_and_fork(tmp_path, monkeypatch):
    _environment(monkeypatch, tmp_path)
    store = BindingStore(tmp_path)
    marker = store.issue("worker", now=_now())
    append_message("sender", "worker", "info", "first", working=tmp_path)

    result = _submit("claude", "same-session", f"instructions\n{marker}")
    assert "sender info: first" in result
    assert store.list_bindings()[0]["cwd"] == str(tmp_path)
    assert store.resolve_reader("claude", "same-session", "", {}, _now()) == "worker"
    assert _submit("claude", "same-session") == ""
    assert _submit("claude", "forked-session") == ""
    records = delivery_events(tmp_path)
    assert [(item["event"], item["reader"], item["session"]) for item in records] == [
        ("delivered", "worker", "same-session"),
        ("acked", "worker", "same-session"),
    ]


def test_marker_redeem_keeps_legacy_identity_and_metadata_split(tmp_path, monkeypatch):
    _environment(monkeypatch, tmp_path)
    monkeypatch.setenv("PASEO_AGENT_ID", "paseo-fixed")
    monkeypatch.setenv("VARDE_AGENT_ID", "agent-fixed")
    monkeypatch.setenv("VARDE_HARNESS", "codex")
    monkeypatch.setenv("VARDE_RUNNER_ENDPOINT", "endpoint-fixed")
    monkeypatch.setenv("VARDE_ADDRESS", "main")
    store = BindingStore(tmp_path)
    marker = store.issue("worker", now=_now())

    assert "inbox:" not in _submit("claude", "marker-session", marker)
    binding = store.list_bindings()[0]

    assert binding["harness"] == "claude"
    assert binding["cwd"] == str(tmp_path)
    assert binding["wake_context"] == {
        "harness": "codex",
        "session_id": "marker-session",
        "cwd": str(tmp_path),
        "paseo_id": "paseo-fixed",
        "agent_id": "agent-fixed",
        "runner_endpoint": "endpoint-fixed",
    }


def test_agent_id_guard_and_var_de_address_live_binding_guard(tmp_path, monkeypatch):
    _environment(monkeypatch, tmp_path)
    store = BindingStore(tmp_path)
    main_marker = store.issue("main", supersede=True, now=_now())
    assert store.redeem(main_marker, "main", "claude", str(tmp_path), now=_now())
    append_message("sender", "main", "info", "private", working=tmp_path)

    subagent = json.dumps({"session_id": "main", "agent_id": "child"}).encode()
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        dispatch({"event": "user-prompt-submit", "input": subagent}, "claude")
    assert output.getvalue() == ""

    monkeypatch.setenv("VARDE_ADDRESS", "main")
    assert _submit("claude", "child") == ""
    assert [item.text for item in unread(tmp_path, "main")] == ["private"]
    assert delivery_events(tmp_path) == []


def test_owner_route_precedes_var_de_address_fallback(tmp_path, monkeypatch):
    _environment(monkeypatch, tmp_path)
    plan = tmp_path / "plans" / "owned-plan" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("---\ntype: plan\nowner: pi:owner-session\n---\n", encoding="utf-8")
    append_message("sender", "owned-plan", "info", "owner mail", working=tmp_path)
    monkeypatch.setenv("VARDE_ADDRESS", "main")

    output = _submit("pi", "owner-session")
    assert "sender info: owner mail" in output
    assert (
        BindingStore(tmp_path).resolve_reader("pi", "owner-session", "", {}, _now())
        is None
    )
    assert [
        (event["reader"], event["event"]) for event in delivery_events(tmp_path)
    ] == [("owned-plan", "delivered"), ("owned-plan", "acked")]


def test_var_de_address_fallback_runs_after_unbound_owner_lookup(tmp_path, monkeypatch):
    _environment(monkeypatch, tmp_path)
    monkeypatch.setenv("VARDE_ADDRESS", "worker")
    append_message("sender", "worker", "info", "fallback mail", working=tmp_path)

    output = _submit("pi", "unbound-session")

    assert "sender info: fallback mail" in output
    assert [
        (event["reader"], event["event"]) for event in delivery_events(tmp_path)
    ] == [("worker", "delivered"), ("worker", "acked")]


def test_owner_reader_selects_matching_plan_and_uses_id(tmp_path):
    plans = tmp_path / "plans"
    plans.mkdir()
    (plans / "other").mkdir()
    (plans / "other" / "plan.md").write_text(
        "---\ntype: plan\nowner: pi:someone-else\nid: other-id\n---\n"
    )
    (plans / "owned").mkdir()
    (plans / "owned" / "plan.md").write_text(
        "---\ntype: plan\nowner: pi:session\nid: explicit-id\n---\n"
    )

    assert _owner_reader(tmp_path, "pi", "session") == "explicit-id"


def test_owner_reader_falls_back_to_plan_directory_name(tmp_path):
    plan = tmp_path / "plans" / "directory-id" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("---\ntype: plan\nowner: claude:session\n---\n")

    assert _owner_reader(tmp_path, "claude", "session") == "directory-id"


def test_owner_reader_ignores_non_plan_artifacts(tmp_path):
    task = tmp_path / "plans" / "task-artifact" / "task.md"
    task.parent.mkdir(parents=True)
    task.write_text("---\ntype: task\nowner: pi:session\n---\n")

    assert _owner_reader(tmp_path, "pi", "session") is None


def test_owner_reader_excludes_archived_plans(tmp_path):
    plan = tmp_path / "plans" / "archive" / "old" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("---\ntype: plan\nowner: pi:session\n---\n")

    assert _owner_reader(tmp_path, "pi", "session") is None


def test_owner_reader_chooses_active_plan_when_archive_has_same_owner(tmp_path):
    active = tmp_path / "plans" / "active" / "plan.md"
    archived = tmp_path / "plans" / "archive" / "old" / "plan.md"
    active.parent.mkdir(parents=True)
    archived.parent.mkdir(parents=True)
    active.write_text("---\ntype: plan\nowner: pi:session\n---\n", encoding="utf-8")
    archived.write_text("---\ntype: plan\nowner: pi:session\n---\n", encoding="utf-8")

    assert _owner_reader(tmp_path, "pi", "session") == "active"


def test_owner_reader_reads_only_plan_documents_once(tmp_path, monkeypatch):
    plan_count = 4
    for index in range(plan_count):
        plan = tmp_path / "plans" / f"plan-{index}" / "plan.md"
        plan.parent.mkdir(parents=True)
        plan.write_text(
            f"---\ntype: plan\nowner: {'pi:session' if index == 2 else 'other'}\n---\n"
        )
        task = plan.parent / "tasks" / "task.md"
        task.parent.mkdir()
        task.write_text("---\ntype: task\n---\n")

    read_bytes = Path.read_bytes
    reads = []

    def counted_read_bytes(path):
        reads.append(path)
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", counted_read_bytes)

    assert _owner_reader(tmp_path, "pi", "session") == "plan-2"
    plan_reads = [path for path in reads if path.name == "plan.md"]
    task_reads = [path for path in reads if "tasks" in path.parts]
    assert len(plan_reads) <= plan_count
    assert len(set(plan_reads)) == len(plan_reads)
    assert task_reads == []


def test_stop_hook_does_not_replay_mail_read_by_bound_slot(tmp_path, monkeypatch):
    _environment(monkeypatch, tmp_path)
    store = BindingStore(tmp_path)
    now = _now()
    marker = store.issue("orchestrator-1", now=now)
    assert store.redeem(marker, "bound-session", "claude", str(tmp_path), now=now)
    append_message("sender", "orchestrator-1", "info", "hello", working=tmp_path)
    monkeypatch.setenv("VARDE_ADDRESS", "main")
    from varde_workflow.inbox import claim_unread

    assert [
        item.text for item in claim_unread(tmp_path, "orchestrator-1", "cli", "cli")
    ] == ["hello"]

    outputs = []
    for _ in range(3):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            dispatch(
                {
                    "event": "stop",
                    "input": json.dumps({"session_id": "bound-session"}).encode(),
                },
                "claude",
            )
        outputs.append(output.getvalue())

    assert outputs == ["", "", ""]


def test_stop_hook_does_not_replay_mail_read_by_bound_alias(tmp_path, monkeypatch):
    _environment(monkeypatch, tmp_path)
    from varde_workflow.slots import add_alias

    add_alias(tmp_path, "orchestrator-1", "plan-a")
    store = BindingStore(tmp_path)
    now = _now()
    marker = store.issue("plan-a", now=now)
    assert store.redeem(marker, "bound-session", "claude", str(tmp_path), now=now)
    append_message("sender", "orchestrator-1", "info", "hello", working=tmp_path)
    monkeypatch.setenv("VARDE_ADDRESS", "main")
    from varde_workflow.inbox import claim_unread

    assert [
        item.text for item in claim_unread(tmp_path, "orchestrator-1", "cli", "cli")
    ] == ["hello"]

    outputs = []
    for _ in range(3):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            dispatch(
                {
                    "event": "stop",
                    "input": json.dumps({"session_id": "bound-session"}).encode(),
                },
                "claude",
            )
        outputs.append(output.getvalue())

    assert outputs == ["", "", ""]


def test_stop_hook_names_resolved_reader_and_delivers_once(tmp_path, monkeypatch):
    _environment(monkeypatch, tmp_path)
    store = BindingStore(tmp_path)
    now = _now()
    marker = store.issue("orchestrator-1", now=now)
    assert store.redeem(marker, "bound-session", "claude", str(tmp_path), now=now)
    append_message("sender", "orchestrator-1", "info", "hello", working=tmp_path)
    monkeypatch.setenv("VARDE_ADDRESS", "main")

    outputs = []
    for _ in range(3):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            dispatch(
                {
                    "event": "stop",
                    "input": json.dumps({"session_id": "bound-session"}).encode(),
                },
                "claude",
            )
        outputs.append(output.getvalue())

    assert "inbox for orchestrator-1: sender info: hello" in outputs[0]
    assert outputs[0].count('"decision":"block"') == 1
    assert outputs[1:] == ["", ""]


def test_unbound_regular_mail_triggers_status_banner(tmp_path, monkeypatch):
    _environment(monkeypatch, tmp_path)
    store = BindingStore(tmp_path)
    marker = store.issue("main", supersede=True, now=_now())
    assert store.redeem(marker, "main", "claude", str(tmp_path), now=_now())
    append_message("sender", "main", "info", "hello", working=tmp_path)
    append_message("sender", "orphan", "info", "held", working=tmp_path)

    output = _submit("claude", "main")
    assert "sender info: hello" in output
    assert "pending mail for unbound addresses" in output


def test_main_banner_reports_bad_mailman_and_escalates_without_mailman(
    tmp_path, monkeypatch
):
    from varde_workflow.commands.msg import append_message, read_all

    _environment(monkeypatch, tmp_path)
    now = datetime(2026, 10, 17, 12, tzinfo=UTC)
    store = BindingStore(tmp_path)
    marker = store.issue("main", supersede=True, now=now)
    assert store.redeem(marker, "main", "claude", str(tmp_path), now=now)
    append_message(
        "sender",
        "orphan",
        "blocked",
        "urgent",
        working=tmp_path,
        now=now - timedelta(minutes=11),
    )

    output = _submit("claude", "main")
    assert "mailman: none" in output
    assert any(
        message.from_ == "relay" and message.to == "main"
        for message in read_all(tmp_path)
    )


def test_old_id_less_messages_do_not_trigger_the_main_banner(tmp_path, monkeypatch):
    _environment(monkeypatch, tmp_path)
    store = BindingStore(tmp_path)
    marker = store.issue("main", supersede=True, now=_now())
    assert store.redeem(marker, "main", "claude", str(tmp_path), now=_now())
    legacy = {
        "ts": "2026-01-01T00:00:00Z",
        "from": "old",
        "to": "main",
        "kind": "needs-user",
        "text": "legacy mail",
    }
    inbox = tmp_path / ".cache" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    (inbox / "messages.jsonl").write_text(json.dumps(legacy) + "\n")

    output = _submit("claude", "main")

    assert "varde msg status" not in output


def test_corrupt_event_log_does_not_discard_claimed_mail(tmp_path, monkeypatch):
    _environment(monkeypatch, tmp_path)
    store = BindingStore(tmp_path)
    marker = store.issue("main", supersede=True, now=_now())
    assert store.redeem(marker, "main", "claude", str(tmp_path), now=_now())
    append_message("sender", "main", "info", "survives", working=tmp_path)
    events = tmp_path / ".cache" / "inbox" / "events.jsonl"
    events.write_text("{broken event\n")

    result = _submit("claude", "main")
    assert "sender info: survives" in result
    assert "varde msg status:" not in result


def test_banner_is_throttled_and_stop_never_prints_it(tmp_path, monkeypatch):
    _environment(monkeypatch, tmp_path)
    marker = BindingStore(tmp_path).issue("main", supersede=True, now=_now())
    assert BindingStore(tmp_path).redeem(
        marker, "main", "claude", str(tmp_path), now=_now()
    )
    append_message(
        "sender",
        "orphan",
        "blocked",
        "held",
        working=tmp_path,
        now=_now() - timedelta(minutes=11),
    )

    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        dispatch(
            {"event": "stop", "input": json.dumps({"session_id": "main"}).encode()},
            "claude",
        )
    assert output.getvalue() == ""
    first = _submit("claude", "main")
    second = _submit("claude", "main")
    assert "varde msg status:" in first
    assert "varde msg status:" not in second


def test_idle_main_can_be_taken_over_through_environment(tmp_path, monkeypatch):
    _environment(monkeypatch, tmp_path)
    store = BindingStore(tmp_path)
    idle = _now() - timedelta(minutes=31)
    marker = store.issue("main", supersede=True, now=idle)
    assert store.redeem(marker, "old-main", "claude", str(tmp_path), now=idle)
    append_message("sender", "main", "info", "takeover mail", working=tmp_path)
    monkeypatch.setenv("VARDE_ADDRESS", "main")

    assert "sender info: takeover mail" in _submit("claude", "child")
    events = (tmp_path / ".cache" / "inbox" / "events.jsonl").read_text()
    assert '"event":"supersede"' in events


def test_prompt_payload_at_200kb_keeps_marker_on_third_line(tmp_path, monkeypatch):
    _environment(monkeypatch, tmp_path)
    marker = BindingStore(tmp_path).issue("worker", now=_now())
    prompt = f"preamble one\npreamble two\n{marker}\n" + "x" * 200_000
    import contextlib
    import io
    import sys

    from varde.fastpath import run

    payload = json.dumps({"session_id": "large-prompt", "prompt": prompt}).encode()

    class Input:
        buffer = io.BytesIO(payload)

        @staticmethod
        def isatty():
            return False

    monkeypatch.setattr(sys, "stdin", Input())
    monkeypatch.setattr(
        "varde.fastpath.select.select", lambda *_: ([sys.stdin], [], [])
    )
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        assert run(["hook", "user-prompt-submit", "--harness", "pi"]) == 0
    assert (
        BindingStore(tmp_path).resolve_reader("pi", "large-prompt", "", {}, _now())
        == "worker"
    )
    assert output.getvalue() == ""


def test_bound_main_hook_handles_ten_thousand_messages_under_three_cpu_seconds(
    tmp_path, monkeypatch
):
    import time

    _environment(monkeypatch, tmp_path)
    store = BindingStore(tmp_path)
    marker = store.issue("main", supersede=True, now=_now())
    assert store.redeem(marker, "main", "claude", str(tmp_path), now=_now())
    inbox = tmp_path / ".cache" / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    stamp = _now().isoformat()
    (inbox / "messages.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "id": f"m-{index:08x}",
                    "ts": stamp,
                    "from": "sender",
                    "to": "main",
                    "kind": "info",
                    "text": "old",
                }
            )
            + "\n"
            for index in range(10_000)
        )
    )

    started = time.process_time()
    _submit("claude", "main")
    assert time.process_time() - started < 3


def test_prompt_hook_refreshes_existing_main_binding_paseo_id(tmp_path, monkeypatch):
    from varde_workflow.binding import session_key, wake_of

    _environment(monkeypatch, tmp_path)
    store = BindingStore(tmp_path)
    marker = store.issue("main", supersede=True, now=_now())
    assert store.redeem(marker, "main", "claude", str(tmp_path), now=_now())
    record = store.list_bindings()[0]
    record.pop("wake_context")
    path = store.bindings / f"{session_key('claude', 'main')}.json"
    path.write_text(json.dumps(record))
    monkeypatch.setenv("PASEO_AGENT_ID", "paseo-main")

    _submit("claude", "main")

    wake = wake_of(tmp_path, "main")
    assert wake is not None
    assert wake["paseo_id"] == "paseo-main"


def test_hook_marker_refresh_preserves_runner_binding(tmp_path, monkeypatch):
    from varde_data.config import load_data_config
    from varde_data.open import open_data
    from varde_data.records.addresses import ReaderContext

    _environment(monkeypatch, tmp_path)
    marker = open_data(tmp_path, load_data_config()).addresses.issue(
        "main", supersede=True, now=_now()
    )
    data = open_data(tmp_path, load_data_config())
    assert data.addresses.redeem(
        marker,
        "runner-session",
        "claude",
        ReaderContext(
            cwd="/runner/workspace",
            agent_id="runner-session",
            runner_harness="claude-cli",
            runner_binding=True,
        ),
        now=_now(),
    )
    before = data.addresses.current_binding("main")
    assert before is not None
    monkeypatch.setenv("PASEO_AGENT_ID", "paseo-main")
    monkeypatch.setenv("VARDE_AGENT_ID", "/runner/workspace")
    monkeypatch.setenv("VARDE_HARNESS", "claude-cli")

    _submit("claude", "runner-session", marker)

    after = data.addresses.current_binding("main")
    assert after is not None
    assert after.extra["wake_context"] == before.extra["wake_context"]
    assert after.extra["runner_binding"] is True


def test_runner_off_delivers_nothing_and_opens_no_mailbox(tmp_path, monkeypatch):
    from varde.glue.inbox_hook import prompt_inbox

    _environment(monkeypatch, tmp_path)
    marker = BindingStore(tmp_path).issue("worker", now=_now())
    append_message("sender", "worker", "info", "pending", working=tmp_path)
    monkeypatch.setenv("VARDE_RUNNER_ENABLED", "0")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("mailbox opened with the runner off")

    payload = json.dumps({"session_id": "s1", "prompt": marker}).encode()

    with monkeypatch.context() as patched:
        patched.setattr("varde_data.open.open_data", forbidden)
        assert prompt_inbox("claude", payload) == []
        assert prompt_inbox("claude", payload, surface="stop") == []
    assert [item.text for item in unread(tmp_path, "worker")] == ["pending"]
    assert delivery_events(tmp_path) == []


def test_runner_default_off_with_no_env_and_no_config(tmp_path, monkeypatch):
    from varde.glue.inbox_hook import prompt_inbox

    _environment(monkeypatch, tmp_path)
    marker = BindingStore(tmp_path).issue("worker", now=_now())
    append_message("sender", "worker", "info", "pending", working=tmp_path)
    monkeypatch.delenv("VARDE_RUNNER_ENABLED")
    assert not (tmp_path / "config" / "config.toml").exists()
    payload = json.dumps({"session_id": "s1", "prompt": marker}).encode()

    assert prompt_inbox("claude", payload) == []
    assert [item.text for item in unread(tmp_path, "worker")] == ["pending"]
