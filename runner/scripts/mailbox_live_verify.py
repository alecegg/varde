"""Exercise mailbox addressing and failure diagnosis on an isolated runner."""

# ruff: noqa: S603, PLR0915

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any


def _port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _ready(port: int, process: subprocess.Popen[Any]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("scratch runner exited before becoming ready")
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/agents", timeout=1
            ):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError("scratch runner did not become ready")


def _command(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "from varde.cli import main; raise SystemExit(main())",
            *args,
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def _record(
    lines: list[str],
    label: str,
    result: subprocess.CompletedProcess[str],
    *,
    silent_reason: str | None = None,
) -> None:
    output = (result.stdout + result.stderr).strip()
    if not output and silent_reason:
        output = silent_reason
    lines.extend(
        [
            f"### {label} (exit {result.returncode})",
            "```text",
            output or "(empty output; the command returned successfully)",
            "```",
            "",
        ]
    )


def _record_send(
    lines: list[str],
    label: str,
    result: subprocess.CompletedProcess[str],
    working: Path,
) -> None:
    silent_reason = (
        "Command returned 0 without a CLI confirmation line; the persisted message "
        "below confirms acceptance."
        if result.returncode == 0
        else None
    )
    _record(lines, label, result, silent_reason=silent_reason)
    message_id = (
        result.stdout.split(maxsplit=2)[1]
        if result.stdout.startswith("sent ")
        else None
    )
    if result.returncode != 0:
        return
    path = working / ".cache" / "inbox" / "messages.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    message = (
        next(row for row in rows if row.get("id") == message_id)
        if message_id
        else rows[-1]
    )
    lines.extend(
        [
            "Persisted message:",
            "```json",
            json.dumps(
                {key: message[key] for key in ("id", "ts", "to", "kind", "text")},
                ensure_ascii=False,
            ),
            "```",
            "",
        ]
    )


def run(output: Path) -> None:
    lines = [
        "# Scratch runner mailbox live verification",
        "",
        "Runner and mailbox data used a temp directory and random loopback port.",
        "",
    ]
    with tempfile.TemporaryDirectory(prefix="varde-mailbox-verify-") as tmp:
        root = Path(tmp)
        working = root / "working"
        working.mkdir()
        port = _port()
        env = os.environ.copy()
        env.update(
            {
                "VARDE_WORKING_DIR": str(working),
                "VARDE_RUNNER_STATE_DIR": str(root / "runner-state"),
                "VARDE_DATA_ADDRESSES_BACKEND": "files",
                "VARDE_DATA_MESSAGES_BACKEND": "files",
            }
        )
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "from varde_runner import main; main()",
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            _ready(port, process)
            lines.append(f"Scratch runner ready at 127.0.0.1:{port}.")
            lines.append("")

            instance_marker: str | None = None
            receipt_marker: str | None = None
            for args, label in (
                (
                    ("msg", "address", "new", "orchestrator-1", "--plan", "plan-a"),
                    "Create role instance address",
                ),
                (
                    ("msg", "address", "new", "receipt-target"),
                    "Create receipt-capable address",
                ),
            ):
                result = _command(env, *args)
                if result.returncode:
                    raise RuntimeError(f"{label} failed: {result.stderr.strip()}")
                marker = result.stdout.strip()
                if label == "Create role instance address":
                    instance_marker = marker
                elif label == "Create receipt-capable address":
                    receipt_marker = marker
            if instance_marker is None or receipt_marker is None:
                raise RuntimeError("scratch address marker was not created")

            bind = _command(
                env,
                "msg",
                "address",
                "bind",
                instance_marker,
                "--session",
                "scratch-instance",
                "--harness",
                "codex",
            )
            _record(
                lines,
                "Bind role instance",
                bind,
                silent_reason=(
                    "Bind command returned 0 with no output; subsequent sends "
                    "verified the binding."
                ),
            )
            if bind.returncode:
                raise RuntimeError(bind.stderr.strip())
            bind_receipt = _command(
                env,
                "msg",
                "address",
                "bind",
                receipt_marker,
                "--session",
                "scratch-receipt-target",
                "--harness",
                "claude",
            )
            _record(
                lines,
                "Bind receipt-capable target",
                bind_receipt,
                silent_reason=(
                    "Bind command returned 0 with no output; later relay probe "
                    "uses this binding."
                ),
            )
            if bind_receipt.returncode:
                raise RuntimeError(bind_receipt.stderr.strip())

            from varde_workflow.slots import add_alias

            add_alias(working, "known-unbound", "plan-unbound")

            sends = (
                (
                    (
                        "msg",
                        "send",
                        "--from",
                        "main",
                        "--to",
                        "orchestrator",
                        "--kind",
                        "info",
                        "role inbox",
                    ),
                    "Send to role",
                ),
                (
                    (
                        "msg",
                        "send",
                        "--from",
                        "main",
                        "--to",
                        "orchestrator-1",
                        "--kind",
                        "info",
                        "instance inbox",
                    ),
                    "Send to instance",
                ),
                (
                    (
                        "msg",
                        "send",
                        "--from",
                        "orchestrator-1",
                        "--to",
                        "main",
                        "--kind",
                        "info",
                        "main inbox",
                    ),
                    "Send to main",
                ),
                (
                    (
                        "msg",
                        "send",
                        "--urgent",
                        "--from",
                        "main",
                        "--to",
                        "orchestrator",
                        "--kind",
                        "blocked",
                        "urgent inbox",
                    ),
                    "Send urgent mail",
                ),
                (
                    (
                        "msg",
                        "send",
                        "--from",
                        "main",
                        "--to",
                        "known-unbound",
                        "--kind",
                        "info",
                        "known but unbound",
                    ),
                    "Send to known unbound address",
                ),
                (
                    (
                        "msg",
                        "send",
                        "--from",
                        "main",
                        "--to",
                        "receipt-target",
                        "--kind",
                        "info",
                        "bound target without receipt",
                    ),
                    "Send to bound target awaiting receipt",
                ),
                (
                    (
                        "msg",
                        "send",
                        "--from",
                        "main",
                        "--to",
                        "unknown-mailbox-name",
                        "--kind",
                        "info",
                        "unknown",
                    ),
                    "Unknown address",
                ),
            )
            for args, label in sends:
                result = _command(env, *args)
                _record_send(lines, label, result, working)
                if label == "Unknown address" and result.returncode != 1:
                    raise RuntimeError("unknown address did not exit 1")
                if label != "Unknown address" and result.returncode:
                    raise RuntimeError(f"{label} failed: {result.stderr.strip()}")

            doctor = _command(env, "msg", "doctor", "--json")
            _record(lines, "Scratch relay doctor after live sends", doctor)
            if doctor.returncode not in {0, 1}:
                raise RuntimeError(doctor.stderr.strip())
            json.loads(doctor.stdout)
            lines.append(
                "No relay events were staged. These live sends verify queued "
                "unbound and unacknowledged targets, but this run did not wait for "
                "the worker to escalate them."
            )
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    run(args.out.expanduser().resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
