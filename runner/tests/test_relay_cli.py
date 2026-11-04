from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from varde_data.config import DataConfig
from varde_data.open import open_data
from varde_data.records.addresses import ReaderContext
from varde_runner.relay import RelayCLI, RelayCommandError, command_error


def fake_varde(
    tmp_path: Path, *, status_code: int = 1, status_stdout: str | None = None
) -> tuple[Path, Path]:
    output = status_stdout
    if output is None:
        output = '{"runner_relay":"down"}' if status_code in {0, 1} else ""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    record = tmp_path / "record.json"
    executable = bin_dir / "varde"
    executable.write_text(
        "#!/bin/sh\n"
        "if [ \"$1 $2 $3\" = 'msg status --json' ]; then\n"
        f"  printf '%s' '{output}'\n"
        f"  exit {status_code}\n"
        "fi\n"
        f"printf '%s' \"$VARDE_WORKING_DIR|$PWD\" > {record}\n"
        "exit 0\n"
    )
    executable.chmod(0o755)
    return bin_dir, record


def test_status_reports_seeded_relay_snapshot(tmp_path):
    now = datetime.now(UTC)
    addresses = open_data(tmp_path, DataConfig()).addresses
    marker = addresses.issue("mailman", now=now, issuer="test")
    addresses.redeem(
        marker,
        "runner-session",
        "codex",
        ReaderContext(cwd=str(tmp_path)),
        now=now,
    )
    token_id = addresses.list_bindings()[0].token_id
    addresses.heartbeat(token_id, "waiting", now, instance_id="runner")

    assert asyncio.run(RelayCLI(cwd=tmp_path).status()) == {
        "runner_relay": "up",
        "mailman": "alive",
        "mailmen": [{"id": token_id, "alive": True}],
        "bad": False,
    }


def test_status_reports_empty_snapshot_when_store_is_missing(tmp_path):
    assert asyncio.run(RelayCLI(cwd=tmp_path).status()) == {
        "runner_relay": "down",
        "mailman": "none",
        "mailmen": [],
        "bad": False,
    }


@pytest.mark.skipif(shutil.which("varde") is None, reason="varde is not on PATH")
def test_real_varde_status_reports_bad_temp_store(tmp_path, monkeypatch):
    from varde_workflow.slots import add_alias

    add_alias(tmp_path, "unbound-test")
    monkeypatch.setenv("VARDE_WORKING_DIR", str(tmp_path))
    subprocess.run(
        [  # noqa: S607 - Test resolves the installed Varde CLI from PATH.
            "varde",
            "msg",
            "send",
            "--from",
            "relay-test",
            "--to",
            "unbound-test",
            "--kind",
            "info",
            "old pending message",
        ],
        cwd=tmp_path,
        env={**os.environ, "VARDE_WORKING_DIR": str(tmp_path)},
        check=True,
        capture_output=True,
        text=True,
    )
    store = tmp_path / ".cache" / "inbox" / "messages.jsonl"
    rows = store.read_text(encoding="utf-8").splitlines()
    assert rows, "varde msg send did not create a temp-store message"
    message = json.loads(rows[-1])
    message["ts"] = "2000-01-01T00:00:00Z"
    rows[-1] = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
    store.write_text("\n".join(rows) + "\n", encoding="utf-8")

    cli = RelayCLI(cwd=tmp_path)
    assert asyncio.run(cli.status())
    raw = subprocess.run(
        ["varde", "msg", "status", "--json"],  # noqa: S607 - Test resolves the installed Varde CLI from PATH.
        cwd=tmp_path,
        env={**os.environ, "VARDE_WORKING_DIR": str(tmp_path)},
        check=False,
        capture_output=True,
        text=True,
    )
    assert raw.returncode == 1


def test_command_errors_always_have_a_message(tmp_path, monkeypatch):
    bin_dir, _ = fake_varde(tmp_path, status_code=2)
    cwd = tmp_path / "outside-repo"
    cwd.mkdir()
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    cli = RelayCLI(cwd=cwd)

    with pytest.raises(RelayCommandError) as caught:
        asyncio.run(cli.json("msg", "status", "--json"))
    assert str(caught.value)
    assert str(caught.value) == "varde msg status --json exited 2"


def test_command_error_prefers_stderr_then_stdout():
    assert str(command_error(2, "out", " err ", ("msg", "status"))) == "err"
    assert str(command_error(2, " output ", "", ("msg", "status"))) == "output"


@pytest.mark.parametrize(
    ("harness", "expected"), [("pi-rpc", "unknown"), ("claude", "claude")]
)
def test_confirm_does_not_claim_receipt_support_for_native_harnesses(
    tmp_path, harness, expected
):
    cli = RelayCLI(cwd=tmp_path)
    calls = []

    async def record(*args):
        calls.append(args)
        return {}

    cli.json = record
    asyncio.run(cli.confirm("action", "pushed", "ok", "mailman", harness=harness))

    args = calls[0]
    assert args[args.index("--harness") + 1] == expected
