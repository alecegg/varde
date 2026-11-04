from __future__ import annotations

import contextlib
import datetime as datetime_module
import io
import itertools
import json
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path

FIXED_NOW = datetime(2026, 10, 22, 12, tzinfo=UTC)
GOLDEN = Path(__file__).parent / "golden" / "addresses" / "hook_bind.json"


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls.fromtimestamp(FIXED_NOW.timestamp(), UTC)
        return value if tz is None else value.astimezone(tz)


def test_hook_marker_bind_golden(tmp_path: Path, monkeypatch) -> None:
    working = tmp_path / "working"
    working.mkdir()
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    monkeypatch.setenv("PWD", str(working))
    monkeypatch.setenv("PASEO_AGENT_ID", "paseo-fixed")
    monkeypatch.setenv("VARDE_AGENT_ID", "agent-fixed")
    monkeypatch.setenv("VARDE_HARNESS", "codex")
    monkeypatch.setenv("VARDE_RUNNER_ENDPOINT", "endpoint-fixed")
    monkeypatch.chdir(working)
    monkeypatch.setattr(datetime_module, "datetime", FixedDateTime)
    from varde_workflow import binding, inbox

    monkeypatch.setattr(binding, "datetime", FixedDateTime)
    monkeypatch.setattr(inbox, "datetime", FixedDateTime)
    from varde.glue import inbox_hook

    monkeypatch.setattr(inbox_hook, "datetime", FixedDateTime)
    ids = itertools.count(1)
    monkeypatch.setattr(secrets, "token_hex", lambda _size: f"{next(ids):08x}")
    monkeypatch.setattr(secrets, "token_bytes", lambda size: bytes([next(ids)]) * size)
    from varde_workflow.binding import BindingStore

    issue = BindingStore.issue

    def issue_with_fixture_source(self, *args, **kwargs):
        marker = issue(self, *args, **kwargs)
        next(ids)
        return marker

    monkeypatch.setattr(BindingStore, "issue", issue_with_fixture_source)
    from varde_workflow.inbox import append_message

    store = BindingStore(working)
    marker = store.issue("worker", now=FIXED_NOW)
    from varde.glue.hook import dispatch

    append_message(
        "sender", "worker", "info", "hook bound", working=working, now=FIXED_NOW
    )
    payload = json.dumps(
        {
            "event": "user-prompt-submit",
            "input": json.dumps(
                {
                    "session_id": "hook-session",
                    "prompt": f"start\n{marker}",
                }
            ),
        }
    )
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        exit_code = dispatch(json.loads(payload), "claude")
    inbox = working / ".cache" / "inbox"
    paths = [
        inbox / "events.jsonl",
        *inbox.joinpath("bindings").glob("*.json"),
        *inbox.joinpath("addresses").glob("worker/current"),
    ]
    snapshot = {
        "classification": "unchanged",
        "marker": marker,
        "exit": exit_code,
        "stdout_lines": stdout.getvalue().splitlines(),
        "store": {
            str(path.relative_to(working)): {
                "bytes": path.read_bytes().decode("utf-8"),
                "mode": f"{path.stat().st_mode & 0o777:04o}",
            }
            for path in paths
        },
    }
    rendered = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    rendered = rendered.replace(str(tmp_path), "<TMP>")
    if os.environ.get("VARDE_UPDATE_GOLDENS") == "1":
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN.write_text(rendered, encoding="utf-8")
    assert GOLDEN.read_text(encoding="utf-8") == rendered
