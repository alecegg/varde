#!/usr/bin/env python3
"""Run a metered Pi Durable smoke with a key read from Pi's auth store."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

PROVIDER = "deepseek"
MODEL = "deepseek/deepseek-flash"
KEY_ENV = "DEEPSEEK_API_KEY"
AUTH_PATH_ENV = "PI_DURABLE_AUTH_FILE"
SMOKE_CAP_USD = 1.0
STATUS_INTERVAL_SECONDS = 15.0
NO_PROGRESS_TIMEOUT_SECONDS = 300.0
REPORTED_TOTAL = [0.0]


class AuthFileError(ValueError):
    """An auth file cannot supply a supported DeepSeek API key."""


def auth_path() -> Path:
    override = os.environ.get(AUTH_PATH_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".pi" / "agent" / "auth.json"


def _auth_data(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuthFileError("Could not read Pi auth.json as valid JSON.") from exc
    if not isinstance(value, dict):
        raise AuthFileError("Pi auth.json must contain a provider object.")
    return value


def deepseek_fields(path: Path) -> tuple[bool, list[str]]:
    data = _auth_data(path)
    if PROVIDER not in data:
        return False, []
    entry = data[PROVIDER]
    if not isinstance(entry, dict):
        raise AuthFileError("The DeepSeek auth entry must be an object.")
    return True, sorted(str(field) for field in entry)


def read_deepseek_key(path: Path) -> str:
    exists, _ = deepseek_fields(path)
    if not exists:
        raise AuthFileError("No DeepSeek credential entry was found in Pi auth.json.")
    entry = _auth_data(path)[PROVIDER]
    credential_type = entry.get("type")
    if credential_type == "oauth":
        raise AuthFileError(
            "DeepSeek OAuth credentials are unsupported; an api_key entry is required."
        )
    if credential_type != "api_key":
        raise AuthFileError(
            "Unsupported DeepSeek credential type; expected an api_key entry."
        )
    key = entry.get("key")
    if not isinstance(key, str) or not key:
        raise AuthFileError("The DeepSeek api_key entry has no non-empty key field.")
    return key


def _native_smoke() -> Any:
    root = Path(__file__).parents[1]
    sys.path.insert(0, str(root / "src"))
    source = root / "scripts" / "native_smoke.py"
    spec = importlib.util.spec_from_file_location("native_smoke", source)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the native smoke helpers.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare_scratch(
    root: Path, api_key: str, port: int | None = None
) -> tuple[int, list[str], dict[str, str]]:
    if port == 8765:
        raise AuthFileError("Port 8765 is reserved for the live runner.")
    smoke = _native_smoke()
    config = root / "config"
    config.mkdir()
    (config / "runner.toml").write_text(
        smoke.config_text(
            "pi-durable",
            "builder",
            MODEL,
            "low",
            provider=PROVIDER,
            key_env=KEY_ENV,
        ),
        encoding="utf-8",
    )
    working = root / "working"
    working.mkdir()
    state = root / "state"
    env = smoke.runner_environment(config, state, working)
    env[KEY_ENV] = api_key
    selected_port = smoke.free_port() if port is None else port
    if selected_port == 8765:
        raise AuthFileError("Port 8765 is reserved for the live runner.")
    return selected_port, smoke.runner_command(selected_port), env


def _wait_ready(process: subprocess.Popen[bytes], port: int) -> None:
    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + 20
    url = f"http://127.0.0.1:{port}/api/agents"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Scratch runner exited before becoming ready.")
        try:
            with opener.open(url, timeout=1):
                return
        except OSError, URLError:
            time.sleep(0.1)
    raise RuntimeError("Scratch runner did not become ready.")


def _durable_run(
    args: argparse.Namespace,
    port: int,
    process: subprocess.Popen[bytes],
    runner_env: dict[str, str],
) -> int:
    current = [process]
    try:
        return _durable_run_started(args, port, current, runner_env)
    finally:
        if current[0].poll() is None:
            current[0].terminate()
            try:
                current[0].wait(timeout=5)
            except subprocess.TimeoutExpired:
                current[0].kill()
                current[0].wait()


def _durable_run_started(
    args: argparse.Namespace,
    port: int,
    current: list[subprocess.Popen[bytes]],
    runner_env: dict[str, str],
) -> int:
    smoke = _native_smoke()
    process = current[0]
    api = smoke.HttpAPI(port)
    workspace = str(Path(args.workspace).resolve())
    launched = api.request(
        "/api/agents",
        {
            "harness": "pi-durable",
            "workspace": workspace,
            "role": args.role,
            "prompt": Path(args.prompt).read_text(encoding="utf-8"),
        },
    )
    agent_id = launched["body"]["agent_id"]
    client = f"pi-durable-smoke-{os.getpid()}"
    first_reply, first_cost, cursor = _meter_reply(api, agent_id, client, None)
    print(f"First prompt complete; reported cost: ${first_cost:.4f}")

    process.terminate()
    process.wait(timeout=10)
    log_path = Path(runner_env["VARDE_RUNNER_CONFIG_DIR"]).parent / "runner.log"
    with log_path.open("ab") as log:
        process = subprocess.Popen(  # noqa: S603 - fixed command from native_smoke.
            smoke.runner_command(port),
            env=runner_env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
        )
    current[0] = process
    _wait_ready(process, port)
    api = smoke.HttpAPI(port)
    listing = api.request("/api/agents")["body"]
    if not any(row.get("agent_id") == agent_id for row in listing):
        raise RuntimeError("Session was not restored after runner restart.")
    replay_client = client + "-replay"
    replay_stream = api.events(agent_id, replay_client, 1800, after=0)
    try:
        replay, _, replay_cursor = _meter_reply(
            api,
            agent_id,
            replay_client,
            0,
            replay_only=True,
            event_stream=replay_stream,
        )
        if replay != first_reply:
            raise RuntimeError("Restart replay did not match the first reply.")
        print("Restart replay verified.")
        agent_path = f"/api/agents/{smoke.quote(agent_id, safe='')}"
        api.request(
            f"{agent_path}/prompt",
            {
                "client": replay_client,
                "text": "Reply with the new contents of calc.py's add function",
            },
        )
        second_reply, second_cost, _ = _meter_reply(
            api,
            agent_id,
            replay_client,
            max(cursor, replay_cursor),
            initial_cost=first_cost,
            event_stream=replay_stream,
        )
    finally:
        replay_stream.close()
    total = first_cost + second_cost
    print(f"Second prompt complete; total reported cost: ${total:.4f}")
    if total >= SMOKE_CAP_USD:
        raise RuntimeError("Combined reported usage reached the $1.00 smoke cap.")
    if not second_reply:
        raise RuntimeError("Followup prompt returned no text.")
    print("Followup prompt verified.")
    print(f"PASS: durable session resumed; total reported cost ${total:.4f}")
    return 0


def _meter_reply(  # noqa: PLR0913, PLR0912, PLR0915 - explicit metering loop.
    api: Any,
    agent_id: str,
    client: str,
    after: int | None,
    *,
    replay_only: bool = False,
    initial_cost: float = 0.0,
    event_stream: Any | None = None,
) -> tuple[str, float, int]:
    import json
    import math
    import select
    import time

    stream = (
        event_stream
        if event_stream is not None
        else api.events(agent_id, client, 1800, after=after)
    )
    reply = ""
    cost = 0.0
    seen_usage = False
    cursor = after or 0
    deadline = time.monotonic() + 1800
    last_event = time.monotonic()
    last_status = 0.0
    approval_summary: str | None = None
    try:
        while time.monotonic() < deadline:
            now = time.monotonic()
            ready, _, _ = select.select(
                [stream], [], [], min(1, STATUS_INTERVAL_SECONDS)
            )
            if not ready:
                now = time.monotonic()
                if now - last_status >= STATUS_INTERVAL_SECONDS:
                    _print_status(
                        api, agent_id, client, now - last_event, approval_summary
                    )
                    last_status = now
                if now - last_event >= NO_PROGRESS_TIMEOUT_SECONDS:
                    _stop_agent(api, agent_id, client)
                    print(
                        f"FAIL: no progress for {NO_PROGRESS_TIMEOUT_SECONDS:g}s; "
                        f"reported cost ${REPORTED_TOTAL[0]:.4f}",
                        flush=True,
                    )
                    raise TimeoutError(
                        "No progress while waiting for Pi Durable reply."
                    )
                continue
            raw = stream.readline()
            if not raw:
                break
            line = raw.decode("utf-8").strip()
            if not line.startswith("data: "):
                continue
            envelope = json.loads(line[6:])
            snapshot_cursor = envelope.get("last_seq")
            if isinstance(snapshot_cursor, int):
                cursor = max(cursor, snapshot_cursor)
            for event in api_events(envelope):
                last_event = time.monotonic()
                if event.get("kind") == "permission_requested":
                    approval_summary = "shell command requires approval"
                    print(f"waiting on approval: {approval_summary}", flush=True)
                seq = event.get("seq")
                if isinstance(seq, int):
                    cursor = max(cursor, seq)
                if event.get("kind") == "text":
                    payload = event.get("payload")
                    text = payload.get("text") if isinstance(payload, dict) else None
                    if isinstance(text, str):
                        reply = text
                if event.get("kind") == "usage" and not replay_only:
                    payload = event.get("payload")
                    value = (
                        payload.get("costUsd") if isinstance(payload, dict) else None
                    )
                    if (
                        not isinstance(value, (int, float))
                        or not math.isfinite(value)
                        or value < 0
                    ):
                        raise RuntimeError("Usage event has no valid reported cost.")
                    cost += value
                    seen_usage = True
                    REPORTED_TOTAL[0] = initial_cost + cost
                    if REPORTED_TOTAL[0] >= SMOKE_CAP_USD:
                        print(
                            "Reported usage reached the $1.00 smoke cap; "
                            f"stopping agent at ${REPORTED_TOTAL[0]:.4f}.",
                            flush=True,
                        )
                        _stop_agent(api, agent_id, client)
                        raise RuntimeError(
                            "Reported usage reached the $1.00 smoke cap."
                        )
            now = time.monotonic()
            if now - last_status >= STATUS_INTERVAL_SECONDS:
                _print_status(api, agent_id, client, now - last_event, approval_summary)
                last_status = now
            if reply and (replay_only or seen_usage):
                return reply, cost, cursor
        raise TimeoutError("Timed out waiting for a metered Pi Durable reply.")
    finally:
        if event_stream is None:
            stream.close()


def _stop_agent(api: Any, agent_id: str, client: str) -> None:
    smoke = _native_smoke()
    api.request(
        f"/api/agents/{smoke.quote(agent_id, safe='')}/stop",
        {"client": client},
    )


def _print_status(
    api: Any, agent_id: str, client: str, since_event: float, approval: str | None
) -> None:
    rows = api.request("/api/agents")["body"]
    row = next((item for item in rows if item.get("agent_id") == agent_id), {})
    lifecycle = row.get("lifecycle", "unknown")
    liveness = row.get("liveness", "unknown")
    if approval is None:
        pending = row.get("pending_requests", [])
        if pending:
            approval = "shell command requires approval"
            print(f"waiting on approval: {approval}", flush=True)
    line = (
        f"STATUS lifecycle={lifecycle} liveness={liveness} "
        f"reported_cost=${REPORTED_TOTAL[0]:.4f} seconds_since_event={since_event:.0f}"
    )
    print(line, flush=True)


def api_events(message: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(message.get("kind"), str):
        return [message]
    events = message.get("events")
    if not isinstance(events, list):
        return []
    return [event for event in events if isinstance(event, dict)]


def _run(args: argparse.Namespace) -> int:
    key_file = auth_path()
    api_key = read_deepseek_key(key_file)
    exists, fields = deepseek_fields(key_file)
    field_names = ", ".join(fields) if fields else "none"
    print(f"DeepSeek entry: {'present' if exists else 'absent'}; fields: {field_names}")
    root = Path(
        tempfile.mkdtemp(prefix="varde-pi-durable-smoke-", dir=tempfile.gettempdir())
    )
    print(f"Scratch files: {root}")
    port, command, runner_env = prepare_scratch(root, api_key, args.port)
    log = (root / "runner.log").open("wb")
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(  # noqa: S603 - fixed command from native_smoke.
            command,
            env=runner_env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
        )
        _wait_ready(process, port)
        print(f"Scratch runner is ready on port {port}.")
        print(
            "This starts two real Pi Durable prompts. "
            "Combined reported-cost stop threshold: $1.00."
        )
        if input("Type RUN to continue: ").strip() != "RUN":
            print("Cancelled.")
            return 1
        return _durable_run(args, port, process, runner_env)
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        log.close()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=(
            "Run a real-provider Pi Durable smoke on an isolated scratch runner."
        )
    )
    result.add_argument(
        "--check",
        action="store_true",
        help="Report only DeepSeek entry presence and its field names.",
    )
    result.add_argument(
        "--port",
        type=int,
        default=18765,
        help="Scratch runner port (8765 is reserved).",
    )
    result.add_argument("role", nargs="?")
    result.add_argument("workspace", nargs="?")
    result.add_argument("prompt", nargs="?")
    return result


def execute(args: argparse.Namespace) -> int:
    if args.check:
        if any((args.role, args.workspace, args.prompt)):
            raise AuthFileError("--check does not take run arguments.")
        exists, fields = deepseek_fields(auth_path())
        state = "present" if exists else "absent"
        field_names = ", ".join(fields) if fields else "none"
        print(f"DeepSeek entry: {state}; fields: {field_names}")
        return 0
    if not all((args.role, args.workspace, args.prompt)):
        raise AuthFileError("Usage: pi-durable-smoke-env.sh ROLE WORKSPACE PROMPT_FILE")
    if args.port == 8765 or not 1 <= args.port <= 65535:
        raise AuthFileError(
            "Choose a valid scratch port; port 8765 is reserved for the live runner."
        )
    if not Path(args.prompt).is_file():
        raise AuthFileError("Prompt file does not exist.")
    if not Path(args.prompt).stat().st_size:
        raise AuthFileError("Prompt file is empty.")
    return _run(args)


def main() -> int:
    args = parser().parse_args()
    try:
        return execute(args)
    except AuthFileError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Smoke interrupted; scratch runner stopped.", file=sys.stderr)
        return 130
    except Exception:  # noqa: BLE001 - suppress error text that could hold auth data.
        # Never print exception text or a traceback: child errors may contain auth data.
        print(
            "Pi Durable smoke failed; details were suppressed to protect credentials.",
            file=sys.stderr,
        )
        print(f"FAIL: Pi Durable smoke; reported cost ${REPORTED_TOTAL[0]:.4f}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
