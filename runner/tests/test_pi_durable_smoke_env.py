from __future__ import annotations

import argparse
import builtins
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from varde_runner.config import parse_config, pi_durable_settings

pytestmark = pytest.mark.slow

SCRIPT = Path(__file__).parents[1] / "scripts" / "pi-durable-smoke-env.sh"
MODULE_PATH = Path(__file__).parents[1] / "scripts" / "pi_durable_smoke_env.py"
SPEC = importlib.util.spec_from_file_location("pi_durable_smoke_env", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
BASH = str(Path(shutil.which("bash") or "/bin/bash").resolve())


def test_check_and_scratch_setup_never_expose_auth_key(tmp_path: Path) -> None:
    sentinel = "deepseek-secret-sentinel-54d9d1"
    auth = tmp_path / "fake-auth.json"
    auth.write_text(
        json.dumps({"deepseek": {"type": "api_key", "key": sentinel}}),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env[MODULE.AUTH_PATH_ENV] = str(auth)
    result = subprocess.run(  # noqa: S603 - fixed local test script with fake data.
        [BASH, str(SCRIPT), "--check"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "DeepSeek entry: present" in result.stdout
    assert "fields: key, type" in result.stdout
    assert sentinel not in result.stdout
    assert sentinel not in result.stderr
    assert sentinel not in " ".join(result.args)

    scratch = tmp_path / "scratch"
    scratch.mkdir()
    port, command, runner_env = MODULE.prepare_scratch(scratch, sentinel)
    assert port != 8765
    assert sentinel not in " ".join(command)
    assert runner_env[MODULE.KEY_ENV] == sentinel
    config_path = scratch / "config" / "runner.toml"
    settings = pi_durable_settings(config_path.read_text(encoding="utf-8"))
    assert settings.provider == "deepseek"
    assert settings.model == "deepseek/deepseek-flash"
    assert settings.key_env == "DEEPSEEK_API_KEY"
    assert (
        parse_config(config_path.read_text(encoding="utf-8")).resolve("builder").harness
        == "pi-durable"
    )
    assert sentinel not in " ".join(
        path.read_text(encoding="utf-8")
        for path in scratch.rglob("*")
        if path.is_file()
    )


def test_check_reports_absence_without_values(tmp_path: Path) -> None:
    env = os.environ.copy()
    env[MODULE.AUTH_PATH_ENV] = str(tmp_path / "missing-auth.json")
    result = subprocess.run(  # noqa: S603 - fixed local test script with fake data.
        [BASH, str(SCRIPT), "--check"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "DeepSeek entry: absent; fields: none"
    assert result.stderr == ""


def test_port_option_and_live_port_refusal(tmp_path: Path) -> None:
    args = MODULE.parser().parse_args(
        ["--port", "18766", "builder", str(tmp_path), "prompt.txt"]
    )
    assert args.port == 18766
    scratch = tmp_path / "alternate"
    scratch.mkdir()
    selected, command, _ = MODULE.prepare_scratch(scratch, "fake", args.port)
    assert selected == 18766
    assert command[-1] == "18766"
    with pytest.raises(MODULE.AuthFileError, match="8765"):
        MODULE.prepare_scratch(tmp_path / "reserved", "fake", 8765)
    result = subprocess.run(  # noqa: S603 - fixed local test script with fake data.
        [BASH, str(SCRIPT), "--port", "8765", "builder", str(tmp_path), "missing"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "8765" in result.stderr


def test_fake_provider_run_restarts_replays_and_meters(
    tmp_path, monkeypatch, capsys
) -> None:
    result, error, output = _run_with_fake_provider(
        tmp_path,
        monkeypatch,
        capsys,
        usage={
            "input_tokens": 100_000,
            "output_tokens": 100_000,
            "total_tokens": 200_000,
        },
    )

    assert error is None
    assert result == 0
    assert "PASS: durable session resumed" in output
    assert "Restart replay verified." in output
    assert "Followup prompt verified." in output
    assert MODULE.REPORTED_TOTAL[0] > 0


def test_fake_provider_cost_cap_stops_agent(tmp_path, monkeypatch, capsys) -> None:
    stop_calls = _track_fake_runner_api(monkeypatch)
    result, error, output = _run_with_fake_provider(
        tmp_path,
        monkeypatch,
        capsys,
        usage={
            "input_tokens": 10_000_000,
            "output_tokens": 10_000_000,
            "total_tokens": 20_000_000,
        },
        expect_cap=True,
    )
    assert result is None
    assert isinstance(error, RuntimeError) and "smoke cap" in str(error)
    assert "stopping agent at $" in output
    assert stop_calls and stop_calls[0][0].endswith("/stop")
    assert MODULE.REPORTED_TOTAL[0] >= MODULE.SMOKE_CAP_USD


def test_fake_provider_approval_wait_times_out_and_stops_agent(
    tmp_path, monkeypatch, capsys
) -> None:
    stop_calls = _track_fake_runner_api(monkeypatch)
    monkeypatch.setattr(MODULE, "STATUS_INTERVAL_SECONDS", 0.05)
    monkeypatch.setattr(MODULE, "NO_PROGRESS_TIMEOUT_SECONDS", 0.3)
    result, error, output = _run_with_fake_provider(
        tmp_path,
        monkeypatch,
        capsys,
        usage=None,
        first_tool={"name": "bash", "arguments": {"command": "pytest test_calc.py -q"}},
        expect_timeout=True,
    )
    assert result is None
    assert isinstance(error, TimeoutError)
    assert "waiting on approval:" in output
    assert "STATUS lifecycle=" in output
    assert "seconds_since_event=" in output
    assert stop_calls and stop_calls[0][0].endswith("/stop")


def _track_fake_runner_api(monkeypatch):
    smoke = MODULE._native_smoke()
    parent_api = smoke.HttpAPI
    stop_calls = []

    class TrackingAPI(parent_api):
        def request(self, path, payload=None):
            if path.endswith("/stop"):
                stop_calls.append((path, payload))
            return super().request(path, payload)

    smoke.HttpAPI = TrackingAPI
    monkeypatch.setattr(MODULE, "_native_smoke", lambda: smoke)
    return stop_calls


def _run_with_fake_provider(  # noqa: PLR0913 - explicit fake-run context.
    tmp_path,
    monkeypatch,
    capsys,
    *,
    usage,
    expect_cap=False,
    first_tool=None,
    expect_timeout=False,
):
    _track_fake_runner_api(monkeypatch)
    sentinel = "fake-provider-secret-sentinel-0b762c"
    auth = tmp_path / "fake-auth.json"
    auth.write_text(
        json.dumps({"openai": {"type": "api_key", "key": sentinel}}),
        encoding="utf-8",
    )
    prompt = tmp_path / "prompt.txt"
    prompt.write_text(
        "Read calc.py, edit subtraction to addition, and reply with one line.",
        encoding="utf-8",
    )
    requests = tmp_path / "requests.jsonl"
    scenario = tmp_path / "fake-provider.json"
    scenario.write_text(
        json.dumps(
            {"requests": str(requests), "usage": usage, "firstTool": first_tool}
        ),
        encoding="utf-8",
    )
    fake = Path(__file__).parent / "fakes" / "fake_pi_durable_provider.mjs"
    monkeypatch.setattr(MODULE, "PROVIDER", "openai")
    monkeypatch.setattr(MODULE, "MODEL", "openai/gpt-4o-mini")
    monkeypatch.setattr(MODULE, "KEY_ENV", "OPENAI_API_KEY")
    monkeypatch.setattr(MODULE, "REPORTED_TOTAL", [0.0])
    monkeypatch.setenv(MODULE.AUTH_PATH_ENV, str(auth))
    monkeypatch.setenv("VARDE_PI_DURABLE_FAKE_PROVIDER", str(scenario))
    monkeypatch.setenv("NODE_OPTIONS", f"--import={fake}")
    monkeypatch.setattr(builtins, "input", lambda _prompt: "RUN")
    args = argparse.Namespace(
        port=MODULE._native_smoke().free_port(),
        role="builder",
        workspace=str(tmp_path),
        prompt=str(prompt),
    )
    error = None
    result = None
    try:
        result = MODULE._run(args)
    except (RuntimeError, TimeoutError) as exc:
        if not expect_cap and not expect_timeout:
            raise
        error = exc
    output = capsys.readouterr().out
    assert sentinel not in output
    expected_requests = 1 if expect_cap or expect_timeout else 2
    assert requests.read_text(encoding="utf-8").count("\n") == expected_requests
    scratch_line = next(
        line for line in output.splitlines() if line.startswith("Scratch files: ")
    )
    scratch = Path(scratch_line.removeprefix("Scratch files: "))
    scratch_text = " ".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in scratch.rglob("*")
        if path.is_file()
    )
    assert sentinel not in scratch_text
    other_files = " ".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in tmp_path.rglob("*")
        if path.is_file() and path != auth
    )
    assert sentinel not in other_files
    shutil.rmtree(scratch)
    return result, error, output


def test_check_suppresses_malformed_auth_errors(tmp_path: Path) -> None:
    sentinel = "malformed-secret-sentinel-b6e42c"
    auth = tmp_path / "fake-auth.json"
    auth.write_text(f'{{"deepseek": "{sentinel}"', encoding="utf-8")
    env = os.environ.copy()
    env[MODULE.AUTH_PATH_ENV] = str(auth)
    result = subprocess.run(  # noqa: S603 - fixed local test script with fake data.
        [BASH, str(SCRIPT), "--check"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert sentinel not in result.stdout
    assert sentinel not in result.stderr
    assert "Traceback" not in result.stderr


def test_oauth_credentials_are_rejected_without_printing_values(tmp_path: Path) -> None:
    sentinel = "oauth-secret-sentinel-126aa7"
    auth = tmp_path / "fake-auth.json"
    auth.write_text(
        json.dumps(
            {
                "deepseek": {
                    "type": "oauth",
                    "access": sentinel,
                    "refresh": "refresh-sentinel",
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        MODULE.AuthFileError, match="OAuth credentials are unsupported"
    ) as exc_info:
        MODULE.read_deepseek_key(auth)
    assert sentinel not in str(exc_info.value)

    prompt = tmp_path / "prompt.txt"
    prompt.write_text("Reply with one word.", encoding="utf-8")
    env = os.environ.copy()
    env[MODULE.AUTH_PATH_ENV] = str(auth)
    result = subprocess.run(  # noqa: S603 - fixed local test script with fake data.
        [BASH, str(SCRIPT), "builder", str(tmp_path), str(prompt)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "OAuth credentials are unsupported" in result.stderr
    assert sentinel not in result.stdout
    assert sentinel not in result.stderr
    assert "Traceback" not in result.stderr
