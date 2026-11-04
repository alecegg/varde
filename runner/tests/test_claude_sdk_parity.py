from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from textwrap import dedent
from typing import Any
from unittest.mock import patch

import pytest
from varde_runner.config import default_config
from varde_runner.events import RunnerEvent
from varde_runner.plugins import SessionRef, SessionSpec
from varde_runner.plugins.claude_sdk.plugin import ClaudeSdkPlugin
from varde_runner.supervisor import Supervisor

RUNNER_ROOT = Path(__file__).resolve().parents[1]
ENGINE = RUNNER_ROOT / "node-host" / "engines" / "claude-sdk" / "index.mjs"
FAKE_SDK = ENGINE.parent / "test" / "fake-sdk.mjs"


def _node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node 22.19+ is required for the native host parity tests")
    return node


def _plugin(
    tmp_path: Path,
    *,
    idle_timeout: float = 0.5,
    env: dict[str, str] | None = None,
) -> tuple[ClaudeSdkPlugin, Path]:
    log_path = tmp_path / "sdk-log.jsonl"
    state_dir = tmp_path / "plugin-state"
    state_dir.mkdir(exist_ok=True)
    wrapper = tmp_path / "sdk-wrapper.mjs"
    wrapper_source = dedent(
        """\
        import { appendFileSync } from "node:fs";
        import * as sdk from __FAKE_SDK_URL__;
        const log = (row) => appendFileSync(
          process.env.FAKE_SDK_LOG,
          `${JSON.stringify(row)}\\n`,
        );
        export const query = ({ prompt, options }) => {
          log({
            type: "start",
            resume: options.resume ?? null,
            cwd: options.cwd,
          });
          const input = (async function* () {
            for await (const item of prompt) {
              log({ type: "input", text: item.message.content });
              yield item;
            }
          })();
          const query = sdk.query({ prompt: input, options });
          const call = sdk.calls.at(-1);
          call.testIndex = sdk.calls.length - 1;
          const timer = setInterval(() => {
            if (call.grandchild && !call.loggedChild) {
              call.loggedChild = true;
              log({
                type: "child",
                session: call.testIndex,
                grandchild: call.grandchild,
              });
              clearInterval(timer);
            }
          }, 10);
          timer.unref();
          return query;
        };
        """
    ).replace("__FAKE_SDK_URL__", json.dumps(FAKE_SDK.as_uri()))
    wrapper.write_text(wrapper_source, encoding="utf-8")
    host_env = {
        "VARDE_CLAUDE_SDK_MODULE": str(wrapper),
        "FAKE_SDK_LOG": str(log_path),
        **(env or {}),
    }
    settings_text = (
        f"[node_host]\nnode = {json.dumps(_node())}\n"
        "restart_max = 3\nrestart_window_s = 30\ncall_timeout_s = 30\n\n"
        f"[claude_sdk]\nstream_idle_timeout_s = {idle_timeout}\n"
    )
    with patch.dict(os.environ, host_env):
        plugin = ClaudeSdkPlugin(
            state_dir=state_dir,
            settings_text=settings_text,
        )
        plugin._host()
    return plugin, log_path


def _spec(cwd: Path, prompt: str = "") -> SessionSpec:
    return SessionSpec(
        "claude-sdk",
        "fake-model",
        "workspace-1",
        str(cwd),
        prompt,
        mode_id="workspace-write",
        agent_id="agent-1",
    )


async def _next_event(stream, kind: str, timeout: float = 10) -> RunnerEvent:
    async def find() -> RunnerEvent:
        async for event in stream:
            if event.kind == kind:
                return event
        raise AssertionError(f"event stream ended before {kind}")

    return await asyncio.wait_for(find(), timeout)


async def _wait_for(predicate, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("timed out waiting for parity condition")
        await asyncio.sleep(0.02)


def _log_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_real_host_restart_resumes_persisted_handle_and_expires_approval(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        original, log_path = _plugin(tmp_path)
        resumed, _ = _plugin(tmp_path)
        ref: SessionRef | None = None
        original_events = None
        resumed_events = None
        try:
            ref = await original.start(_spec(tmp_path, "perm"))
            original_events = original.events(ref)
            request = await _next_event(original_events, "permission_requested")
            assert request.payload["request_id"] == "tu-perm"
            state_path = original._path(ref.session_id)
            await _wait_for(
                lambda: (
                    json.loads(state_path.read_text()).get("handle")
                    == "fake-sdk-session-1"
                )
            )
            saved = json.loads(state_path.read_text())
            assert saved["handle"] == "fake-sdk-session-1"
            assert saved["pending_approvals"] == ["tu-perm"]

            await original.close()
            resumed_events = resumed.events(ref)
            await resumed.resume(ref)
            expired = await _next_event(resumed_events, "permission_resolved")
            assert expired.payload == {
                "request_id": "tu-perm",
                "decision": "expired",
            }
            assert not resumed._pending.get(ref.session_id)
            await resumed.send(ref, "continue")
            await _next_event(resumed_events, "session_end")

            starts = [row for row in _log_rows(log_path) if row["type"] == "start"]
            assert [row["resume"] for row in starts] == [None, "fake-sdk-session-1"]
            assert all(row["cwd"] == str(tmp_path) for row in starts)
            inputs = [
                row["text"] for row in _log_rows(log_path) if row["type"] == "input"
            ]
            assert inputs == ["perm", "continue"]
        finally:
            await original.close()
            await resumed.close()
            if original_events is not None:
                await original_events.aclose()
            if resumed_events is not None:
                await resumed_events.aclose()

    asyncio.run(exercise())


def test_host_restart_before_handle_starts_fresh(tmp_path: Path) -> None:
    async def exercise() -> None:
        plugin, log_path = _plugin(tmp_path)
        events = None
        try:
            ref = await plugin.start(_spec(tmp_path))
            events = plugin.events(ref)
            host = plugin.host
            assert host is not None and host.pid is not None
            old_pid = host.pid
            assert not plugin._handles.get(ref.session_id)
            os.kill(old_pid, signal.SIGKILL)
            await _wait_for(lambda: host.state == "ready" and host.pid != old_pid)
            await plugin.send(ref, "fresh start")
            await _next_event(events, "session_end")
            starts = [row for row in _log_rows(log_path) if row["type"] == "start"]
            assert len(starts) == 2
            assert [row["resume"] for row in starts] == [None, None]
            assert all(row["cwd"] == str(tmp_path) for row in starts)
            assert "fake-sdk-session-1" in plugin._handles.values()
        finally:
            await plugin.close()
            if events is not None:
                await events.aclose()

    asyncio.run(exercise())


def test_silent_stream_is_flagged_and_supervisor_reports_stalled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        monkeypatch.setattr(
            "varde_runner.supervisor.load_config",
            lambda *_args, **_kwargs: replace(default_config(), stall_after_s=0.1),
        )
        plugin, _ = _plugin(tmp_path, idle_timeout=0.4)
        supervisor = Supervisor(tmp_path / "runner-state", {"claude-sdk": plugin})
        ref: SessionRef | None = None
        try:
            ref = await supervisor.start_session(_spec(tmp_path, "hang"), "builder")
            await _wait_for(
                lambda: any(
                    row["kind"] == "status" and row["payload"].get("silent") is True
                    for row in supervisor.store.events_after(ref.session_id, 0)
                ),
                timeout=10,
            )
            await asyncio.sleep(0.12)
            result = await supervisor.liveness(ref.session_id)
            assert (result.state, result.reason) == ("stalled", "silent")
            plugin_ref = supervisor._refs[ref.session_id]
            assert plugin.process_alive(plugin_ref)
            assert await plugin.idle_status(plugin_ref) == "running"
        finally:
            await supervisor.shutdown()

    asyncio.run(exercise())


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    if sys.platform == "linux":
        try:
            stat = Path(f"/proc/{pid}/stat").read_text()
        except FileNotFoundError:
            return False
        return stat[stat.rfind(")") + 2 :].split()[0] != "Z"
    return True


def test_interrupt_and_stop_kill_only_the_session_process_group(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        plugin, log_path = _plugin(tmp_path)
        first_events = None
        second_events = None
        first: SessionRef | None = None
        second: SessionRef | None = None
        try:
            first = await plugin.start(_spec(tmp_path, "hang"))
            second = await plugin.start(_spec(tmp_path, "hang"))
            first_events = plugin.events(first)
            second_events = plugin.events(second)
            try:
                await _wait_for(
                    lambda: (
                        len(
                            [
                                row
                                for row in _log_rows(log_path)
                                if row["type"] == "child"
                            ]
                        )
                        >= 2
                    )
                )
                host_for_groups = plugin.host
                assert host_for_groups is not None

                def has_two_tracked_groups() -> bool:
                    run = host_for_groups._run
                    return run is not None and len(run.tracked) >= 2

                await _wait_for(has_two_tracked_groups)
            except AssertionError as exc:
                host = plugin.host
                raise AssertionError(
                    f"fake SDK child did not start: {_log_rows(log_path)}; "
                    f"host stderr: {host.stderr_tail() if host else []}"
                ) from exc
            children = {
                row["session"]: row["grandchild"]
                for row in _log_rows(log_path)
                if row["type"] == "child"
            }
            host = plugin.host
            assert host is not None and host._run is not None
            groups = list(host._run.tracked.values())
            first_child, second_child = groups[:2]
            first_grandchild, second_grandchild = children[0], children[1]
            assert _pid_alive(first_child.pid)
            assert _pid_alive(first_grandchild)
            assert _pid_alive(second_child.pid)
            assert _pid_alive(second_grandchild)

            await plugin.interrupt(first)
            await _wait_for(
                lambda: (
                    not _pid_alive(first_child.pid) and not _pid_alive(first_grandchild)
                )
            )
            assert _pid_alive(second_child.pid)
            assert _pid_alive(second_grandchild)
            await plugin.send(first, "resumed after interrupt")
            await _next_event(first_events, "session_end")
            starts = [row for row in _log_rows(log_path) if row["type"] == "start"]
            assert starts[-1]["resume"] == "fake-sdk-session-1"

            await plugin.stop(second)
            await _wait_for(
                lambda: (
                    not _pid_alive(second_child.pid)
                    and not _pid_alive(second_grandchild)
                )
            )
        finally:
            await plugin.close()
            if first_events is not None:
                await first_events.aclose()
            if second_events is not None:
                await second_events.aclose()

    asyncio.run(exercise())


@pytest.mark.skipif(
    sys.platform != "linux", reason="requires Linux process-table checks"
)
def test_runner_sigkill_leaves_no_claude_child(tmp_path: Path) -> None:
    wrapper_plugin, _ = _plugin(tmp_path)
    assert wrapper_plugin.host is not None
    wrapper_path = tmp_path / "sdk-wrapper.mjs"
    ready_path = tmp_path / "runner-pids.json"
    state_dir = tmp_path / "killed-runner-state"
    helper = dedent(
        """\
        import asyncio
        import json
        import os
        from pathlib import Path

        from varde_runner.plugins import SessionSpec
        from varde_runner.plugins.claude_sdk.plugin import ClaudeSdkPlugin

        async def main():
            state_dir = Path(os.environ["FAKE_STATE_DIR"])
            (state_dir / "plugin").mkdir(parents=True, exist_ok=True)
            plugin = ClaudeSdkPlugin(
                state_dir=state_dir / "plugin",
                settings_text=(
                    "[node_host]\\nnode = "+json.dumps(os.environ["FAKE_NODE"])
                    + "\\nrestart_max = 1\\n\\n[claude_sdk]\\n"
                    + "stream_idle_timeout_s=10\\n"
                ),
            )
            plugin._host()
            host = plugin.host
            assert host is not None
            await plugin.start(
                SessionSpec(
                    "claude-sdk",
                    "fake-model",
                    "workspace",
                    os.environ["FAKE_CWD"],
                    "hang",
                    mode_id="workspace-write",
                )
            )
            while not host._run or not host._run.tracked:
                await asyncio.sleep(0.02)
            pids = {"host": host.pid, "groups": list(host._run.tracked)}
            Path(os.environ["FAKE_READY_FILE"]).write_text(json.dumps(pids))
            await asyncio.Event().wait()

        asyncio.run(main())
        """
    )
    helper_path = tmp_path / "runner-helper.py"
    helper_path.write_text(helper, encoding="utf-8")
    child_env = os.environ.copy()
    child_env["VARDE_CLAUDE_SDK_MODULE"] = str(wrapper_path)
    child_env["FAKE_SDK_LOG"] = str(tmp_path / "runner-sdk-log.jsonl")
    child_env["FAKE_NODE"] = _node()
    child_env["FAKE_STATE_DIR"] = str(state_dir)
    child_env["FAKE_READY_FILE"] = str(ready_path)
    child_env["FAKE_CWD"] = str(tmp_path)
    process = subprocess.Popen(  # noqa: S603 - fixed local Python test helper.
        [sys.executable, str(helper_path)],
        cwd=RUNNER_ROOT.parent,
        env=child_env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    groups: list[int] = []
    try:
        deadline = time.monotonic() + 20
        while not ready_path.exists() and process.poll() is None:
            if time.monotonic() >= deadline:
                raise AssertionError("runner helper did not start")
            time.sleep(0.02)
        assert process.poll() is None
        pids = json.loads(ready_path.read_text())
        groups = pids["groups"]
        assert groups
        assert process.pid != pids["host"]
        process.kill()
        process.wait(timeout=5)
        assert process.returncode == -signal.SIGKILL
        _wait_sync(
            lambda: (
                not _pid_alive(pids["host"])
                and all(not _group_alive(group) for group in groups)
            )
        )
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    if sys.platform == "linux":
        for stat_path in Path("/proc").glob("[0-9]*/stat"):
            try:
                stat = stat_path.read_text()
            except OSError:
                continue
            fields = stat[stat.rfind(")") + 2 :].split()
            if len(fields) > 2 and fields[0] != "Z" and int(fields[2]) == pgid:
                return True
        return False
    return True


def _wait_sync(predicate, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("timed out waiting for process group cleanup")
        time.sleep(0.02)
