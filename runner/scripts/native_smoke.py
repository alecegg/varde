"""Run one native adapter session against an isolated runner process.

The harness inherits env and HOME for the user's own login; only runner state
is isolated.
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import select
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import ProxyHandler, Request, build_opener

from varde_runner.config import ROLE_NAMES

HARNESS_SECTIONS = {
    "claude-cli": "claude_cli",
    "codex-app-server": "codex_app_server",
    "pi-rpc": "pi_rpc",
    "opencode-http": "opencode_http",
    "pi-durable": "pi_durable",
}


class RunnerHTTPError(RuntimeError):
    def __init__(self, status: int, body: str) -> None:
        super().__init__(f"runner returned HTTP {status}: {body}")
        self.status = status


def config_text(
    harness: str,
    role: str,
    model: str,
    effort: str,
    *,
    provider: str = "openai",
    key_env: str = "OPENAI_API_KEY",
) -> str:
    section = HARNESS_SECTIONS[harness]
    mode = 'mode = "read-only"\n' if harness == "pi-rpc" else ""
    fallback_mode = ', mode = "read-only"' if mode else ""
    if harness == "pi-durable":
        return (
            "version = 1\n\n[policy]\nnever_models = []\n"
            'allow_fallback_only_on = ["provider_limit"]\n'
            "create_paseo_projects = false\n\n"
            f'[pi_durable]\nenabled = true\nprovider = "{provider}"\n'
            f'model = "{model}"\nkey_env = "{key_env}"\n'
            'storage_dir = "pi-durable"\n\n'
            '[types.smoke]\nharness = "pi-durable"\n'
            f'model = "{model}"\nreasoning_effort = "{effort}"\n'
            f'fallback = [{{ harness = "pi-durable", model = "{model}", '
            f'reasoning_effort = "{effort}" }}]\n\n[roles.{role}]\n'
            'type = "smoke"\n'
        )
    return (
        "version = 1\n\n"
        "[policy]\nnever_models = []\n"
        'allow_fallback_only_on = ["provider_limit"]\n'
        "create_paseo_projects = false\n\n"
        f"[{section}]\nenabled = true\n\n"
        "[types.smoke]\n"
        f'harness = "{harness}"\nmodel = "{model}"\n'
        f'reasoning_effort = "{effort}"\n{mode}'
        f'fallback = [{{ harness = "{harness}", model = "{model}", '
        f'reasoning_effort = "{effort}"{fallback_mode} }}]\n\n'
        f'[roles.{role}]\ntype = "smoke"\n'
    )


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def runner_environment(config: Path, state: Path, working: Path) -> dict[str, str]:
    """Build the isolated runner environment shared by the driver and tests."""
    env = os.environ.copy()
    env["VARDE_RUNNER_CONFIG_DIR"] = str(config)
    env["VARDE_RUNNER_STATE_DIR"] = str(state)
    env["VARDE_WORKING_DIR"] = str(working)
    env["VARDE_DATA_ADDRESSES_BACKEND"] = "files"
    env["VARDE_DATA_MESSAGES_BACKEND"] = "files"
    checkout_bin = str(Path(sys.executable).absolute().parent)
    env["PATH"] = checkout_bin + os.pathsep + env.get("PATH", "")
    return env


def runner_command(port: int) -> list[str]:
    """Return the runner command used by both real and offline smoke paths."""
    bootstrap = (
        "import logging; logging.basicConfig(level=logging.INFO, "
        "format='%(levelname)s %(name)s %(message)s'); "
        "from varde_runner import main; main()"
    )
    return [
        sys.executable,
        "-c",
        bootstrap,
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]


def runtime_info(environment: dict[str, str] | None = None) -> dict[str, Any]:
    """Describe the checkout modules and effective data backends."""
    import varde_runner
    from varde_data.config import load_data_config

    backends = dict(load_data_config().backends)
    selected_environment = environment or os.environ
    for domain in ("addresses", "messages"):
        override = selected_environment.get(f"VARDE_DATA_{domain.upper()}_BACKEND")
        if override is not None:
            backends[domain] = override
    cli_version = importlib.metadata.version("varde")
    return {
        "executable": sys.executable,
        "runner_module": str(Path(varde_runner.__file__).resolve()),
        "version": cli_version,
        "distribution_version": cli_version,
        "varde_executable": shutil.which(
            "varde", path=selected_environment.get("PATH")
        ),
        "data_backends": backends,
    }


def event_text(payload: dict[str, Any]) -> str | None:
    if payload.get("kind") == "text":
        event_payload = payload.get("payload")
        value = event_payload.get("text") if isinstance(event_payload, dict) else None
        return value if isinstance(value, str) else None
    return None


def watch_events(message: dict[str, Any]) -> list[dict[str, Any]]:
    if isinstance(message.get("kind"), str):
        return [message]
    if message.get("type") == "snapshot":
        events = message.get("events")
        return (
            [event for event in events if isinstance(event, dict)]
            if isinstance(events, list)
            else []
        )
    return []


class HttpAPI:
    def __init__(self, port: int, launch_timeout: float = 60) -> None:
        self.base = f"http://127.0.0.1:{port}"
        self.opener = build_opener(ProxyHandler({}))
        self.launch_timeout = launch_timeout

    def request(
        self, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        data = json.dumps(payload).encode() if payload is not None else None
        request = Request(  # noqa: S310 - self.base is a fixed loopback HTTP origin.
            self.base + path,
            data=data,
            headers={"content-type": "application/json"},
            method="POST" if payload is not None else "GET",
        )
        try:
            timeout = self.launch_timeout if path == "/api/agents" and payload else 15
            with self.opener.open(request, timeout=timeout) as response:
                return {
                    "http_status": response.status,
                    "body": json.loads(response.read()),
                }
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RunnerHTTPError(exc.code, body) from exc
        except URLError as exc:
            raise RuntimeError(f"runner request failed: {exc}") from exc

    def events(
        self, agent_id: str, client: str, timeout: float, after: int | None = None
    ):
        url = (
            f"{self.base}/api/agents/{quote(agent_id, safe='')}/watch"
            f"?client={quote(client)}&role=writer"
            + (f"&after={after}" if after is not None else "")
        )
        request = Request(  # noqa: S310 - url is built from the fixed loopback origin.
            url, headers={"accept": "text/event-stream"}
        )
        return self.opener.open(request, timeout=timeout)


def drive(  # noqa: PLR0913, PLR0917 - explicit smoke context inputs.
    api: Any,
    harness: str,
    role: str,
    workspace: str,
    prompt: str,
    reply_timeout: float = 120,
    model: str = "unknown",
    expected: str = "reply",
    mail_wake: bool = False,
    mail_working: str | None = None,
) -> dict[str, Any]:
    steps: list[dict[str, Any]] = []
    note: dict[str, Any] = {
        "harness": harness,
        "role": role,
        "model": model,
        "steps": steps,
        "events": [],
    }

    def perform(name: str, action):
        started = time.monotonic()
        try:
            result = action()
            status = (
                result.pop("http_status", "completed")
                if isinstance(result, dict)
                else "completed"
            )
            body = result.get("body", result) if isinstance(result, dict) else result
            entry = {
                "step": name,
                "status": status,
                "elapsed_seconds": time.monotonic() - started,
            }
            if isinstance(body, (dict, list, str, int, float, bool)) or body is None:
                entry["result"] = body
            steps.append(entry)
        except Exception as exc:
            steps.append(
                {
                    "step": name,
                    "status": "error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "elapsed_seconds": time.monotonic() - started,
                }
            )
            raise
        else:
            return result

    stream: Any = None
    try:
        launched = perform(
            "launch",
            lambda: api.request(
                "/api/agents",
                {
                    "harness": harness,
                    "workspace": workspace,
                    "role": role,
                    "prompt": prompt,
                    **(
                        {"address": {"slot": "smoke-orch", "plan": "smoke-plan"}}
                        if mail_wake
                        else {}
                    ),
                },
            ),
        )
        agent_id = launched["body"]["agent_id"]
        note["agent_id"] = agent_id
        if mail_wake:
            note.setdefault("binding_snapshots", {})["after_launch"] = relay_data_state(
                mail_working or workspace
            )["binding"]
        client = f"native-smoke-{uuid.uuid4().hex}"
        stream = perform(
            "stream_open", lambda: api.events(agent_id, client, reply_timeout)
        )
        base = f"/api/agents/{quote(agent_id, safe='')}"
        if mail_wake:
            first_reply = perform(
                "initial_reply",
                lambda: wait_for_reply(stream, reply_timeout, note["events"]),
            )
            note["initial_reply"] = first_reply
            note["binding_snapshots"]["after_first_reply"] = relay_data_state(
                mail_working or workspace
            )["binding"]
            perform("mail_send", lambda: send_smoke_mail(mail_working or workspace))
            wake_reply = perform(
                "mail_wake_reply",
                lambda: wait_for_reply(stream, reply_timeout, note["events"]),
            )
            note["wake_reply"] = wake_reply
            note["relay_data_state"] = relay_data_state(mail_working or workspace)
            lifecycle = ("stop", "archive")
        elif expected == "error":
            error = perform(
                "error",
                lambda: wait_for_error(stream, reply_timeout, note["events"]),
            )
            note["error_text"] = error
            lifecycle = ("stop", "archive")
        else:
            perform(
                "reply",
                lambda: wait_for_reply(stream, reply_timeout, note["events"]),
            )
            lifecycle = ("interrupt", "resume", "stop", "archive")
        for step in lifecycle:
            perform(
                step,
                lambda step=step: api.request(f"{base}/{step}", {"client": client}),
            )
    except Exception as exc:  # noqa: BLE001 - a failed run still leaves a transcript.
        note["error"] = f"{type(exc).__name__}: {exc}"
        note["runner_stderr_tail"] = getattr(api, "stderr_tail", "")
        if mail_wake and mail_working:
            note.setdefault("binding_snapshots", {})["at_timeout"] = relay_data_state(
                mail_working
            )["binding"]
    finally:
        if stream is not None:
            stream.close()
    return note


def wait_for_reply(
    stream: Any, timeout: float, events: list[dict[str, Any]] | None = None
) -> str:
    reply: list[str] = []
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("timed out waiting for agent reply")
        try:
            readable, _, _ = select.select([stream], [], [], remaining)
        except OSError, TypeError, ValueError:
            readable = [stream]
        if not readable:
            raise TimeoutError("timed out waiting for agent reply")
        raw = stream.readline()
        if not raw:
            raise TimeoutError("agent event stream closed before reply")
        line = raw.decode("utf-8").strip()
        if not line.startswith("data: "):
            continue
        event = json.loads(line[6:])
        for record in watch_events(event):
            kind = record.get("kind")
            if isinstance(events, list) and isinstance(kind, str):
                payload = record.get("payload")
                events.append(
                    {
                        "kind": kind,
                        "payload_keys": (
                            sorted(payload) if isinstance(payload, dict) else []
                        ),
                        **(
                            {"message": payload.get("message")}
                            if kind == "error"
                            and isinstance(payload, dict)
                            and isinstance(payload.get("message"), str)
                            else {}
                        ),
                    }
                )
            if kind == "permission_requested":
                payload = record.get("payload")
                request_id = (
                    payload.get("request_id") if isinstance(payload, dict) else None
                )
                name = f" {request_id}" if request_id is not None else ""
                raise RuntimeError(
                    f"permission_requested{name}; smoke driver will not approve"
                )
            text = event_text(record)
            if text:
                reply.append(text)
            event_payload = record.get("payload")
            is_idle = (
                kind == "status"
                and isinstance(event_payload, dict)
                and event_payload.get("status") == "idle"
            )
            if is_idle and reply:
                return "".join(reply)


def wait_for_error(stream: Any, timeout: float, events: list[dict[str, Any]]) -> str:
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("timed out waiting for agent error")
        try:
            readable, _, _ = select.select([stream], [], [], remaining)
        except OSError, TypeError, ValueError:
            readable = [stream]
        if not readable:
            raise TimeoutError("timed out waiting for agent error")
        raw = stream.readline()
        if not raw:
            raise TimeoutError("agent event stream closed before error")
        line = raw.decode("utf-8").strip()
        if not line.startswith("data: "):
            continue
        event = json.loads(line[6:])
        for record in watch_events(event):
            kind = record.get("kind")
            payload = record.get("payload")
            if isinstance(kind, str):
                events.append(
                    {
                        "kind": kind,
                        "payload_keys": sorted(payload)
                        if isinstance(payload, dict)
                        else [],
                        **(
                            {"message": payload.get("message")}
                            if kind == "error"
                            and isinstance(payload, dict)
                            and isinstance(payload.get("message"), str)
                            else {}
                        ),
                    }
                )
            if (
                kind == "error"
                and isinstance(payload, dict)
                and isinstance(payload.get("message"), str)
            ):
                return payload["message"]


def send_smoke_mail(working: str) -> dict[str, Any]:
    env = os.environ.copy()
    env["VARDE_WORKING_DIR"] = working
    env["VARDE_DATA_ADDRESSES_BACKEND"] = "files"
    env["VARDE_DATA_MESSAGES_BACKEND"] = "files"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from varde.cli import main; raise SystemExit(main())",
            "msg",
            "send",
            "--from",
            "smoke-main",
            "--to",
            "smoke-orch",
            "--kind",
            "needs-user",
            "Reply with the single word woke.",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return {
        "stdout": result.stdout.strip(),
        "command": "checkout Python varde.cli msg send",
        "runtime": runtime_info(env),
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--harness", choices=tuple(HARNESS_SECTIONS), required=True)
    result.add_argument("--role", choices=ROLE_NAMES, required=True)
    result.add_argument("--prompt", default="Reply with the single word ok.")
    result.add_argument("--workspace", type=Path)
    result.add_argument("--out", type=Path, required=True)
    result.add_argument("--model", required=True)
    result.add_argument("--effort", default="low")
    result.add_argument("--reply-timeout", type=float, default=120)
    result.add_argument("--expect", choices=("reply", "error"), default="reply")
    result.add_argument(
        "--mail-wake",
        action="store_true",
        help="verify a runner-launched session receives a mail wake",
    )
    result.add_argument("--launch-timeout", type=float, default=60)
    return result


def run_pi_durable_offline(  # noqa: PLR0915 - smoke lifecycle.
    args: argparse.Namespace,
) -> dict[str, Any]:
    """Exercise a durable session across a scratch runner restart."""

    with tempfile.TemporaryDirectory(prefix="varde-pi-durable-smoke-") as temporary:
        root = Path(temporary)
        config = root / "config"
        config.mkdir()
        (config / "runner.toml").write_text(
            config_text("pi-durable", args.role, args.model, args.effort),
            encoding="utf-8",
        )
        workspace = root / "workspace"
        workspace.mkdir()
        working = root / "working"
        working.mkdir()
        requests = root / "provider-requests.jsonl"
        scenario = root / "fake-provider.json"
        scenario.write_text(json.dumps({"requests": str(requests)}), encoding="utf-8")
        port = free_port()
        env = runner_environment(config, root / "state", working)
        fake = Path(__file__).parents[1] / "tests/fakes/fake_pi_durable_provider.mjs"
        env.update(
            {
                "VARDE_PI_DURABLE_FAKE_PROVIDER": str(scenario),
                "NODE_OPTIONS": f"--import={fake}",
                "OPENAI_API_KEY": "test-only-fake-key",
            }
        )
        stderr_path = root / "runner.stderr"
        stderr = stderr_path.open("w", encoding="utf-8")
        process = None
        note: dict[str, Any] = {"harness": "pi-durable", "steps": [], "port": port}

        def start() -> tuple[subprocess.Popen[Any], HttpAPI]:
            child = subprocess.Popen(  # noqa: S603 - fixed executable and arguments.
                runner_command(port), env=env, stdout=subprocess.DEVNULL, stderr=stderr
            )
            api = HttpAPI(port, args.launch_timeout)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if child.poll() is not None:
                    raise RuntimeError("scratch runner exited before readiness")
                try:
                    api.request("/api/agents")
                    return child, api  # noqa: TRY300
                except OSError, RuntimeError:
                    time.sleep(0.1)
            child.terminate()
            raise TimeoutError("scratch runner did not become ready")

        def stop(child: subprocess.Popen[Any]) -> None:
            child.terminate()
            child.wait(timeout=10)

        try:
            process, api = start()
            launched = api.request(
                "/api/agents",
                {
                    "harness": "pi-durable",
                    "workspace": str(workspace),
                    "role": args.role,
                    "prompt": args.prompt,
                },
            )
            agent_id = launched["body"]["agent_id"]
            client = f"native-smoke-{uuid.uuid4().hex}"
            base = f"/api/agents/{quote(agent_id, safe='')}"
            first_stream = api.events(agent_id, client, args.reply_timeout)
            first_reply = wait_for_text(first_stream, args.reply_timeout)
            first_stream.close()
            note["steps"].append({"step": "first_reply", "result": first_reply})
            stop(process)
            note["steps"].append({"step": "runner_restart_stop", "status": "stopped"})
            process, api = start()
            listing = api.request("/api/agents")
            if not any(row.get("agent_id") == agent_id for row in listing["body"]):
                raise RuntimeError(  # noqa: TRY301
                    "session state was not restored after restart"
                )
            replay_client = f"native-smoke-{uuid.uuid4().hex}"
            replay_stream = api.events(
                agent_id, replay_client, args.reply_timeout, after=0
            )
            replay = wait_for_text(replay_stream, args.reply_timeout)
            if replay != first_reply:
                raise RuntimeError(  # noqa: TRY301
                    "replayed event did not match the first reply"
                )
            note["steps"].append(
                {"step": "restart_restore_and_replay", "result": replay}
            )
            api.request(
                f"{base}/prompt",
                {"client": replay_client, "text": "second prompt"},
            )
            second_reply = wait_for_text(replay_stream, args.reply_timeout)
            replay_stream.close()
            note["steps"].append({"step": "second_prompt", "result": second_reply})
            note["provider_requests"] = len(
                requests.read_text(encoding="utf-8").splitlines()
            )
            if note["provider_requests"] != 2:
                raise RuntimeError(  # noqa: TRY301
                    "expected exactly two fake provider requests"
                )
            note["result"] = "PASS"
        except Exception as exc:  # noqa: BLE001 - the note records every smoke failure.
            note["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            if process is not None and process.poll() is None:
                stop(process)
            stderr.close()
        note["runner_stderr_tail"] = stderr_tail(stderr_path)
        return note


def wait_for_text(stream: Any, timeout: float) -> str:
    """Read one text event from a runner SSE stream, including snapshots."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        readable, _, _ = select.select(
            [stream], [], [], max(0, deadline - time.monotonic())
        )
        if not readable:
            break
        raw = stream.readline()
        if not raw:
            break
        line = raw.decode("utf-8").strip()
        if not line.startswith("data: "):
            continue
        for event in watch_events(json.loads(line[6:])):
            text = event_text(event)
            if text:
                return text
    raise TimeoutError("timed out waiting for agent text event")


def write_note(out: Path, note: dict[str, Any]) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(note, indent=2) + "\n", encoding="utf-8")


def include_readiness(note: dict[str, Any], readiness: dict[str, Any]) -> None:
    note["steps"] = [readiness, *note.get("steps", [])]


def stderr_tail(path: Path) -> str:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(lines[-60:])


def varde_msg_state(working: Path) -> dict[str, Any]:
    executable = shutil.which("varde")
    if executable is None:
        return {"error": "varde executable not found on PATH"}
    environment = os.environ.copy()
    environment["VARDE_WORKING_DIR"] = str(working)
    result = subprocess.run(  # noqa: S603 - executable and arguments are fixed.
        [executable, "msg", "read", "--as", "smoke-orch", "--all", "--json"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    return {
        "command": "varde msg read --as smoke-orch --all --json",
        "returncode": result.returncode,
        "stdout": result.stdout[-8000:],
        "stderr": result.stderr[-2000:],
    }


def relay_state(api: Any) -> dict[str, Any]:
    try:
        response = api.request("/api/relay")
    except Exception as exc:  # noqa: BLE001 - diagnostics must not mask smoke failure.
        return {"error": f"{type(exc).__name__}: {exc}"}
    if isinstance(response, dict):
        body = response.get("body", response)
        return body if isinstance(body, dict) else {"result": body}
    return {"result": response}


def relay_log_lines(stderr: str) -> list[str]:
    return [line for line in stderr.splitlines() if "relay" in line.lower()][-60:]


def relay_data_state(working: str | Path) -> dict[str, Any]:
    """Read the smoke slot's binding and pending mail for timeout evidence."""
    from varde_data.config import load_data_config
    from varde_data.open import open_data

    config = load_data_config()
    data = open_data(Path(working), config)
    binding = data.addresses.current_binding("smoke-orch")
    pending = data.messages.pending_by_address().get("smoke-orch", ())
    return {
        "data_backends": dict(config.backends),
        "binding": (
            {
                "address": binding.address,
                "session_id": binding.session_id,
                "harness": binding.harness,
                "last_seen": binding.last_seen.isoformat(),
                "token": binding.token_id,
                "extra": dict(binding.extra),
                "wake_context": dict(binding.extra.get("wake_context", {})),
            }
            if binding is not None
            else None
        ),
        "pending_messages": [
            {
                "id": message.id,
                "from": message.from_,
                "kind": message.kind,
                "text": message.text,
            }
            for message in pending
        ],
    }


def main() -> None:  # noqa: C901, PLR0912, PLR0915 - smoke setup and teardown.
    args = parser().parse_args()
    if args.harness == "pi-durable":
        note = run_pi_durable_offline(args)
        write_note(args.out, note)
        if note.get("runner_stderr_tail"):
            print(note["runner_stderr_tail"], file=sys.stderr)
        if "error" in note:
            raise SystemExit(f"smoke failed: {note['error']}")
        print(json.dumps({"result": note["result"], "steps": note["steps"]}))
        return
    with tempfile.TemporaryDirectory(prefix="varde-native-smoke-") as temporary:
        root = Path(temporary)
        steps: list[dict[str, Any]] = []
        note: dict[str, Any] = {
            "harness": args.harness,
            "role": args.role,
            "model": args.model,
            "steps": steps,
            "events": [],
        }
        stderr_path = root / "runner.stderr"
        config = root / "config"
        config.mkdir()
        (config / "runner.toml").write_text(
            config_text(args.harness, args.role, args.model, args.effort),
            encoding="utf-8",
        )
        working = root / "working"
        working.mkdir()
        workspace = args.workspace or root / "workspace"
        workspace.mkdir(parents=True, exist_ok=True)
        port = free_port()
        env = runner_environment(config, root / "state", working)
        env["VARDE_DATA_QUEUE_BACKEND"] = "sqlite"
        if args.mail_wake:
            env["VARDE_RUNNER_RELAY"] = "data"
            note["mail_wake"] = True
        process = None
        readiness_started = time.monotonic()
        try:
            process = subprocess.Popen(  # noqa: S603 - fixed executable and arguments.
                runner_command(port),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=stderr_path.open("w", encoding="utf-8"),
            )
            readiness_started = time.monotonic()
            deadline = readiness_started + 20
            api = HttpAPI(port, args.launch_timeout)
            consecutive_server_errors = 0
            while True:
                if process.poll() is not None:
                    raise RuntimeError(  # noqa: TRY301 - handled by readiness retry boundary.
                        "runner exited before becoming ready"
                    )
                try:
                    api.request("/api/agents")
                    steps.append(
                        {
                            "step": "readiness",
                            "status": "ready",
                            "elapsed_seconds": time.monotonic() - readiness_started,
                        }
                    )
                    break
                except RunnerHTTPError as exc:
                    if exc.status == 500:
                        consecutive_server_errors += 1
                        if consecutive_server_errors >= 3:
                            raise RuntimeError(
                                f"runner readiness returned HTTP 500 three times: {exc}"
                            ) from exc
                    else:
                        consecutive_server_errors = 0
                    if time.monotonic() >= deadline:
                        raise TimeoutError("runner did not become ready") from exc
                    time.sleep(0.1)
                except (OSError, RuntimeError) as exc:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("runner did not become ready") from exc
                    time.sleep(0.1)
            driven = drive(
                api,
                args.harness,
                args.role,
                str(workspace),
                args.prompt,
                args.reply_timeout,
                args.model,
                args.expect,
                args.mail_wake,
                str(working),
            )
            note = driven
            note["runner_runtime"] = runtime_info(env)
            include_readiness(note, steps[0])
            steps = note["steps"]
            if args.mail_wake and any(
                step.get("step") == "mail_wake_reply" and step.get("status") == "error"
                for step in steps
            ):
                tail = stderr_tail(stderr_path)
                note["runner_stderr_tail"] = tail
                note["relay_state"] = relay_state(api)
                note["relay_log_lines"] = relay_log_lines(tail)
                note["varde_msg_state"] = varde_msg_state(working)
                note["relay_data_state"] = relay_data_state(working)
        except Exception as exc:  # noqa: BLE001 - every failure produces a note.
            if steps and steps[-1].get("step") == "readiness":
                pass
            elif process is None:
                steps.append(
                    {
                        "step": "runner_start",
                        "status": "error",
                        "elapsed_seconds": 0.0,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
            else:
                steps.append(
                    {
                        "step": "readiness",
                        "status": "error",
                        "elapsed_seconds": time.monotonic() - readiness_started,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
            note["steps"] = steps
            note["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            if process is not None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        tail = stderr_tail(stderr_path)
        note.setdefault("runner_runtime", runtime_info(env))
        note["runner_stderr_tail"] = tail
        if tail:
            print(tail, file=sys.stderr)
        write_note(args.out, note)
        if "error" in note:
            raise SystemExit(f"smoke failed: {note['error']}")


if __name__ == "__main__":
    main()
