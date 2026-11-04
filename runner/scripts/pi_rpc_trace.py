"""Record the raw frames of one `pi --mode rpc` session built by the runner adapter.

Sends get_state, then one tiny prompt, and writes every stdout/stderr line with a
timestamp to --out. One run; bounded by --seconds. Uses the user's own pi login.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from varde_runner.plugins.pi_rpc.wire import build_command, encode_command


def pump(stream, label: str, lines: list[dict], started: float) -> None:
    for raw in stream:
        elapsed = round(time.monotonic() - started, 2)
        text = raw.decode("utf-8", "replace").rstrip()[: 256 * 1024]
        lines.extend([{"t": elapsed, "stream": label, "line": text}])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", default="high")
    parser.add_argument("--prompt", default="Reply with exactly one word: READY")
    parser.add_argument("--seconds", type=float, default=45)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    command = build_command(args.model, "trace-session", None, args.effort)
    lines: list[dict] = []
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="pi-rpc-trace-") as cwd:
        process = subprocess.Popen(  # noqa: S603 - fixed adapter command line.
            command,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdin = process.stdin
        if stdin is None:
            raise RuntimeError("pi stdin pipe missing")
        for label, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
            threading.Thread(
                target=pump, args=(stream, label, lines, started), daemon=True
            ).start()
        stdin.write((encode_command("get_state", "trace-1") + "\n").encode())
        stdin.flush()
        time.sleep(3)
        stdin.write(
            (encode_command("prompt", "trace-2", message=args.prompt) + "\n").encode()
        )
        stdin.flush()
        deadline = started + args.seconds
        while time.monotonic() < deadline and process.poll() is None:
            time.sleep(0.5)
        exit_code = process.poll()
        process.kill()
    note = {"command": command, "exit_code": exit_code, "frames": lines}
    args.out.write_text(json.dumps(note, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(lines)} frames to {args.out}")


if __name__ == "__main__":
    main()
