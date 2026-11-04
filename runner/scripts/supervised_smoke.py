"""Check that a real runner session produces output or its startup diagnostic."""

# Every subprocess command below is built from fixed program names and local values.
# ruff: noqa: S603, S607

from __future__ import annotations

import argparse
import json
import os
import plistlib
import socket
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _request(port: int, path: str, payload: dict[str, Any] | None = None) -> Any:
    data = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=data,
        headers={"content-type": "application/json"},
        method="POST" if data is not None else "GET",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=10) as response:
        return json.load(response)


def classify_event(event: dict[str, Any]) -> str | None:
    kind = event.get("kind") or event.get("type")
    payload = event.get("payload")
    text = payload.get("text", "") if isinstance(payload, dict) else ""
    if isinstance(text, str) and "The child produced no output" in text:
        return "diagnostic"
    if kind in {"text", "frame"} or text:
        return "frame_seen"
    return None


def wait_for_output(port: int, agent: str, timeout: float) -> str:
    query = urllib.parse.urlencode(
        {"client": f"smoke-{uuid.uuid4().hex}", "role": "writer"}
    )
    agent_path = urllib.parse.quote(agent, safe="")
    url = f"http://127.0.0.1:{port}/api/agents/{agent_path}/watch?{query}"
    request = urllib.request.Request(url, headers={"accept": "text/event-stream"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + timeout
    try:
        with opener.open(request, timeout=timeout) as stream:
            while time.monotonic() < deadline:
                line = stream.readline()
                if not line:
                    return "timeout"
                if line.startswith(b"data: "):
                    event = json.loads(line[6:])
                    result = classify_event(event)
                    if result:
                        return result
    except TimeoutError, OSError:
        pass
    return "timeout"


def runner_environment(root: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        VARDE_RUNNER_STATE_DIR=str(root / "state"),
        VARDE_WORKING_DIR=str(root / "working"),
        VARDE_DATA_ADDRESSES_BACKEND="files",
        VARDE_DATA_MESSAGES_BACKEND="files",
    )
    return env


def _runner_command(port: int) -> list[str]:
    return [
        sys.executable,
        "-c",
        "from varde_runner import main; main()",
        "serve",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]


def _start_service(root: Path, port: int, env: dict[str, str]) -> tuple[str, str]:
    token = uuid.uuid4().hex
    command = _runner_command(port)
    if sys.platform == "darwin":
        label = f"org.varde.runner.smoke.{token}"
        service = root / "service.plist"
        service.write_bytes(
            plistlib.dumps(
                {
                    "Label": label,
                    "ProgramArguments": command,
                    "RunAtLoad": True,
                    "EnvironmentVariables": env,
                    "StandardOutPath": str(root / "out.log"),
                    "StandardErrorPath": str(root / "err.log"),
                }
            )
        )
        subprocess.run(
            ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(service)], check=True
        )
        return "launchd", label
    unit = f"varde-runner-smoke-{token}"
    subprocess.run(
        [
            "systemd-run",
            "--user",
            "--unit",
            unit,
            "--collect",
            *[f"--setenv={key}={value}" for key, value in env.items()],
            *command,
        ],
        check=True,
    )
    return "systemd", unit


def _pid_from_text(output: str) -> int:
    for line in output.splitlines():
        key, separator, value = line.strip().partition("=")
        if separator and key == "pid" and value.isdigit():
            return int(value)
    raise RuntimeError("service did not report a runner process")


def _stop_service(
    kind: str, identity: str, process: subprocess.Popen[Any] | None
) -> None:
    if process is not None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
    elif kind == "launchd":
        subprocess.run(
            ["launchctl", "bootout", f"gui/{os.getuid()}/{identity}"], check=False
        )
    elif kind == "systemd":
        subprocess.run(
            ["systemctl", "--user", "stop", f"{identity}.service"], check=False
        )


def run(args: argparse.Namespace) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="varde-runner-smoke-") as directory:
        root = Path(directory)
        (root / "working").mkdir()
        workspace = root / "workspace"
        workspace.mkdir()
        port = _port()
        env = runner_environment(root)
        process = None
        service_pid = None
        if args.foreground:
            process = subprocess.Popen(
                _runner_command(port),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            kind, identity = "foreground", ""
        else:
            kind, identity = _start_service(root, port, env)
        try:
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if process is not None and process.poll() is not None:
                    raise RuntimeError("runner exited before becoming ready")
                try:
                    _request(port, "/api/agents")
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                raise TimeoutError("runner did not become ready")
            service_pid = (
                process.pid if process is not None else _service_pid(kind, identity)
            )
            agent = _request(
                port,
                "/api/agents",
                {
                    "harness": args.harness,
                    "workspace": str(workspace),
                    "role": "builder",
                    "prompt": "Reply with one short sentence.",
                },
            )["agent_id"]
            outcome = wait_for_output(port, agent, args.timeout)
            if process is not None:
                alive = process.pid == service_pid and process.poll() is None
            else:
                alive = _service_pid(kind, identity) == service_pid
            return {"outcome": outcome, "runner_pid_unchanged": alive}
        finally:
            _stop_service(kind, identity, process)


def _service_pid(kind: str, identity: str) -> int:
    if kind == "launchd":
        result = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{identity}"],
            check=True,
            capture_output=True,
            text=True,
        )
        return _pid_from_text(result.stdout)
    result = subprocess.run(
        [
            "systemctl",
            "--user",
            "show",
            "--property=MainPID",
            "--value",
            f"{identity}.service",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return int(result.stdout.strip())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--harness", required=True)
    parser.add_argument("--foreground", action="store_true")
    parser.add_argument("--timeout", type=float, default=45)
    args = parser.parse_args()
    result = run(args)
    print(json.dumps(result, sort_keys=True) if args.json else result)
    if (
        result["outcome"] not in {"frame_seen", "diagnostic"}
        or not result["runner_pid_unchanged"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
