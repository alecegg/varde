#!/usr/bin/env python3
"""Exercise relay behavior with fakes or an explicitly requested live run."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import uuid
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from varde_runner.plugins import SessionRef, SessionSpec
from varde_runner.plugins.paseo import PaseoPlugin
from varde_runner.relay import RelayCLI, RelayWorker
from varde_runner.relay_e2e import (
    agent_created_leftovers,
    fake_restart_drill,
    format_report,
    grep_e2e_leaks,
    temp_store_path,
    wait_for_predicate,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_TIMEOUT = 60


class FakeCLI:
    async def status(self) -> dict[str, Any]:
        return {"mailmen": []}

    async def bindings(self) -> list[dict[str, Any]]:
        return []

    async def issue_and_bind(self, _session: str) -> str:
        return "fake-mailman"

    async def issue_and_bind_superseding(self, _session: str) -> str:
        return "fake-mailman"

    async def wait(self, _identity: str) -> dict[str, Any]:
        return {"actions": []}

    async def confirm(self, *_args: Any, harness: str) -> None:
        return None

    async def renew(self, _action: str) -> dict[str, str]:
        return {"status": "renewed"}

    async def end(self, _identity: str) -> None:
        return None

    async def unbind(self, _session: str) -> None:
        return None


class FakePlugin:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def idle_status(self, _agent: str) -> str:
        return "idle"

    async def send(self, agent: str, prompt: str) -> None:
        self.sent.append((agent, prompt))


class FakeLivePlugin:
    async def inspect(self, _ref: SessionRef) -> dict[str, Any]:
        return {"status": "idle", "archived": False}

    async def send(self, _ref: SessionRef, _prompt: str) -> None:
        return None

    async def close(self) -> None:
        return None


class RecordingWorker(RelayWorker):
    def __init__(self, cli: RelayCLI, plugin: Any) -> None:
        super().__init__(cli, plugin)
        self.outcomes: list[tuple[list[str], str]] = []
        self.responses: list[str | None] = []

    async def _process_response(self, response: dict[str, Any]) -> bool:
        self.responses.append(response.get("status"))
        return await super()._process_response(response)

    def _record_confirmation(
        self, action: dict[str, Any], action_id: str, result: str
    ) -> None:
        super()._record_confirmation(action, action_id, result)
        self.outcomes.append((list(action.get("message_ids", [])), result))
        outcome_path = os.environ.get("VARDE_E2E_OUTCOMES")
        if outcome_path:
            with Path(outcome_path).open("a", encoding="utf-8") as stream:
                stream.write(
                    json.dumps(
                        {
                            "action_id": action_id,
                            "message_ids": list(action.get("message_ids", [])),
                            "result": result,
                        }
                    )
                    + "\n"
                )


def dry_run() -> str:
    checks = {"fake mode keeps real services unused": asyncio.run(_fake_exercise())}
    checks.update(fake_restart_drill())
    return format_report(checks, cleaned=True, leaks=[])


async def _fake_exercise() -> bool:
    plugin = FakePlugin()
    worker = RelayWorker(FakeCLI(), plugin)
    await worker._handle(
        {
            "action_id": "e2e-fake",
            "wake": {"paseo_id": "e2e-agent"},
            "prompt": "e2e-prompt",
            "message_ids": ["e2e-message"],
        }
    )
    return plugin.sent == [("e2e-agent", "e2e-prompt")]


def _run_varde(working: Path, *args: str) -> str:
    env = {**os.environ, "VARDE_WORKING_DIR": str(working)}
    result = subprocess.run(
        ["varde", *args],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=LIVE_TIMEOUT,
    )
    return result.stdout.strip()


def _real_inbox() -> Path:
    result = subprocess.run(
        ["varde", "setup", "paths", "--json"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
        timeout=LIVE_TIMEOUT,
    )
    paths = json.loads(result.stdout)
    working = Path(paths.get("data", paths)["working"]).expanduser().resolve()
    return working / ".cache" / "inbox"


async def _bounded(awaitable: Any, *, timeout: float = LIVE_TIMEOUT) -> Any:
    return await asyncio.wait_for(awaitable, timeout=timeout)


def _bind_live_nonrunner(working: Path) -> tuple[str, bytes | None]:
    session_id = f"e2e-live-holder-{uuid.uuid4().hex}"
    marker = _run_varde(working, "msg", "address", "new", "mailman", "--supersede")
    env = {**os.environ, "VARDE_WORKING_DIR": str(working)}
    subprocess.run(
        [
            "varde",
            "msg",
            "address",
            "bind",
            marker,
            "--harness",
            "codex",
            "--session",
            session_id,
        ],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=LIVE_TIMEOUT,
    )
    bindings = json.loads(_run_varde(working, "msg", "address", "list", "--json"))[
        "bindings"
    ]
    binding = next(item for item in bindings if item.get("session_id") == session_id)
    token_id = str(binding["token_id"])
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    state_dir = working / ".cache" / "inbox" / "relay"
    state_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_dir / "state.json"
    previous_state = state_path.read_bytes() if state_path.exists() else None
    state_path.write_text(
        json.dumps(
            {
                "current_mailman": token_id,
                "mailman_started": {token_id: now},
                "mailman_instances": {token_id: "e2e-live-holder"},
                "events": [{"event": "waiting", "token_id": token_id, "at": now}],
            }
        ),
        encoding="utf-8",
    )
    return session_id, previous_state


def _restore_live_nonrunner_state(working: Path, previous_state: bytes | None) -> None:
    state_path = working / ".cache" / "inbox" / "relay" / "state.json"
    if previous_state is None:
        state_path.unlink(missing_ok=True)
    else:
        state_path.write_bytes(previous_state)


def _issue_recipient(working: Path, name: str, agent_id: str) -> None:
    marker = _run_varde(working, "msg", "address", "new", name)
    env = {**os.environ, "VARDE_WORKING_DIR": str(working), "PASEO_AGENT_ID": agent_id}
    subprocess.run(
        [
            "varde",
            "msg",
            "address",
            "bind",
            marker,
            "--harness",
            "codex",
            "--session",
            f"e2e-{uuid.uuid4().hex}",
        ],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=LIVE_TIMEOUT,
    )


def _send(working: Path, name: str, token: str) -> str:
    _run_varde(
        working,
        "msg",
        "send",
        "--from",
        "e2e-sender",
        "--to",
        name,
        "--kind",
        "info",
        f"{token}: relay check",
    )
    payload = json.loads(_run_varde(working, "msg", "read", "--all", "--json"))
    messages = payload.get("data", payload)["messages"]
    return str(messages[-1]["id"])


def _seed_bad_status(working: Path, token: str) -> bool:
    _run_varde(
        working,
        "msg",
        "send",
        "--from",
        "e2e-sender",
        "--to",
        "e2e-unbound",
        "--kind",
        "info",
        f"{token}: unbound status fixture",
    )
    messages_path = working / ".cache" / "inbox" / "messages.jsonl"
    rows = messages_path.read_text(encoding="utf-8").splitlines()
    if not rows:
        return False
    message = json.loads(rows[-1])
    message["ts"] = "2000-01-01T00:00:00Z"
    rows[-1] = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    messages_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    result = subprocess.run(
        ["varde", "msg", "status", "--json"],
        cwd=REPO_ROOT,
        env={**os.environ, "VARDE_WORKING_DIR": str(working)},
        check=False,
        capture_output=True,
        text=True,
        timeout=LIVE_TIMEOUT,
    )
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False
    data = report.get("data", report)
    return result.returncode == 1 and bool(data.get("unbound_pending"))


async def _wait_for(predicate, *, timeout: float = 180, interval: float = 0.2) -> bool:
    return await wait_for_predicate(predicate, timeout=timeout, interval=interval)


async def live_run(workspace_id: str) -> str:  # noqa: PLR0912, PLR0915
    inbox = _real_inbox()
    token = uuid.uuid4().hex[:12]
    store = temp_store_path(inbox, token)
    temp_root = store.parents[2]
    working = temp_root / "working"
    refs: list[SessionRef] = []
    plugin: PaseoPlugin | None = None
    live_adapter: _LiveAdapter | None = None
    worker: RecordingWorker | None = None
    cli: RelayCLI | None = None
    relay_task: asyncio.Task[None] | None = None
    nonrunner_holder: tuple[str, bytes | None] | None = None
    idle_msg = busy_msg = archived_msg = unknown_msg = ""
    unknown_id = ""
    agents: dict[str, SessionRef] = {}
    cleanup_errors: list[str] = []
    leftovers_removed = 0
    checks = {
        "temp store status exits 1 for unbound pending mail": False,
        "idle -> pushed": False,
        "busy agent became running before send": False,
        "archived recipient -> revived and pushed": False,
        "unknown agent -> target-gone": False,
        "status shows runner relay up": False,
        "overlapping runner takes over and releases safely": False,
        "runner worker stops after supersede": False,
        "live non-runner holder remains bound after refusal": False,
        "restart drill: four deliveries across three process restarts": False,
        "restart drill: graceful stops release address": False,
        "restart drill: crash binding is taken over": False,
        "restart drill: no live-binding refusals": False,
        "restart drill: every worker starts": False,
    }
    try:
        working.mkdir(parents=True)
        os.environ["VARDE_WORKING_DIR"] = str(working)
        plugin = PaseoPlugin.from_environment()
        cli = RelayCLI()
        checks["temp store status exits 1 for unbound pending mail"] = _seed_bad_status(
            working, token
        )
        for name, prompt in (
            ("idle", "Reply with the single word ready."),
            ("archived", "Reply with the single word ready."),
        ):
            ref = await _bounded(
                plugin.start(
                    SessionSpec(
                        provider="codex",
                        model="gpt-6-luna",
                        reasoning_effort="low",
                        workspace_id=workspace_id,
                        cwd=str(REPO_ROOT),
                        prompt=f"Never run varde commands.\n{prompt}",
                    )
                ),
                timeout=120,
            )
            refs.append(ref)
            agents[name] = ref
            _issue_recipient(working, f"e2e-{name}", ref.session_id)

        unknown_id = f"e2e-unknown-{uuid.uuid4().hex}"
        _issue_recipient(working, "e2e-unknown", unknown_id)
        live_adapter = _LiveAdapter(plugin)
        worker = RecordingWorker(cli, live_adapter)
        idle_msg = _send(working, "e2e-idle", token)
        relay_task = asyncio.create_task(worker.run())
        checks["idle -> pushed"] = await _wait_outcome(worker, idle_msg, "pushed")

        busy_ref = await _bounded(
            plugin.start(
                SessionSpec(
                    provider="codex",
                    model="gpt-6-luna",
                    reasoning_effort="low",
                    mode_id="full-access",
                    workspace_id=workspace_id,
                    cwd=str(REPO_ROOT),
                    prompt=(
                        "Never run varde commands.\nRun the shell command "
                        "`sleep 240`, then reply done."
                    ),
                )
            ),
            timeout=120,
        )
        refs.append(busy_ref)
        agents["busy"] = busy_ref
        _issue_recipient(working, "e2e-busy", busy_ref.session_id)
        busy_running = await _wait_running(plugin, busy_ref, timeout=LIVE_TIMEOUT)
        checks["busy agent became running before send"] = busy_running
        if not busy_running:
            print(
                "FAIL agent never became busy within 60s; relay check not run",
                file=sys.stderr,
            )
        if busy_running:
            busy_msg = _send(working, "e2e-busy", token)
            busy_then_pushed = await _wait_outcome(
                worker, busy_msg, "skipped-busy", timeout=240
            )
            if busy_then_pushed:
                busy_then_pushed = await _wait_outcome(
                    worker, busy_msg, "pushed", timeout=600
                )
            checks["running message -> skipped-busy then pushed"] = busy_then_pushed

        archived_ref = agents["archived"]
        await _bounded(plugin.stop(archived_ref), timeout=30)
        archived_before = await _wait_archived(plugin, archived_ref)
        archived_msg = _send(working, "e2e-archived", token)
        archived_pushed = archived_before and await _wait_outcome(
            worker, archived_msg, "pushed", timeout=240
        )
        archived_snapshot = await _bounded(plugin.inspect(archived_ref), timeout=15)
        checks["archived recipient -> revived and pushed"] = (
            archived_pushed and archived_snapshot.get("archived") is False
        )

        unknown_msg = _send(working, "e2e-unknown", token)
        checks["unknown agent -> target-gone"] = await _wait_outcome(
            worker, unknown_msg, "target-gone"
        )

        status = await _bounded(cli.status())
        checks["status shows runner relay up"] = status.get("runner_relay") == "up"
        if worker is None or relay_task is None:
            raise RuntimeError("runner worker did not start")
        takeover_result = await _verify_live_runner_takeover(
            cli, worker, relay_task, plugin
        )
        checks.update(takeover_result)
        checks["overlapping runner takes over and releases safely"] = (
            takeover_result["overlap binding belongs to second runner"]
            and takeover_result["overlap cancellation releases binding"]
        )
        relay_task = None
        nonrunner_holder = _bind_live_nonrunner(working)
        holder_session, previous_relay_state = nonrunner_holder
        checks.update(await _verify_live_nonrunner_refusal(cli, plugin, holder_session))
        _require_live_nonrunner_holder(checks)
        await _bounded(cli.unbind(holder_session))
        _restore_live_nonrunner_state(working, previous_relay_state)
        nonrunner_holder = None
        restart_checks = await _live_restart_drill(working, token)
        checks.update(restart_checks)
    finally:
        if worker is not None:
            try:
                await _bounded(
                    _print_failed_diagnostics(
                        worker,
                        plugin,
                        {
                            "idle -> pushed": (idle_msg, agents.get("idle")),
                            "running message -> skipped-busy then pushed": (
                                busy_msg,
                                agents.get("busy"),
                            ),
                            "busy agent became running before send": (
                                "",
                                agents.get("busy"),
                            ),
                            "archived recipient -> revived and pushed": (
                                archived_msg,
                                agents.get("archived"),
                            ),
                            "unknown agent -> target-gone": (
                                unknown_msg,
                                SessionRef("paseo", unknown_id) if unknown_id else None,
                            ),
                        },
                        checks,
                        live_adapter,
                    ),
                    timeout=15,
                )
            except TimeoutError:
                cleanup_errors.append("diagnostics timed out")
        if relay_task is not None:
            relay_task.cancel()
            try:
                await _bounded(relay_task, timeout=15)
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # noqa: BLE001
                cleanup_errors.append(str(exc))
        if nonrunner_holder and cli is not None:
            holder_session, previous_relay_state = nonrunner_holder
            try:
                await _bounded(cli.unbind(holder_session))
            except Exception as exc:  # noqa: BLE001
                cleanup_errors.append(str(exc))
            try:
                _restore_live_nonrunner_state(working, previous_relay_state)
            except OSError as exc:
                cleanup_errors.append(str(exc))
        if plugin is not None:
            for ref in refs:
                try:
                    await _bounded(plugin.stop(ref), timeout=30)
                except Exception as exc:  # noqa: BLE001
                    cleanup_errors.append(str(exc))
            try:
                await _bounded(plugin.close(), timeout=15)
            except Exception as exc:  # noqa: BLE001
                cleanup_errors.append(str(exc))
        shutil.rmtree(temp_root, ignore_errors=True)
        leftovers = agent_created_leftovers(inbox)
        for path in leftovers:
            path.unlink()
            leftovers_removed += 1
    leaks = grep_e2e_leaks(inbox, token)
    checks["cleanup completed"] = not cleanup_errors
    report = format_report(checks, cleaned=not temp_root.exists(), leaks=leaks)
    return f"{report}\nNOTE agent-created leftovers removed: {leftovers_removed}"


async def _verify_live_nonrunner_refusal(
    cli: RelayCLI,
    plugin: Any,
    holder_session: str,
) -> dict[str, bool]:
    second = RelayWorker(cli, _LiveAdapter(plugin))
    second_task = asyncio.create_task(second.run())
    try:
        await _bounded(second_task, timeout=LIVE_TIMEOUT)
        bindings = await _bounded(cli.bindings())
        return {
            "live non-runner holder remains bound after refusal": (
                second.state == "refused"
                and any(
                    item.get("session_id") == holder_session
                    and item.get("address") == "mailman"
                    for item in bindings
                )
            )
        }
    finally:
        if not second_task.done():
            second_task.cancel()
            with suppress(asyncio.CancelledError, TimeoutError):
                await _bounded(second_task, timeout=15)


async def _verify_live_runner_takeover(
    cli: RelayCLI,
    first: RecordingWorker,
    first_task: asyncio.Task[None],
    plugin: Any,
) -> dict[str, bool]:
    second = RecordingWorker(cli, _LiveAdapter(plugin))
    second_task = asyncio.create_task(second.run())
    try:
        await _bounded(first_task, timeout=LIVE_TIMEOUT)
        bindings = await _bounded(cli.bindings())
        second_session = second.session_id
        first_superseded = first.state == "stopped" and "superseded" in first.responses
        second_owns_binding = (
            second.state in {"starting", "waiting", "delivering"}
            and second_session is not None
            and any(
                item.get("address") == "mailman"
                and item.get("session_id") == second_session
                for item in bindings
            )
        )
        if any(
            item.get("address") == "mailman"
            and item.get("session_id") != second_session
            for item in bindings
        ):
            second_owns_binding = False
        if not first_superseded or not second_owns_binding:
            print(
                "DIAGNOSTIC runner takeover: "
                f"first.state={first.state!r} "
                f"first_superseded={'superseded' in first.responses!r} "
                f"second.state={second.state!r} "
                f"second_owns_binding={second_owns_binding!r} "
                f"second.session_id={second_session!r} bindings={bindings!r}",
                file=sys.stderr,
            )
        second_task.cancel()
        with suppress(asyncio.CancelledError):
            await _bounded(second_task, timeout=15)
        released = await _wait_for(
            lambda: _no_mailman_binding(cli), timeout=LIVE_TIMEOUT
        )
        return {
            "runner worker stops after supersede": first_superseded,
            "overlap binding belongs to second runner": second_owns_binding,
            "overlap cancellation releases binding": released,
        }
    finally:
        if not first_task.done():
            first_task.cancel()
            with suppress(asyncio.CancelledError, TimeoutError):
                await _bounded(first_task, timeout=15)
        if not second_task.done():
            second_task.cancel()
            with suppress(asyncio.CancelledError, TimeoutError):
                await _bounded(second_task, timeout=15)


def _require_live_nonrunner_holder(checks: dict[str, bool]) -> None:
    if not checks["live non-runner holder remains bound after refusal"]:
        raise RuntimeError("live non-runner holder was not retained after refusal")


async def _wait_outcome(
    worker: RecordingWorker, message_id: str, result: str, *, timeout: float = 180
) -> bool:
    return await _wait_for(
        lambda: any(
            message_id in message_ids and outcome == result
            for message_ids, outcome in worker.outcomes
        ),
        timeout=timeout,
    )


async def _service_worker_main(*, fake_plugin: bool = False) -> None:
    plugin = FakeLivePlugin() if fake_plugin else PaseoPlugin.from_environment()
    worker = RecordingWorker(RelayCLI(), _LiveAdapter(plugin))
    task = asyncio.create_task(worker.run())
    loop = asyncio.get_running_loop()

    def stop_worker() -> None:
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(signum)
        task.cancel()

    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, stop_worker)
    try:
        with suppress(asyncio.CancelledError):
            # The service lifetime ends only on an OS signal; the parent process
            # bounds its wait and owns restart supervision.
            await task
    finally:
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(signum)
        await _bounded(plugin.close(), timeout=15)


async def _live_restart_drill(  # noqa: PLR0915
    working: Path, token: str, *, fake_plugin: bool = False
) -> dict[str, bool]:
    cli = RelayCLI(cwd=working)
    outcome_path = working / "restart-outcomes.jsonl"
    worker_log = working / "restart-worker.log"
    child_env = {
        **os.environ,
        "VARDE_WORKING_DIR": str(working),
        "VARDE_E2E_OUTCOMES": str(outcome_path),
    }
    process: asyncio.subprocess.Process | None = None
    delivered = 0
    graceful_released = 0
    takeover_after_crash = False
    no_live_binding_refusals = True

    async def start() -> bool:
        nonlocal process, takeover_after_crash, no_live_binding_refusals
        before = await _bounded(cli.bindings())
        previous_sessions = {
            str(item.get("session_id", ""))
            for item in before
            if item.get("address") == "mailman"
        }
        prior_runner = any(
            item.get("address") == "mailman"
            and str(item.get("session_id", "")).startswith("runner-")
            for item in before
        )
        worker_args = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--service-worker",
        ]
        if fake_plugin:
            worker_args.append("--fake-plugin")
        with worker_log.open("ab") as stderr:
            process = await _bounded(
                asyncio.create_subprocess_exec(
                    *worker_args,
                    cwd=REPO_ROOT,
                    env=child_env,
                    stdout=subprocess.DEVNULL,
                    stderr=stderr,
                ),
                timeout=LIVE_TIMEOUT,
            )
        ready = await _wait_for(
            lambda: process is not None and process.returncode is None,
            timeout=10,
        ) and await _wait_runner_binding(
            cli,
            excluded_sessions=previous_sessions,
            timeout=LIVE_TIMEOUT,
        )
        bindings = await _bounded(cli.bindings())
        owns_binding = any(
            item.get("address") == "mailman"
            and str(item.get("session_id", "")).startswith("runner-")
            for item in bindings
        )
        takeover_after_crash = takeover_after_crash or (prior_runner and owns_binding)
        events = working / ".cache" / "inbox" / "events.jsonl"
        no_live_binding_refusals = no_live_binding_refusals and not (
            events.exists() and '"reason":"live-binding"' in events.read_text()
        )
        return ready and owns_binding and no_live_binding_refusals

    async def deliver(number: int) -> bool:
        nonlocal delivered
        message_id = _send(working, "e2e-idle", f"{token}-restart-{number}")
        ok = await _wait_for(
            lambda: _has_outcome(outcome_path, message_id, "pushed"), timeout=240
        )
        delivered += int(ok)
        return ok

    async def stop(signum: int, *, count_graceful: bool = True) -> bool:
        nonlocal process, graceful_released
        if process is None or process.returncode is not None:
            return False
        if signum == signal.SIGTERM:
            process.send_signal(signal.SIGTERM)
        else:
            process.kill()
        exited = await _wait_for(
            lambda: process is not None and process.returncode is not None,
            timeout=LIVE_TIMEOUT,
        )
        if not exited:
            return False
        if signum != signal.SIGTERM:
            return True
        released = await _wait_for(
            lambda: _no_mailman_binding(cli), timeout=LIVE_TIMEOUT
        )
        graceful_released += int(released and count_graceful)
        return released

    all_started = False
    all_delivered = False
    try:
        all_started = await start()
        all_delivered = True if fake_plugin else await deliver(0)
        for cycle, signum in enumerate(
            (signal.SIGTERM, signal.SIGKILL, signal.SIGTERM), start=1
        ):
            stopped = await stop(signum)
            all_started = (await start()) and all_started
            if not fake_plugin:
                all_delivered = (await deliver(cycle)) and all_delivered
            all_started = stopped and all_started
    finally:
        if process is not None and process.returncode is None:
            await stop(signal.SIGTERM, count_graceful=False)
    checks = {
        "restart drill: graceful stops release address": graceful_released == 2,
        "restart drill: crash binding is taken over": takeover_after_crash,
        "restart drill: no live-binding refusals": no_live_binding_refusals,
        "restart drill: every worker starts": all_started,
    }
    if not fake_plugin:
        checks["restart drill: four deliveries across three process restarts"] = (
            all_delivered and delivered == 4
        )
    return checks


async def _wait_runner_binding(
    cli: RelayCLI, *, excluded_sessions: set[str], timeout: float
) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        bindings = await _bounded(cli.bindings(), timeout=LIVE_TIMEOUT)
        if any(
            item.get("address") == "mailman"
            and str(item.get("session_id", "")).startswith("runner-")
            and str(item.get("session_id")) not in excluded_sessions
            for item in bindings
        ):
            return True
        await asyncio.sleep(0.2)
    return False


async def _no_mailman_binding(cli: RelayCLI) -> bool:
    bindings = await _bounded(cli.bindings(), timeout=LIVE_TIMEOUT)
    return not any(item.get("address") == "mailman" for item in bindings)


def _has_outcome(path: Path, message_id: str, result: str) -> bool:
    if not path.exists():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if message_id in event.get("message_ids", []) and event.get("result") == result:
            return True
    return False


async def _wait_archived(
    plugin: PaseoPlugin, ref: SessionRef, *, timeout: float = 60
) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if (await _bounded(plugin.inspect(ref), timeout=15)).get("archived") is True:
            return True
        await asyncio.sleep(0.2)
    return (await _bounded(plugin.inspect(ref), timeout=15)).get("archived") is True


async def _wait_running(
    plugin: PaseoPlugin, ref: SessionRef, *, timeout: float = 60
) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if (await _bounded(plugin.inspect(ref), timeout=15)).get("status") == "running":
            return True
        await asyncio.sleep(0.2)
    return (await _bounded(plugin.inspect(ref), timeout=15)).get("status") == "running"


async def _print_failed_diagnostics(
    worker: RecordingWorker,
    plugin: PaseoPlugin | None,
    messages: dict[str, tuple[str, SessionRef | None]],
    checks: dict[str, bool],
    live_adapter: _LiveAdapter | None,
) -> None:
    for name, passed in checks.items():
        if passed:
            continue
        message_id, ref = messages.get(name, ("", None))
        outcomes = [outcome for ids, outcome in worker.outcomes if message_id in ids]
        try:
            snapshot = worker.snapshot()
        except Exception as exc:  # noqa: BLE001
            snapshot = {"diagnostic_error": str(exc)}
        agent = None
        if plugin is not None and ref is not None:
            try:
                agent = await _bounded(plugin.inspect(ref), timeout=15)
            except Exception as exc:  # noqa: BLE001
                agent = {"inspect_error": str(exc)}
        print(
            f"DIAGNOSTIC {name}: message={message_id!r} outcomes={outcomes!r} "
            f"failures={snapshot.get('failures')!r} "
            f"last_error={snapshot.get('last_error')!r} "
            f"agent={agent!r}"
            + (
                f" ref={ref.session_id!r} all_status_log={live_adapter.status_log!r}"
                if name
                in {
                    "running message -> skipped-busy then pushed",
                    "busy agent became running before send",
                }
                and live_adapter is not None
                and ref is not None
                else ""
            ),
            file=sys.stderr,
        )


class _LiveAdapter:
    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin
        self.status_log: list[tuple[str, str, bool, float]] = []

    def status_log_for(self, session_id: str) -> list[tuple[str, str, bool, float]]:
        return [entry for entry in self.status_log if entry[0] == session_id]

    async def idle_status(self, session_id: str) -> dict[str, Any]:
        snapshot = await _bounded(
            self.plugin.inspect(SessionRef("paseo", session_id)), timeout=15
        )
        status = snapshot.get("status")
        normalized = (
            status if status in {"idle", "running", "error", "closed"} else "unknown"
        )
        archived = bool(snapshot.get("archived"))
        self.status_log.append((session_id, normalized, archived, time.time()))
        return {"status": normalized, "archived": archived}

    async def send(self, session_id: str, prompt: str) -> None:
        await _bounded(
            self.plugin.send(SessionRef("paseo", session_id), prompt), timeout=45
        )


async def _live_run_with_signal_cleanup(workspace_id: str) -> str:
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    if task is None:
        raise RuntimeError("live e2e requires an asyncio task")

    def cancel_live_run() -> None:
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(signum)
        task.cancel()

    for signum in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(signum, cancel_live_run)
    try:
        return await live_run(workspace_id)
    except asyncio.CancelledError:
        return "FAIL live e2e interrupted; cleanup attempted"
    finally:
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.remove_signal_handler(signum)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--service-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--fake-plugin", action="store_true", help=argparse.SUPPRESS)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run", action="store_true", help="exercise the fake relay path"
    )
    mode.add_argument(
        "--live", action="store_true", help="use the real inbox and Paseo service"
    )
    parser.add_argument(
        "--workspace-id", help="existing Paseo workspace required by --live"
    )
    args = parser.parse_args()
    if args.service_worker:
        asyncio.run(_service_worker_main(fake_plugin=args.fake_plugin))
        return 0
    if not args.dry_run and not args.live:
        parser.error("choose --dry-run or --live")
    if args.live and not args.workspace_id:
        parser.error("--live requires --workspace-id for an existing Paseo workspace")
    report = (
        asyncio.run(_live_run_with_signal_cleanup(args.workspace_id))
        if args.live
        else dry_run()
    )
    print(report)
    return (
        0
        if all(
            line.startswith(("PASS", "NOTE agent-created leftovers removed:"))
            for line in report.splitlines()
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
