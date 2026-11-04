import json
from types import SimpleNamespace

import pytest


@pytest.fixture
def real_adapters(monkeypatch):
    """Other tests register fakes in the global registry; restore the real ones."""
    from varde_learn.loop.diagnose.claude import ClaudeHarness
    from varde_learn.loop.diagnose.codex import CodexHarness
    from varde_learn.loop.diagnose.model import HARNESS_ADAPTERS
    from varde_learn.loop.diagnose.opencode import OpenCodeAdapter

    for adapter in (CodexHarness(), ClaudeHarness(), OpenCodeAdapter()):
        monkeypatch.setitem(HARNESS_ADAPTERS, adapter.harness, adapter)


def test_summary_entry_metrics_errors_and_mark_round_trip(
    tmp_path, monkeypatch, capsys
):
    from varde_learn.loop import cli_diagnose
    from varde_learn.loop.diagnose import summary
    from varde_learn.loop.diagnose.list import ListedSession, SessionList

    listed = [
        ListedSession("codex", f"s{i}", "active", "unlinked", None, str(tmp_path), True)
        for i in range(4)
    ]
    monkeypatch.setenv("VARDE_LEARN_STORE", str(tmp_path / "store"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    monkeypatch.setattr(summary, "list_sessions", lambda request: SessionList(listed))

    class Adapter:
        def inspect(self, request):
            if request.session_id == "s3":
                raise ValueError("broken session")
            return SimpleNamespace(
                records=[
                    {
                        "kind": "assistant",
                        "usage_total": {
                            "input_tokens": 11,
                            "cached_input_tokens": 5,
                            "output_tokens": 3,
                        },
                    }
                ]
            )

    monkeypatch.setattr(summary, "harness_adapter", lambda harness: Adapter())
    args = [
        "diagnose",
        "summary",
        "--harness",
        "codex",
        "--repository",
        str(tmp_path),
        "--json",
        "--mark",
    ]
    assert cli_diagnose.run(args) == 0
    payload = json.loads(capsys.readouterr().out)["data"]
    assert len(payload["sessions"]) == 3
    assert payload["sessions"][0]["input_tokens"] == 11
    assert payload["errors"][0]["id"] == "s3"

    # The failed inspection is not marked and is retried by the next --new run.
    listed[:] = [
        ListedSession("codex", "s3", "active", "unlinked", None, str(tmp_path), True)
    ]
    assert cli_diagnose.run(args[:-1] + ["--new"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["errors"][0]["id"] == "s3"

    listed[:] = [
        ListedSession("codex", "s0", "active", "unlinked", None, str(tmp_path), True)
    ]
    assert cli_diagnose.run(args[:-1] + ["--new"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["sessions"] == []


def _synthetic_homes(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    claude = tmp_path / "claude" / "projects" / "proj"
    claude.mkdir(parents=True)
    rows = [
        {
            "type": "user",
            "sessionId": "csess",
            "cwd": str(repo),
            "uuid": "u1",
            "timestamp": "2026-09-01T10:00:00Z",
            "message": {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        },
        {
            "type": "assistant",
            "sessionId": "csess",
            "cwd": str(repo),
            "uuid": "a1",
            "timestamp": "2026-09-01T10:00:09Z",
            "message": {
                "id": "m1",
                "role": "assistant",
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 7, "output_tokens": 4},
            },
        },
    ]
    (claude / "csess.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    rollout = tmp_path / "codex" / "sessions" / "2026" / "09" / "01"
    rollout.mkdir(parents=True)
    events = [
        {
            "type": "session_meta",
            "payload": {
                "id": "xsess",
                "cli_version": "0.162.1",
                "timestamp": "2026-09-01T10:00:00Z",
                "cwd": str(repo),
            },
        },
        {
            "type": "response_item",
            "timestamp": "2026-09-01T10:00:01Z",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": "hi"}],
            },
        },
        {
            "type": "response_item",
            "timestamp": "2026-09-01T10:00:05Z",
            "payload": {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "ok"}],
            },
        },
    ]
    (rollout / "rollout-2026-09-01T10-00-00-xsess.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in events)
    )
    return repo


def test_summary_reads_real_claude_and_codex_files(
    tmp_path, monkeypatch, capsys, real_adapters
):
    from varde_learn.loop import cli_diagnose

    repo = _synthetic_homes(tmp_path)
    monkeypatch.setenv("VARDE_LEARN_STORE", str(tmp_path / "store"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "no-opencode"))
    args = ["diagnose", "summary", "--repository", str(repo), "--json"]
    assert cli_diagnose.run([*args, "--harness", "all"]) == 0
    payload = json.loads(capsys.readouterr().out)["data"]
    assert payload["errors"] == []
    assert {(s["harness"], s["id"]) for s in payload["sessions"]} == {
        ("claude", "csess"),
        ("codex", "xsess"),
    }

    assert cli_diagnose.run(["diagnose", "list", *args[2:], "--harness", "codex"]) == 0
    listed = json.loads(capsys.readouterr().out)["data"]["sessions"]
    assert listed[0]["source"] == "active"
    assert listed[0]["path"].endswith("rollout-2026-09-01T10-00-00-xsess.jsonl")


def test_list_all_warns_and_continues_when_opencode_is_unreadable(
    tmp_path, monkeypatch, real_adapters
):
    from varde_learn.loop.diagnose import list as listing
    from varde_learn.loop.errors import Diagnose

    repo = _synthetic_homes(tmp_path)
    request = listing.ListRequest(
        "all",
        repo,
        tmp_path / "codex",
        tmp_path / "claude" / "projects",
        tmp_path / "opencode",
    )
    adapter = listing.HARNESS_ADAPTERS[listing.DiagnosticHarness.OPENCODE]

    def denied(**_):
        raise Diagnose(
            "diagnose_session_not_found",
            "cannot resolve OpenCode database: Operation not permitted",
        )

    monkeypatch.setattr(adapter, "discover", denied)
    result = listing.list_sessions(request)
    assert {s.harness for s in result.sessions} == {"claude", "codex"}
    assert any(
        "opencode" in w and "Operation not permitted" in w for w in result.warnings
    )


def test_session_errors_are_single_line():
    from varde_learn.loop.diagnose.summary import session_errors

    rows = session_errors(
        [
            {
                "kind": "tool_call",
                "tool_name": "Bash",
                "tool_error": "Exit code 1\nsed: bad\n  pattern",
            }
        ]
    )
    assert rows[0]["message"] == "Exit code 1 sed: bad pattern"


def test_session_errors_ignore_failed_items_without_a_tool():
    from varde_learn.loop.diagnose.summary import session_errors

    assert session_errors([{"kind": "item_completed", "tool_status": "failed"}]) == []
