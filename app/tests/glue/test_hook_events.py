from __future__ import annotations

import contextlib
import io
import json
import subprocess
from datetime import UTC, datetime

import pytest
from varde.glue.hook import dispatch
from varde_workflow.binding import BindingStore
from varde_workflow.commands.msg import append_message
from varde_workflow.inbox import delivery_events


def _now():
    return datetime.now(UTC)


def setup(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("VARDE_WORKING_DIR", str(tmp_path))
    monkeypatch.delenv("VARDE_ADDRESS", raising=False)


def call(event, harness, data):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        status = dispatch({"event": event, "input": json.dumps(data).encode()}, harness)
    return status, out.getvalue()


def test_session_start_compact_and_post_tool_use_deliver_once(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    store = BindingStore(tmp_path)
    marker = store.issue("worker", now=_now())
    append_message("sender", "worker", "info", "startup", working=tmp_path)
    data = {"session_id": "s1", "prompt": marker}
    _, started = call("session-start", "claude", data)
    assert "sender info: startup" in started
    append_message("sender", "worker", "info", "hello", working=tmp_path)
    _, delivered = call("post-tool-use", "claude", {"session_id": "s1"})
    _, repeated = call("post-tool-use", "claude", {"session_id": "s1"})
    assert "sender info: hello" in delivered
    assert "hello" not in repeated
    _, compact = call(
        "session-start", "claude", {"session_id": "s1", "source": "compact"}
    )
    assert "varde address: worker" in compact
    assert [e["event"] for e in delivery_events(tmp_path)] == [
        "delivered",
        "acked",
        "delivered",
        "acked",
    ]


def linked_repos(tmp_path):
    main = tmp_path / "main"
    worktree = tmp_path / "worktree"
    main.mkdir()
    subprocess.run(["git", "init", str(main)], check=True, capture_output=True)  # noqa: S603, S607 - test creates a local fixture repo
    subprocess.run(  # noqa: S603 - test configures its local fixture repo
        ["git", "-C", str(main), "config", "user.name", "Test"],  # noqa: S607 - fixed git command
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603 - test configures its local fixture repo
        ["git", "-C", str(main), "config", "user.email", "test@example.com"],  # noqa: S607 - fixed git command
        check=True,
        capture_output=True,
    )
    (main / "app").mkdir()
    (main / "app" / "source.py").write_text("pass\n")
    subprocess.run(  # noqa: S603 - test stages a fixture file
        ["git", "-C", str(main), "add", "app/source.py"],  # noqa: S607 - fixed git command
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603 - test commits a fixture repository
        ["git", "-C", str(main), "commit", "-m", "init"],  # noqa: S607 - fixed git command
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603 - test creates an isolated worktree
        ["git", "-C", str(main), "worktree", "add", "-b", "task", str(worktree)],  # noqa: S607 - fixed git command
        check=True,
        capture_output=True,
    )
    return main, worktree


@pytest.mark.parametrize("harness", ["claude", "codex"])
def test_pre_tool_use_outputs_harness_deny_payload(tmp_path, monkeypatch, harness):
    setup(tmp_path, monkeypatch)
    monkeypatch.setenv("VARDE_LEARN_STORE", str(tmp_path / "learn"))
    _, worktree = linked_repos(tmp_path)
    _, output = call(
        "pre-tool-use",
        harness,
        {
            "tool_name": "Bash",
            "cwd": str(worktree),
            "tool_input": {"command": "uv tool install varde"},
        },
    )
    result = json.loads(output)["hookSpecificOutput"]
    assert result["permissionDecision"] == "deny"
    assert "main checkout after merge" in result["permissionDecisionReason"]
    from varde_learn.loop.calls import read_calls

    rows = read_calls(tmp_path / "learn")
    assert [(row.get("guardrail"), row["status"]) for row in rows] == [
        ("hook-pre-tool-install-guard", "blocked")
    ]


def test_claude_pre_tool_use_documented_contract(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    monkeypatch.setenv("VARDE_LEARN_STORE", str(tmp_path / "learn"))
    _, worktree = linked_repos(tmp_path)
    # Claude Code PreToolUse contract: https://code.claude.com/docs/en/hooks
    payload = {
        "session_id": "session-1",
        "transcript_path": str(tmp_path / "session.jsonl"),
        "cwd": str(worktree),
        "permission_mode": "default",
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {
            "command": "uv tool install varde",
            "description": "Install Varde",
            "timeout": 1000,
            "run_in_background": False,
        },
        "tool_use_id": "toolu_123",
    }
    status, output = call("pre-tool-use", "claude", payload)

    assert status == 0
    assert output
    assert json.loads(output) == {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                "uv tool install/upgrade/uninstall is blocked when the command "
                "or install source is in a linked worktree. Install only from "
                "the main checkout after merge, or build a PEX to a temp dir."
            ),
        }
    }

    payload["tool_input"]["command"] = "uv run pytest"
    status, output = call("pre-tool-use", "claude", payload)
    assert status == 0
    assert output == ""
    from varde_learn.loop.calls import read_calls

    assert [row.get("guardrail") for row in read_calls(tmp_path / "learn")] == [
        "hook-pre-tool-install-guard"
    ]


def test_pre_tool_use_ignores_invalid_or_irrelevant_payloads(tmp_path):
    _, worktree = linked_repos(tmp_path)
    for payload in (
        b"not json",
        json.dumps(
            {
                "tool_name": "Read",
                "cwd": str(worktree),
                "tool_input": {"command": "uv tool install"},
            }
        ).encode(),
        json.dumps(
            {"tool_name": "Bash", "tool_input": {"command": "uv tool install"}}
        ).encode(),
        json.dumps(
            {
                "tool_name": "Bash",
                "cwd": str(tmp_path / "missing"),
                "tool_input": {"command": "uv tool install"},
            }
        ).encode(),
    ):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            dispatch({"event": "pre-tool-use", "input": payload}, "claude")
        assert output.getvalue() == ""


def test_stop_blocks_mail_once_and_guards_subagents_and_unknown_events(
    tmp_path, monkeypatch
):
    setup(tmp_path, monkeypatch)
    monkeypatch.setenv("VARDE_LEARN_STORE", str(tmp_path / "learn"))
    store = BindingStore(tmp_path)
    marker = store.issue("worker", now=_now())
    assert store.redeem(marker, "s1", "claude", str(tmp_path), now=_now())
    append_message("sender", "worker", "info", "stop mail", working=tmp_path)
    _, blocked = call("stop", "claude", {"session_id": "s1"})
    assert json.loads(blocked)["decision"] == "block"
    assert "stop mail" in blocked
    from varde_learn.loop.calls import read_calls

    assert [
        (row.get("guardrail"), row["status"]) for row in read_calls(tmp_path / "learn")
    ] == [("hook-stop-inbox-block", "blocked")]
    _, allow = call("stop", "claude", {"session_id": "s1", "stop_hook_active": True})
    assert allow == ""
    append_message(
        "sender", "worker", "info", "arrived while stopping", working=tmp_path
    )
    _, active_with_mail = call(
        "stop", "claude", {"session_id": "s1", "stop_hook_active": True}
    )
    assert json.loads(active_with_mail)["decision"] == "block"
    assert "arrived while stopping" in active_with_mail
    _, subagent = call("stop", "claude", {"session_id": "s1", "agent_id": "child"})
    assert subagent == ""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert dispatch({"event": "never-event", "input": b"{}"}, "claude") == 2
    assert out.getvalue() == ""


def test_unbound_stop_and_session_start_report_held_mail(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    monkeypatch.setenv("VARDE_LEARN_STORE", str(tmp_path / "learn"))
    _, stop_result = call("stop", "claude", {"session_id": "unbound"})
    _, start_result = call("session-start", "claude", {"session_id": "unbound"})
    assert stop_result == ""
    from varde_learn.loop.calls import read_calls

    assert read_calls(tmp_path / "learn") == []
    assert "this session is unregistered" in start_result


def test_pi_prompt_payload_binds_marker_from_event_prompt(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    marker = BindingStore(tmp_path).issue("pi-worker", now=_now())
    append_message("sender", "pi-worker", "info", "Pi prompt", working=tmp_path)
    # Mirrors pi.ts's Python-side JSON contract: event.prompt is forwarded as prompt.
    _, output = call(
        "user-prompt-submit",
        "pi",
        {"session_id": "pi-session", "prompt": f"hello\n{marker}"},
    )
    assert "sender info: Pi prompt" in output
    assert (
        BindingStore(tmp_path).resolve_reader("pi", "pi-session", "", {}, _now())
        == "pi-worker"
    )


def test_tool_result_marker_and_subagent_hook_payloads_do_not_bind(
    tmp_path, monkeypatch
):
    setup(tmp_path, monkeypatch)
    marker = BindingStore(tmp_path).issue("worker", now=_now())
    _, output = call(
        "post-tool-use",
        "claude",
        {"session_id": "tool-result", "tool_response": marker},
    )
    assert output == ""
    assert (
        BindingStore(tmp_path).resolve_reader("claude", "tool-result", "", {}, _now())
        is None
    )

    _, post_tool = call(
        "post-tool-use", "claude", {"session_id": "child", "agent_id": "child"}
    )
    _, started = call(
        "session-start", "claude", {"session_id": "child", "agent_id": "child"}
    )
    assert "varde address:" not in post_tool
    assert "unregistered" not in started
    assert (
        BindingStore(tmp_path).resolve_reader("claude", "child", "", {}, _now()) is None
    )


def test_session_start_compact_uses_owner_route(tmp_path, monkeypatch):
    setup(tmp_path, monkeypatch)
    monkeypatch.delenv("VARDE_ADDRESS", raising=False)
    plan = tmp_path / "plans" / "owned-plan" / "plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("---\ntype: plan\nowner: pi:owned-session\n---\n", encoding="utf-8")

    _, output = call(
        "session-start",
        "pi",
        {"session_id": "owned-session", "source": "compact"},
    )
    assert "varde address: owned-plan" in output
    assert "unregistered" not in output


def test_stop_fastpath_help_and_unknown_event_status(capsys):
    from varde.fastpath import run

    assert run(["hook", "stop", "--help"]) == 0
    assert "Usage: varde hook stop" in capsys.readouterr().out
    assert run(["hook", "unknown", "--harness", "claude"]) == 2
