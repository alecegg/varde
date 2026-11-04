"""Governor rules (pure) and BotControl: caps, loops, pause, kill, stop of agents."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from varde_data.bot import open_bot
from varde_runner.bot_audit import BotAudit
from varde_runner.bot_control import BotControl, ControlError
from varde_runner.bot_governor import (
    Caps,
    Usage,
    bot_rooted,
    check_caps,
    detect_loop,
    load_caps,
    reported_tokens,
    session_tokens_today,
)
from varde_runner.bot_route_policy import Classified, allow
from varde_runner.bot_tokens import BOT_ACTOR, BotIdentity, BotTokens
from varde_runner.clients import WriterLeases

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=UTC)
LAUNCH = Classified("POST /api/agents", allow("launch"), {})
STOP = Classified("POST /api/agents/{id:str}/stop", allow("agent_action"), {"id": "x"})
IDENTITY = BotIdentity(BOT_ACTOR, "bot-session")


def usage(**fields) -> Usage:
    base = {"bot_live": 0, "all_live": 0, "max_live_instances": 8, "tokens_today": 0}
    return Usage(**{**base, **fields})


def row(repo, ago: timedelta = timedelta(0), clock=None, **fields):
    fields = {
        "phase": "call",
        "action": "launch",
        "route": "r",
        "args_digest": "d",
        "redacted_args": "{}",
        "actor": BOT_ACTOR,
        "status": "allowed",
        **fields,
    }
    saved = repo._clock
    repo._clock = lambda: (NOW - ago).isoformat().replace("+00:00", "Z")
    try:
        return repo.append_audit(**fields)
    finally:
        repo._clock = saved


# --- pure rules ---------------------------------------------------------------


def test_an_exhausted_budget_pauses_even_when_another_cap_is_also_hit() -> None:
    caps = Caps(daily_token_budget=100)
    breach = check_caps(
        caps,
        "launch",
        usage(all_live=8, max_live_instances=8, tokens_today=100),
        [],
        NOW,
    )
    assert breach is not None and breach.status == 423
    assert breach.pause and breach.stop_agents == caps.stop_agents_on_stop
    assert "daily_token_budget" in breach.reason


def test_caps_instance_cap_is_checked_first_and_names_itself(tmp_path) -> None:
    breach = check_caps(Caps(), "launch", usage(all_live=8, bot_live=4), [], NOW)
    assert breach is not None and breach.status == 429
    assert "max_live_instances" in breach.reason


def test_caps_concurrent_agents_count_descendants(tmp_path) -> None:
    sessions = [
        {"id": "a", "launched_by": BOT_ACTOR, "lifecycle": "idle"},
        {"id": "b", "parent_id": "a", "lifecycle": "running"},
        {"id": "c", "parent_id": "b", "lifecycle": "running"},
        {"id": "d", "parent_id": "c", "lifecycle": "completed"},
        {"id": "e", "launched_by": "user", "lifecycle": "running"},
    ]
    rooted = bot_rooted(sessions)
    assert {r["id"] for r in rooted} == {"a", "b", "c", "d"}
    live = sum(r["lifecycle"] != "completed" for r in rooted)
    breach = check_caps(
        Caps(max_concurrent_agents=3), "launch", usage(bot_live=live), [], NOW
    )
    assert breach is not None and "max_concurrent_agents" in breach.reason


def test_manager_root_usage_is_included_in_daily_budget(tmp_path) -> None:
    manager = session(
        "manager-root",
        role="manager-bot",
        launched_by=None,
        usage=[{"usage": {"total_tokens": 100}}],
    )
    control, supervisor, *_ = make_control(
        tmp_path, [manager], caps=Caps(daily_token_budget=100)
    )
    supervisor.store.recent_usage_payloads = lambda session_id, limit=5: manager[
        "usage"
    ]

    refusal = asyncio.run(control.governor(IDENTITY, STOP, {}))

    assert refusal is not None and refusal.status == 423
    assert "daily_token_budget" in refusal.reason
    assert [sid for sid, _ in supervisor.stopped] == ["manager-root"]


def test_manager_root_usage_triggers_daily_budget_warning(tmp_path) -> None:
    manager = session(
        "manager-root",
        role="manager-bot",
        launched_by=None,
        usage=[{"usage": {"total_tokens": 80}}],
    )
    control, supervisor, repo, *_ = make_control(
        tmp_path, [manager], caps=Caps(daily_token_budget=100)
    )
    supervisor.store.recent_usage_payloads = lambda session_id, limit=5: manager[
        "usage"
    ]

    assert asyncio.run(control.governor(IDENTITY, STOP, {})) is None

    warned = repo.get_state("budget_warned")
    assert warned is not None and warned.state == NOW.date().isoformat()


def test_manager_root_without_usage_is_estimated_and_counted(tmp_path) -> None:
    manager = session(
        "manager-root",
        role="manager-bot",
        launched_by=None,
        created_at=(NOW - timedelta(hours=2)).isoformat(),
    )
    control, supervisor, *_ = make_control(
        tmp_path,
        [manager],
        caps=Caps(daily_token_budget=1000, hourly_token_estimate=1000),
    )
    supervisor.store.recent_usage_payloads = lambda session_id, limit=5: []

    refusal = asyncio.run(control.governor(IDENTITY, STOP, {}))

    assert refusal is not None and refusal.status == 423
    assert "daily_token_budget" in refusal.reason
    assert [sid for sid, _ in supervisor.stopped] == ["manager-root"]


def test_caps_launches_per_hour_uses_the_fake_clock(tmp_path) -> None:
    repo = open_bot(tmp_path)
    for minutes in (5, 20, 61):
        row(repo, timedelta(minutes=minutes))
    rows = repo.audit_since("2026-10-26T00:00:00Z", BOT_ACTOR)
    caps = Caps(max_launches_per_hour=3)
    # the launch 61 minutes ago is outside the window
    assert check_caps(caps, "launch", usage(), rows, NOW) is None
    row(repo, timedelta(minutes=1))
    rows = repo.audit_since("2026-10-26T00:00:00Z", BOT_ACTOR)
    breach = check_caps(caps, "launch", usage(), rows, NOW)
    assert breach is not None and "max_launches_per_hour" in breach.reason


def test_caps_actions_per_minute_ignore_reads_and_permissions(tmp_path) -> None:
    repo = open_bot(tmp_path)
    row(repo, action="agent_stop")
    row(repo, action="GET /api/queue", status="read")
    row(repo, action="permission")
    rows = repo.audit_since("2026-10-26T00:00:00Z", BOT_ACTOR)
    caps = Caps(max_actions_per_minute=2)
    assert check_caps(caps, "agent_stop", usage(), rows, NOW) is None
    row(repo, action="agent_prompt")
    rows = repo.audit_since("2026-10-26T00:00:00Z", BOT_ACTOR)
    breach = check_caps(caps, "agent_stop", usage(), rows, NOW)
    assert breach is not None and "max_actions_per_minute" in breach.reason


def test_budget_at_100_percent_pauses_and_stops_agents() -> None:
    breach = check_caps(
        Caps(daily_token_budget=100), "agent_stop", usage(tokens_today=100), [], NOW
    )
    assert breach is not None and breach.pause and breach.stop_agents


def test_estimate_counts_hours_run_today_for_agents_without_tokens() -> None:
    start = NOW - timedelta(hours=2)
    assert session_tokens_today(start, None, None, NOW, 1000) == 2000
    midnight_start = NOW - timedelta(days=3)
    assert session_tokens_today(midnight_start, None, None, NOW, 1000) == 12000
    assert session_tokens_today(start, None, 777, NOW, 1000) == 777


def test_reported_tokens_reads_codex_and_flat_usage_events() -> None:
    payloads = [
        {"usage": {"total": {"total_tokens": 10}}},
        {"usage": {"total_tokens": 25}},
        {"limit": {}},
        {"usage": "unknown"},
    ]
    assert reported_tokens(payloads) == 25
    assert reported_tokens([{"usage": "unknown"}]) is None


def test_load_caps_reads_the_bot_section_and_ignores_bad_values(tmp_path) -> None:
    path = tmp_path / "runner.toml"
    path.write_text("[bot]\nmax_launches_per_hour = 2\ndaily_token_budget = 'x'\n")
    caps = load_caps(path)
    assert caps.max_launches_per_hour == 2
    assert caps.daily_token_budget == Caps().daily_token_budget
    assert load_caps(tmp_path / "missing.toml") == Caps()


def test_loop_same_action_and_arguments_three_times_in_ten_minutes(tmp_path) -> None:
    repo = open_bot(tmp_path)
    for minutes in (1, 3):
        row(repo, timedelta(minutes=minutes), action="agent_prompt", args_digest="x")
    assert detect_loop(repo.audit_since("2026-10-26T00:00:00Z"), NOW) is None
    row(repo, timedelta(minutes=2), action="agent_prompt", args_digest="x")
    reason = detect_loop(repo.audit_since("2026-10-26T00:00:00Z"), NOW)
    assert reason is not None and "agent_prompt repeated 3" in reason


def test_loop_repeated_reads_are_not_a_loop(tmp_path) -> None:
    repo = open_bot(tmp_path)
    for minutes in range(5):
        row(repo, timedelta(minutes=minutes), status="read", args_digest="x")
    assert detect_loop(repo.audit_since("2026-10-26T00:00:00Z"), NOW) is None


def launched(repo, agent_id: str, minutes: int, plan: str = "p1") -> None:
    row(
        repo,
        timedelta(minutes=minutes),
        phase="result",
        status="ok",
        agent_id=agent_id,
        redacted_args=json.dumps({"address": {"plan": plan}}),
        args_digest=f"l-{agent_id}",
    )


def stopped(repo, agent_id: str, minutes: int) -> None:
    row(
        repo,
        timedelta(minutes=minutes),
        action="agent_stop",
        agent_id=agent_id,
        args_digest=f"s-{agent_id}",
    )


def loop_reason(repo) -> str | None:
    return detect_loop(repo.audit_since("2026-10-26T00:00:00Z"), NOW)


def test_loop_two_launch_stop_cycles_on_one_plan(tmp_path) -> None:
    repo = open_bot(tmp_path)
    for n, minutes in enumerate((25, 20)):
        launched(repo, f"a{n}", minutes)
        stopped(repo, f"a{n}", minutes - 1)
    reason = loop_reason(repo)
    assert reason is not None and "plan p1" in reason


def test_loop_counts_two_outstanding_launches_stopped_later(tmp_path) -> None:
    repo = open_bot(tmp_path)
    launched(repo, "a1", 25)
    launched(repo, "a2", 24)
    stopped(repo, "a1", 20)
    stopped(repo, "a2", 19)
    reason = loop_reason(repo)
    assert reason is not None and "2 launch and stop cycles on plan p1" in reason


def test_loop_ignores_a_stop_of_an_agent_the_bot_did_not_launch(tmp_path) -> None:
    repo = open_bot(tmp_path)
    launched(repo, "a1", 25)
    launched(repo, "a2", 24)
    stopped(repo, "a1", 20)
    stopped(repo, "unrelated", 19)
    assert loop_reason(repo) is None


def test_loop_twenty_refused_calls_in_five_minutes(tmp_path) -> None:
    repo = open_bot(tmp_path)
    for n in range(19):
        row(repo, timedelta(minutes=1), status="denied", args_digest=str(n))
    assert detect_loop(repo.audit_since("2026-10-26T00:00:00Z"), NOW) is None
    row(repo, timedelta(minutes=1), status="denied", action="permission")
    reason = detect_loop(repo.audit_since("2026-10-26T00:00:00Z"), NOW)
    assert reason is not None and "20 refused" in reason


# --- control ------------------------------------------------------------------


class FakeStore:
    def __init__(self, sessions) -> None:
        self.rows = sessions

    def sessions(self):
        return self.rows

    def recent_usage_payloads(self, session_id, limit=5):
        return []


class FakeSupervisor:
    def __init__(self, sessions) -> None:
        self.store = FakeStore(sessions)
        self.writer_leases = WriterLeases()
        self.stopped: list[tuple[str, str]] = []
        self.interrupted: list[str] = []

    def max_live_instances(self) -> int:
        return 8

    async def stop(self, agent_id, client_id) -> None:
        self.stopped.append((agent_id, client_id))
        for r in self.store.rows:
            if r["id"] == agent_id:
                r["lifecycle"] = "completed"

    async def interrupt(self, agent_id, client_id) -> None:
        self.interrupted.append(agent_id)


def session(sid, **fields):
    return {
        "id": sid,
        "lifecycle": "running",
        "created_at": NOW.isoformat(),
        "updated_at": NOW.isoformat(),
        **fields,
    }


def make_control(tmp_path, sessions, caps=None, mailbox=None):
    repo = open_bot(tmp_path)
    supervisor = FakeSupervisor(sessions)
    tokens = BotTokens()

    async def get():
        return supervisor

    control = BotControl(
        repo=repo,
        tokens=tokens,
        audit=BotAudit(repo),
        supervisor=get,
        caps=lambda: caps or Caps(),
        raise_mailbox=mailbox,
        clock=lambda: NOW,
    )
    return control, supervisor, repo, tokens


def bot_sessions(count):
    return [
        session(f"a{n}", launched_by=BOT_ACTOR, lifecycle="running")
        for n in range(count)
    ]


def test_concurrent_launches_at_three_of_four_let_exactly_one_through(tmp_path) -> None:
    control, *_ = make_control(tmp_path, bot_sessions(3))

    async def go():
        return await asyncio.gather(
            control.governor(IDENTITY, LAUNCH, {}),
            control.governor(IDENTITY, LAUNCH, {}),
        )

    results = asyncio.run(go())
    assert sorted(r is None for r in results) == [False, True]
    refusal = next(r for r in results if r is not None)
    assert refusal.status == 429 and "max_concurrent_agents" in refusal.reason


def test_the_reserved_slot_frees_when_the_launch_finishes(tmp_path) -> None:
    control, *_ = make_control(tmp_path, bot_sessions(3))
    assert asyncio.run(control.governor(IDENTITY, LAUNCH, {})) is None
    refusal = asyncio.run(control.governor(IDENTITY, LAUNCH, {}))
    assert refusal is not None
    control.release(LAUNCH)
    # the finished launch now shows as a live session, so use the store to model it
    assert control._reserved == 0


def test_the_runner_wide_instance_cap_applies_to_a_launch(tmp_path) -> None:
    others = [session(f"u{n}", launched_by="user") for n in range(8)]
    control, *_ = make_control(tmp_path, others)
    refusal = asyncio.run(control.governor(IDENTITY, LAUNCH, {}))
    assert refusal is not None and "max_live_instances" in refusal.reason


def test_a_loop_pauses_the_bot_raises_a_mailbox_item_and_blocks_writes(
    tmp_path,
) -> None:
    raised: list[str] = []

    async def mailbox(reason):
        raised.append(reason)

    control, _, repo, _ = make_control(tmp_path, [], mailbox=mailbox)
    for minutes in (1, 2, 3):
        row(repo, timedelta(minutes=minutes), action="agent_prompt", args_digest="x")
    refusal = asyncio.run(control.governor(IDENTITY, STOP, {}))
    assert refusal is not None and refusal.status == 423
    assert control.run_state() == "paused" and len(raised) == 1
    state = repo.get_state("run")
    assert state is not None and state.changed_by == "system:governor"


def test_mailbox_resume_uses_the_same_handler_as_the_control_route(tmp_path) -> None:
    control, *_ = make_control(tmp_path, [])
    asyncio.run(control.pause("loop", "system:governor"))
    asyncio.run(control.resume("user"))
    assert control.run_state() == "running"


def test_pause_and_kill_persist_across_a_restart(tmp_path) -> None:
    control, *_ = make_control(tmp_path, [])
    asyncio.run(control.pause("by user", "user"))
    restarted, *_ = make_control(tmp_path, [])
    assert restarted.run_state() == "paused"
    asyncio.run(restarted.kill("user"))
    again, *_ = make_control(tmp_path, [])
    assert again.run_state() == "killed"
    with pytest.raises(ControlError) as excinfo:
        asyncio.run(again.resume("user"))
    assert excinfo.value.status == 409
    again.new_generation("user")
    assert again.run_state() == "running"


def test_kill_revokes_the_token_stops_bot_rooted_agents_and_releases_leases(
    tmp_path,
) -> None:
    sessions = [
        session("manager", role="manager-bot"),
        session("w1", launched_by=BOT_ACTOR),
        session("w2", parent_id="w1"),
        session("user-agent", launched_by="user"),
    ]
    control, supervisor, _, tokens = make_control(tmp_path, sessions)
    token = tokens.issue("manager")
    supervisor.writer_leases.acquire("w1", "bot:manager")
    asyncio.run(control.kill("user"))
    stopped = {sid for sid, _ in supervisor.stopped}
    assert stopped == {"manager", "w1", "w2"}
    assert tokens.resolve(token) is None
    assert supervisor.writer_leases.holder("w1") is None


def test_stop_agents_on_stop_false_leaves_bot_agents_running(tmp_path) -> None:
    sessions = [session("w1", launched_by=BOT_ACTOR)]
    control, supervisor, *_ = make_control(
        tmp_path, sessions, caps=Caps(stop_agents_on_stop=False)
    )
    asyncio.run(control.kill("user"))
    assert supervisor.stopped == []


def test_budget_at_100_percent_pauses_and_stops_bot_agents(tmp_path) -> None:
    sessions = [
        session(
            "w1",
            launched_by=BOT_ACTOR,
            created_at=(NOW - timedelta(hours=2)).isoformat(),
        )
    ]
    control, supervisor, *_ = make_control(
        tmp_path,
        sessions,
        caps=Caps(daily_token_budget=1000, hourly_token_estimate=1000),
    )
    refusal = asyncio.run(control.governor(IDENTITY, STOP, {}))
    assert refusal is not None and refusal.status == 423
    assert control.run_state() == "paused"
    assert [sid for sid, _ in supervisor.stopped] == ["w1"]


def test_a_user_interrupt_takes_the_lease_from_a_bot_holder() -> None:
    leases = WriterLeases()
    leases.acquire("s1", "bot:manager")
    leases.preempt_bot("s1", "tab-1")
    assert leases.holder("s1") is None
    leases.acquire("s1", "tab-2")
    leases.preempt_bot("s1", "bot:manager")
    assert leases.holder("s1") == "tab-2"


def test_snapshot_reports_state_and_usage(tmp_path) -> None:
    control, *_ = make_control(tmp_path, bot_sessions(2))
    snap = asyncio.run(control.snapshot())
    assert snap["state"] == "running" and snap["agents"] == 2
    assert snap["max_concurrent_agents"] == 4


# --- routes through the real app ------------------------------------------------

LOCAL = {"host": "127.0.0.1:8765", "origin": "http://127.0.0.1:8765"}


@pytest.fixture
def app(tmp_path):
    from varde_runner.web.app import create_app

    return create_app(data_dir=tmp_path / "data", bound_port=8765)


def test_the_bot_reads_its_state_but_cannot_change_it(app) -> None:
    from bot_helpers import call
    from varde_runner.bot_tokens import TOKEN_HEADER

    headers = {**LOCAL, TOKEN_HEADER: app.state.bot_tokens.issue("bot-session")}
    status, state = asyncio.run(call(app, "GET", "/api/bot/state", None, headers))
    assert status == 200 and state["state"] == "running"
    status, body = asyncio.run(
        call(app, "POST", "/api/bot/control", {"action": "resume"}, headers)
    )
    assert status == 403 and "user only" in body["error"]


def test_a_user_pause_makes_bot_writes_423_and_a_user_resume_restores_them(
    app,
) -> None:
    from bot_helpers import call
    from varde_runner.bot_tokens import TOKEN_HEADER

    headers = {**LOCAL, TOKEN_HEADER: app.state.bot_tokens.issue("bot-session")}
    status, state = asyncio.run(
        call(app, "POST", "/api/bot/control", {"action": "pause"}, LOCAL)
    )
    assert status == 200 and state["state"] == "paused"
    status, _ = asyncio.run(
        call(app, "POST", "/api/work-items", {"text": "t"}, headers)
    )
    assert status == 423
    status, state = asyncio.run(
        call(app, "POST", "/api/bot/control", {"action": "resume"}, LOCAL)
    )
    assert state["state"] == "running"


def test_kill_through_the_route_blocks_writes_and_resume_gives_409(app) -> None:
    from bot_helpers import call
    from varde_runner.bot_tokens import TOKEN_HEADER

    headers = {**LOCAL, TOKEN_HEADER: app.state.bot_tokens.issue("bot-session")}
    status, state = asyncio.run(
        call(app, "POST", "/api/bot/control", {"action": "kill"}, LOCAL)
    )
    assert status == 200 and state["state"] == "killed"
    status, _ = asyncio.run(
        call(app, "POST", "/api/work-items", {"text": "t"}, headers)
    )
    assert status == 423
    status, _ = asyncio.run(
        call(app, "POST", "/api/bot/control", {"action": "resume"}, LOCAL)
    )
    assert status == 409


def test_an_unknown_control_action_is_rejected(app) -> None:
    from bot_helpers import call

    status, _ = asyncio.run(
        call(app, "POST", "/api/bot/control", {"action": "explode"}, LOCAL)
    )
    assert status == 400


def test_manager_audit_failure_releases_governor_reservation(app, monkeypatch) -> None:
    audit = app.state.bot_audit

    def fail_record(*_args, **_kwargs):
        raise OSError("audit store unavailable")

    monkeypatch.setattr(audit, "record", fail_record)

    async def scenario():
        try:
            await app.state.manager_lifecycle.hooks.launch("manager prompt")
        except OSError:
            pass
        else:
            raise AssertionError("manager launch should fail closed on audit error")
        assert app.state.bot_control._reserved == 0
        assert await app.state.bot_control.governor(IDENTITY, LAUNCH, {}) is None
        app.state.bot_control.release(LAUNCH)

    asyncio.run(scenario())


def test_a_paused_bot_gets_no_chat_delivery_until_resumed(tmp_path) -> None:
    from test_chat_api import FakeSupervisor, get_supervisor
    from varde_data.chat import open_chat
    from varde_runner.chat_delivery import ChatDelivery
    from varde_runner.supervisor import SendOutcome

    async def run() -> None:
        chat = open_chat(tmp_path)
        message = chat.append_user("main", "m-1", "hello")
        chat.set_chat_bot("main", "manager", "now", None, "running", 1)
        supervisor = FakeSupervisor([SendOutcome.SENT])
        paused = {"value": True}
        delivery = ChatDelivery(
            chat,
            lambda: get_supervisor(supervisor),
            retry_seconds=0.001,
            bot_paused=lambda: paused["value"],
        )
        await delivery.accept(message)
        await asyncio.sleep(0.05)
        assert supervisor.calls == []
        paused["value"] = False
        for _ in range(100):
            if supervisor.calls:
                break
            await asyncio.sleep(0.002)
        assert [call[1] for call in supervisor.calls] == ["hello"]
        await delivery.close()

    asyncio.run(run())
