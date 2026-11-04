from __future__ import annotations

import concurrent.futures
import hashlib
import json
import multiprocessing
import os
import re
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from varde_workflow import binding

NOW = datetime(2026, 10, 17, 12, tzinfo=UTC)


def test_annotate_stale_bindings_by_paseo_id_without_mutating() -> None:
    bindings = [
        {"address": "one", "wake_context": {"paseo_id": "archived"}},
        {"address": "two", "wake_context": {"paseo_id": "active"}},
        {"address": "three", "wake_context": {}},
    ]
    annotated = binding.annotate_stale_bindings(bindings, ["archived", "other"])
    assert [item["stale"] for item in annotated] == [True, False, False]
    assert all("stale" not in item for item in bindings)
    assert annotated[0] is not bindings[0]
    assert binding.annotate_stale_bindings(bindings, []) == [
        {**item, "stale": False} for item in bindings
    ]


def test_env_working_dir_counts_as_resolved(monkeypatch, tmp_path: Path) -> None:
    from types import SimpleNamespace

    import tomlkit
    from varde_learn.knowledge import memory

    working = tmp_path / "env-working"
    monkeypatch.setenv("VARDE_WORKING_DIR", str(working))
    monkeypatch.setattr(
        memory, "load_config", lambda: SimpleNamespace(document=tomlkit.parse(""))
    )
    resolved, project_resolved = binding.resolve_working_dir_with_source(
        tmp_path / "outside"
    )
    assert resolved == working
    assert project_resolved


def test_marker_requires_own_line_in_first_five_lines() -> None:
    marker = "[varde-address: demo vt1.AAAAAAAAAAAAAAAAAAAAAAAAAA]"
    assert binding.parse_marker("\n".join([marker] + ["x"] * 4)) == (
        "demo",
        "vt1.AAAAAAAAAAAAAAAAAAAAAAAAAA",
    )
    assert binding.parse_marker("\n".join(["x"] * 4 + [marker])) is not None
    assert binding.parse_marker("\n".join(["x"] * 5 + [marker])) is None
    assert binding.parse_marker(" " + marker) is None
    assert binding.parse_marker("prefix " + marker) is None
    assert binding.parse_marker("preamble\v" + marker) is None
    assert binding.parse_marker("[varde-address: bad name token]") is None


def test_resolve_reader_binds_marker_only_when_in_first_five_unindented_lines(
    tmp_path: Path,
) -> None:
    store = binding.BindingStore(tmp_path)
    marker = store.issue("demo", now=NOW)
    assert (
        store.resolve_reader("claude", "one", "preamble\n" + marker, {}, NOW) == "demo"
    )
    lower = store.issue("lower", now=NOW)
    assert (
        store.resolve_reader("claude", "two", "\n".join(["x"] * 5 + [lower]), {}, NOW)
        is None
    )
    indented = store.issue("indented", now=NOW)
    assert store.resolve_reader("claude", "three", " " + indented, {}, NOW) is None


def test_issue_and_redeem_bind_with_expiry_and_current_pointer(tmp_path: Path) -> None:
    store = binding.BindingStore(tmp_path)
    marker = store.issue("demo", now=NOW)
    assert re.fullmatch(r"\[varde-address: demo vt1\.[A-Z2-7]{26}\]", marker)
    assert store.redeem(marker, "one", "claude", "/repo", now=NOW)
    assert store.resolve_reader("claude", "one", "", {}, NOW) == "demo"
    assert store.resolve_reader("claude", "fork", "", {}, NOW) is None
    assert store.redeem(marker, "one", "claude", "/repo", now=NOW)

    expired = store.issue("expired", ttl=timedelta(seconds=1), now=NOW)
    assert not store.redeem(
        expired, "claude:two", "claude", "/repo", now=NOW + timedelta(seconds=2)
    )
    assert (
        store.resolve_reader("claude", "two", expired, {}, NOW + timedelta(seconds=2))
        is None
    )


def test_marker_errors_report_each_refusal_cause(tmp_path: Path) -> None:
    store = binding.BindingStore(tmp_path)
    superseded = store.issue("demo", now=NOW)
    replacement = store.issue("demo", supersede=True, now=NOW)
    assert store.redeem(replacement, "second", "claude", "/repo", now=NOW)
    expired = store.issue("expired", ttl=timedelta(seconds=1), now=NOW)
    used = store.issue("used", now=NOW)
    assert store.redeem(used, "third", "claude", "/repo", now=NOW)
    live = store.issue("live", uses=2, now=NOW)
    blocked = live
    assert store.redeem(live, "fourth", "claude", "/repo", now=NOW)

    assert "superseded" in store.marker_error(superseded, NOW)
    assert store.marker_error(expired, NOW + timedelta(seconds=2)) == "marker expired"
    assert store.marker_error(used, NOW) == "marker already used"
    assert (
        store.marker_error(
            "[varde-address: unknown vt1.AAAAAAAAAAAAAAAAAAAAAAAAAA]", NOW
        )
        == "unknown marker"
    )
    assert (
        store.marker_error(blocked, NOW + timedelta(seconds=1))
        == "live binding refuses this marker"
    )


def test_marker_error_treats_malformed_uses_left_as_spent(tmp_path: Path) -> None:
    store = binding.BindingStore(tmp_path)
    marker = store.issue("demo", now=NOW)
    token_path = next((tmp_path / ".cache/inbox/addresses/demo/tokens").glob("*.json"))
    token = json.loads(token_path.read_text())
    token["uses_left"] = "invalid"
    token_path.write_text(json.dumps(token))

    assert store.marker_error(marker, NOW) == "marker already used"


def test_address_list_displays_store_path(tmp_path: Path, capsys) -> None:
    from argparse import Namespace

    from varde_workflow.commands.address import run

    working = tmp_path / "working"
    assert run(Namespace(address_action="list", json=False), working) == 0
    assert capsys.readouterr().out == f"store: {working / '.cache' / 'inbox'}\n"


def test_supersede_replacement_redeems_while_spent_tokens_do_not(
    tmp_path: Path,
) -> None:
    store = binding.BindingStore(tmp_path)
    expired = store.issue("demo", ttl=timedelta(seconds=1), now=NOW)
    spent = store.issue("demo", now=NOW + timedelta(seconds=2))
    assert store.redeem(spent, "one", "claude", "/repo", now=NOW + timedelta(seconds=2))
    replacement = store.issue("demo", now=NOW + timedelta(seconds=3), supersede=True)

    assert not store.redeem(
        expired, "two", "claude", "/repo", now=NOW + timedelta(seconds=3)
    )
    assert not store.redeem(
        spent, "three", "claude", "/repo", now=NOW + timedelta(seconds=3)
    )
    assert store.redeem(
        replacement, "four", "claude", "/repo", now=NOW + timedelta(seconds=3)
    )


def test_one_use_token_has_one_concurrent_winner_and_reuse_event(
    tmp_path: Path,
) -> None:
    store = binding.BindingStore(tmp_path)
    marker = store.issue("demo", uses=1, now=NOW)
    barrier = threading.Barrier(2)

    def redeem(session: str) -> bool:
        barrier.wait()
        return store.redeem(marker, session, "claude", "/repo", now=NOW)

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(redeem, ("claude:one", "claude:two")))
    assert sorted(results) == [False, True]
    events = [
        json.loads(row)
        for row in (tmp_path / ".cache/inbox/events.jsonl").read_text().splitlines()
    ]
    assert [event["event"] for event in events] == ["bind", "token-reuse"]


def _redeem_process(working: str, marker: str, session: str, barrier, results) -> None:
    barrier.wait()
    results.put(
        binding.BindingStore(working).redeem(
            marker, session, "claude", "/repo", now=NOW
        )
    )


def test_one_use_token_has_one_winner_across_processes(tmp_path: Path) -> None:
    store = binding.BindingStore(tmp_path)
    marker = store.issue("race", now=NOW)
    context = multiprocessing.get_context("fork")
    barrier, results = context.Barrier(2), context.Queue()
    workers = [
        context.Process(
            target=_redeem_process, args=(str(tmp_path), marker, sid, barrier, results)
        )
        for sid in ("a", "b")
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
        assert worker.exitcode == 0
    assert sorted(results.get(timeout=2) for _ in workers) == [False, True]


def test_var_de_address_and_supersede_guards(tmp_path: Path) -> None:
    store = binding.BindingStore(tmp_path)
    main_marker = store.issue("main", now=NOW, supersede=True)
    assert store.redeem(main_marker, "main", "claude", "/repo", now=NOW)
    assert (
        store.resolve_reader("claude", "child", "", {"VARDE_ADDRESS": "main"}, NOW)
        is None
    )

    with pytest.raises(ValueError, match="supersede"):
        store.issue("main", now=NOW + timedelta(minutes=1))
    replacement = store.issue("main", now=NOW + timedelta(minutes=1), supersede=True)
    assert store.redeem(
        replacement, "new", "claude", "/repo", now=NOW + timedelta(minutes=1)
    )
    assert (
        store.resolve_reader("claude", "main", "", {}, NOW + timedelta(minutes=1))
        is None
    )
    assert (
        store.resolve_reader("claude", "new", "", {}, NOW + timedelta(minutes=1))
        == "main"
    )


def test_var_de_address_binds_only_when_address_has_no_live_binding(
    tmp_path: Path,
) -> None:
    store = binding.BindingStore(tmp_path)
    assert (
        store.resolve_reader("claude", "first", "", {"VARDE_ADDRESS": "demo"}, NOW)
        == "demo"
    )
    assert (
        store.resolve_reader(
            "claude",
            "second",
            "",
            {"VARDE_ADDRESS": "demo"},
            NOW + timedelta(minutes=1),
        )
        is None
    )


def test_var_de_address_idle_takeover_logs_supersede(tmp_path: Path) -> None:
    store = binding.BindingStore(tmp_path)
    idle = NOW - timedelta(minutes=31)
    marker = store.issue("demo", now=idle)
    assert store.redeem(marker, "old", "claude", "/repo", now=idle)
    assert (
        store.resolve_reader("claude", "child", "", {"VARDE_ADDRESS": "demo"}, NOW)
        == "demo"
    )
    events = (tmp_path / ".cache/inbox/events.jsonl").read_text().splitlines()
    supersede = [
        json.loads(line) for line in events if json.loads(line)["event"] == "supersede"
    ]
    assert supersede[0]["prior_live"] is False


def test_live_supersede_event_records_prior_binding_as_live(tmp_path: Path) -> None:
    store = binding.BindingStore(tmp_path)
    first = store.issue("demo", now=NOW)
    assert store.redeem(first, "old", "claude", "/repo", now=NOW)
    replacement = store.issue("demo", supersede=True, now=NOW + timedelta(minutes=1))
    assert store.redeem(
        replacement, "new", "claude", "/repo", now=NOW + timedelta(minutes=1)
    )

    events = [
        json.loads(line)
        for line in (tmp_path / ".cache/inbox/events.jsonl").read_text().splitlines()
    ]
    supersede = [event for event in events if event["event"] == "supersede"]
    assert supersede[0]["prior_live"] is True


def test_unbind_by_session_revokes_current_pointer(tmp_path: Path) -> None:
    store = binding.BindingStore(tmp_path)
    marker = store.issue("demo", uses=2, now=NOW)
    assert store.redeem(marker, "one", "claude", "/repo", now=NOW)
    assert store.unbind("one", NOW + timedelta(seconds=1))
    assert not store.redeem(
        marker, "one", "claude", "/repo", now=NOW + timedelta(seconds=2)
    )
    assert (
        store.resolve_reader("claude", "one", "", {}, NOW + timedelta(seconds=2))
        is None
    )


def test_unbind_then_marker_rebinds(tmp_path: Path) -> None:
    store = binding.BindingStore(tmp_path)
    first = store.issue("demo", uses=2, now=NOW)
    assert store.redeem(first, "one", "claude", "/repo", now=NOW)
    assert (
        store.resolve_reader("claude", "one", "", {}, NOW + timedelta(seconds=30))
        == "demo"
    )
    assert store.unbind("one", NOW + timedelta(seconds=61))
    assert (
        store.resolve_reader("claude", "one", "", {}, NOW + timedelta(seconds=62))
        is None
    )
    next_marker = store.issue("demo", now=NOW + timedelta(seconds=62))
    assert (
        store.resolve_reader(
            "claude", "one", next_marker, {}, NOW + timedelta(seconds=63)
        )
        == "demo"
    )


def test_supersede_recent_non_main_refused_without_flag(tmp_path: Path) -> None:
    store = binding.BindingStore(tmp_path)
    first = store.issue("demo", now=NOW)
    assert store.redeem(first, "claude:one", "claude", "/repo", now=NOW)
    with pytest.raises(ValueError, match="supersede"):
        store.issue("demo", now=NOW + timedelta(minutes=1))
    assert store.issue("demo", now=NOW + timedelta(minutes=31))


def test_supersede_invalidates_old_session_and_old_token(tmp_path: Path) -> None:
    store = binding.BindingStore(tmp_path)
    old_marker = store.issue("demo", uses=2, now=NOW)
    assert store.redeem(old_marker, "old", "claude", "/repo", now=NOW)
    new_marker = store.issue("demo", now=NOW + timedelta(minutes=1), supersede=True)
    assert store.redeem(
        new_marker, "new", "claude", "/repo", now=NOW + timedelta(minutes=1)
    )
    assert (
        store.resolve_reader("claude", "old", "", {}, NOW + timedelta(minutes=2))
        is None
    )
    assert not store.redeem(
        old_marker, "old", "claude", "/repo", now=NOW + timedelta(minutes=2)
    )


def test_command_emits_one_marker_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from varde_workflow.commands.address import run_new

    assert run_new("demo", tmp_path, now=NOW) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert re.fullmatch(r"\[varde-address: demo vt1\.[A-Z2-7]{26}\]\n", captured.out)


def test_bind_command_uses_claude_session_environment(
    tmp_path: Path, monkeypatch
) -> None:
    from argparse import Namespace

    from varde_workflow.commands.address import SESSION_ENV_VARS, run

    for variable, _ in SESSION_ENV_VARS:
        monkeypatch.delenv(variable, raising=False)

    now = datetime.now(UTC)
    marker = binding.BindingStore(tmp_path).issue("demo", now=now)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "from-environment")
    args = Namespace(
        address_action="bind", session="", harness="unknown", marker=marker
    )
    assert run(args, tmp_path) == 0
    assert (
        binding.BindingStore(tmp_path).resolve_reader(
            "claude", "from-environment", "", {}, now
        )
        == "demo"
    )


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        (
            {"CODEX_SESSION_ID": "codex", "CLAUDE_CODE_SESSION_ID": "claude"},
            ("claude", "claude"),
        ),
        ({"CODEX_THREAD_ID": "thread"}, ("thread", "codex")),
        ({"PI_SESSION_ID": "pi"}, ("pi", "pi")),
        ({}, ("", "unknown")),
    ],
)
def test_session_and_harness_from_env(
    env: dict[str, str], expected: tuple[str, str]
) -> None:
    from varde_workflow.commands.address import _session_and_harness_from_env

    assert _session_and_harness_from_env(env) == expected


def test_session_env_ignores_empty_values() -> None:
    from varde_workflow.commands.address import _session_and_harness_from_env

    assert _session_and_harness_from_env({"CLAUDE_CODE_SESSION_ID": ""}) == (
        "",
        "unknown",
    )


def test_explicit_harness_selects_its_family_in_mixed_environment() -> None:
    from varde_workflow.commands.address import _session_and_harness_from_env

    env = {"CLAUDE_CODE_SESSION_ID": "claude-id", "CODEX_SESSION_ID": "codex-id"}
    assert _session_and_harness_from_env(env, harness="codex") == ("codex-id", "codex")


def test_bind_explicit_harness_uses_only_that_harness_environment(
    tmp_path: Path, monkeypatch
) -> None:
    from argparse import Namespace

    from varde_workflow.commands.address import SESSION_ENV_VARS, run

    for variable, _ in SESSION_ENV_VARS:
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "claude-id")
    monkeypatch.setenv("CODEX_SESSION_ID", "codex-id")
    now = datetime.now(UTC)
    marker = binding.BindingStore(tmp_path).issue("demo", now=now)
    args = Namespace(address_action="bind", session="", harness="codex", marker=marker)

    assert run(args, tmp_path) == 0
    assert (
        binding.BindingStore(tmp_path).resolve_reader("codex", "codex-id", "", {}, now)
        == "demo"
    )


def test_bind_command_uses_claude_code_session_environment(
    tmp_path: Path, monkeypatch
) -> None:
    from argparse import Namespace

    from varde_workflow.commands.address import SESSION_ENV_VARS, run

    for variable, _ in SESSION_ENV_VARS:
        monkeypatch.delenv(variable, raising=False)

    now = datetime.now(UTC)
    marker = binding.BindingStore(tmp_path).issue("demo", now=now)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "claude-code-session")
    args = Namespace(
        address_action="bind", session="", harness="unknown", marker=marker
    )
    assert run(args, tmp_path) == 0
    assert (
        binding.BindingStore(tmp_path).resolve_reader(
            "claude", "claude-code-session", "", {}, now
        )
        == "demo"
    )


def test_bind_explicit_session_and_harness_win_over_environment(
    tmp_path: Path, monkeypatch
) -> None:
    from argparse import Namespace

    from varde_workflow.commands.address import SESSION_ENV_VARS, run

    for variable, _ in SESSION_ENV_VARS:
        monkeypatch.delenv(variable, raising=False)

    now = datetime.now(UTC)
    marker = binding.BindingStore(tmp_path).issue("demo", now=now)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "environment-session")
    args = Namespace(
        address_action="bind", session="explicit-session", harness="pi", marker=marker
    )
    assert run(args, tmp_path) == 0
    assert (
        binding.BindingStore(tmp_path).resolve_reader(
            "pi", "explicit-session", "", {}, now
        )
        == "demo"
    )


def test_unknown_harness_without_session_environment() -> None:
    from varde_workflow.commands.address import _session_and_harness_from_env

    assert _session_and_harness_from_env({}) == ("", "unknown")


def test_token_file_is_private_and_hash_only(tmp_path: Path) -> None:
    store = binding.BindingStore(tmp_path)
    marker = store.issue("demo", now=NOW)
    token = marker.removeprefix("[varde-address: demo ").removesuffix("]")
    token_files = list((tmp_path / ".cache/inbox/addresses/demo/tokens").glob("*.json"))
    assert len(token_files) == 1
    assert os.stat(token_files[0]).st_mode & 0o777 == 0o600
    record = json.loads(token_files[0].read_text())
    assert record["sha256"] == hashlib.sha256(token.encode()).hexdigest()
    assert token not in token_files[0].read_text()


def test_wake_context_gone_and_resolved_event_bypasses_touch_throttle(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from varde_workflow.binding import mark_wake_gone, wake_of
    from varde_workflow.inbox import append_message, record_delivery

    store = binding.BindingStore(tmp_path)
    monkeypatch.setenv("PASEO_AGENT_ID", "paseo-7")
    marker = store.issue("worker", now=NOW)
    assert store.redeem(marker, "s", "claude", "/repo", now=NOW)
    context = wake_of(tmp_path, "worker")
    assert context == {
        "harness": "claude",
        "session_id": "s",
        "cwd": "/repo",
        "paseo_id": "paseo-7",
    }
    mark_wake_gone(tmp_path, "worker", NOW + timedelta(seconds=1))
    message = append_message(
        "main", "worker", "info", "wake", working=tmp_path, now=NOW
    )
    assert message.id is not None
    record_delivery(
        tmp_path,
        message.id,
        "worker",
        now=(NOW + timedelta(seconds=2)).isoformat(),
        via="hook",
    )
    record = store.list_bindings()[0]
    assert record["wake"] == "active"
    assert record["last_seen"] == (NOW + timedelta(seconds=2)).isoformat().replace(
        "+00:00", "Z"
    )


def test_empty_inbox_hook_resolution_clears_gone_without_waiting_for_throttle(
    tmp_path: Path,
) -> None:
    from varde_workflow.binding import mark_wake_gone

    store = binding.BindingStore(tmp_path)
    marker = store.issue("worker", now=NOW)
    assert store.redeem(marker, "s", "claude", "/repo", now=NOW)
    mark_wake_gone(tmp_path, "worker", NOW + timedelta(seconds=1))
    assert (
        store.resolve_reader("claude", "s", "", {}, NOW + timedelta(seconds=2))
        == "worker"
    )
    assert store.list_bindings()[0]["wake"] == "active"


def test_same_session_redeem_refreshes_paseo_id(tmp_path, monkeypatch):
    store = binding.BindingStore(tmp_path)
    marker = store.issue("demo", now=NOW)
    monkeypatch.delenv("PASEO_AGENT_ID", raising=False)
    assert store.redeem(marker, "one", "claude", "/old", now=NOW)
    monkeypatch.setenv("PASEO_AGENT_ID", "agent-new")

    assert store.redeem(marker, "one", "claude", "/new", now=NOW + timedelta(seconds=1))

    record = store.list_bindings()[0]
    assert record["wake_context"] == {
        "harness": "claude",
        "session_id": "one",
        "cwd": "/new",
        "paseo_id": "agent-new",
    }


def test_resolve_reader_refreshes_paseo_id_without_clearing_when_unset(
    tmp_path, monkeypatch
):
    store = binding.BindingStore(tmp_path)
    marker = store.issue("demo", now=NOW)
    assert store.redeem(marker, "one", "claude", "/repo", now=NOW)
    env = {"PWD": "/new", "PASEO_AGENT_ID": "agent-one"}
    assert (
        store.resolve_reader("claude", "one", "", env, NOW + timedelta(seconds=1))
        == "demo"
    )
    assert _paseo_id(store) == "agent-one"
    assert (
        store.resolve_reader(
            "claude", "one", "", {"PWD": "/later"}, NOW + timedelta(seconds=2)
        )
        == "demo"
    )
    assert _paseo_id(store) == "agent-one"


def test_native_wake_bind_and_refresh_preserve_both_ids(tmp_path, monkeypatch):
    store = binding.BindingStore(tmp_path)
    marker = store.issue("demo", now=NOW)
    monkeypatch.setenv("VARDE_AGENT_ID", "runner-agent")
    monkeypatch.setenv("VARDE_HARNESS", "claude-cli")
    monkeypatch.setenv("VARDE_RUNNER_ENDPOINT", "http://127.0.0.1:9000")
    monkeypatch.setenv("PASEO_AGENT_ID", "paseo-agent")

    assert store.redeem(marker, "one", "claude", "/repo", now=NOW)
    wake = store.list_bindings()[0]["wake_context"]
    assert isinstance(wake, dict)
    assert wake["agent_id"] == "runner-agent"
    assert wake["harness"] == "claude-cli"
    assert wake["runner_endpoint"] == "http://127.0.0.1:9000"
    assert wake["paseo_id"] == "paseo-agent"

    monkeypatch.setenv("VARDE_AGENT_ID", "runner-agent-new")
    assert store.refresh_current(
        "claude",
        "one",
        "/new",
        None,
        NOW + timedelta(seconds=1),
        agent_id=os.environ["VARDE_AGENT_ID"],
        runner_harness=os.environ["VARDE_HARNESS"],
        runner_endpoint=os.environ["VARDE_RUNNER_ENDPOINT"],
    )
    wake = store.list_bindings()[0]["wake_context"]
    assert isinstance(wake, dict)
    assert wake["agent_id"] == "runner-agent-new"
    assert wake["paseo_id"] == "paseo-agent"


def test_native_wake_does_not_guess_missing_agent_id(tmp_path, monkeypatch):
    store = binding.BindingStore(tmp_path)
    marker = store.issue("demo", now=NOW)
    monkeypatch.delenv("VARDE_AGENT_ID", raising=False)
    monkeypatch.delenv("PASEO_AGENT_ID", raising=False)
    assert store.redeem(marker, "session-value", "claude", "/repo", now=NOW)
    wake = store.list_bindings()[0]["wake_context"]
    assert isinstance(wake, dict)
    assert "agent_id" not in wake
    assert wake["paseo_id"] == ""
    wake_of = binding.wake_of(tmp_path, "demo")
    assert wake_of is not None
    assert wake_of["paseo_id"] == ""


def test_bind_without_runner_harness_uses_hook_harness_without_native_id(
    tmp_path, monkeypatch
):
    store = binding.BindingStore(tmp_path)
    marker = store.issue("demo", now=NOW)
    monkeypatch.setenv("VARDE_AGENT_ID", "agent-1")
    monkeypatch.delenv("VARDE_HARNESS", raising=False)
    monkeypatch.setenv("VARDE_RUNNER_ENDPOINT", "http://runner")

    assert store.redeem(marker, "one", "claude", "/repo", now=NOW)

    wake = store.list_bindings()[0]["wake_context"]
    assert isinstance(wake, dict)
    assert wake["harness"] == "claude"
    assert "agent_id" not in wake
    assert "runner_endpoint" not in wake


def test_paseo_only_refresh_overwrites_wake_harness(tmp_path, monkeypatch):
    store = binding.BindingStore(tmp_path)
    marker = store.issue("demo", now=NOW)
    assert store.redeem(marker, "one", "claude", "/repo", now=NOW)
    assert store.refresh_current(
        "claude", "one", "/new", "paseo-1", NOW + timedelta(seconds=1)
    )

    refreshed = store.list_bindings()[0]["wake_context"]
    assert isinstance(refreshed, dict)
    assert refreshed["harness"] == "claude"


def test_refresh_agent_id_without_runner_harness_drops_native_identity(
    tmp_path, monkeypatch
):
    store = binding.BindingStore(tmp_path)
    marker = store.issue("demo", now=NOW)
    monkeypatch.setenv("VARDE_AGENT_ID", "agent-1")
    monkeypatch.setenv("VARDE_HARNESS", "claude-cli")
    assert store.redeem(marker, "one", "claude", "/repo", now=NOW)
    monkeypatch.setenv("VARDE_AGENT_ID", "agent-2")
    monkeypatch.delenv("VARDE_HARNESS", raising=False)

    assert store.refresh_current(
        "claude",
        "one",
        "/new",
        None,
        NOW + timedelta(seconds=1),
        agent_id="agent-2",
        runner_harness=None,
        runner_endpoint="http://runner",
    )

    wake = store.list_bindings()[0]["wake_context"]
    assert isinstance(wake, dict)
    assert wake["harness"] == "claude"
    assert "agent_id" not in wake
    assert "runner_endpoint" not in wake


def _paseo_id(store: binding.BindingStore) -> object:
    wake = store.list_bindings()[0]["wake_context"]
    assert isinstance(wake, dict)
    return wake["paseo_id"]
