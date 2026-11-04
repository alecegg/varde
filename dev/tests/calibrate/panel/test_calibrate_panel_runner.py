import datetime as dt
import json
from pathlib import Path

import pytest
from varde_dev.calibrate.panel.commands import main, scan_secrets
from varde_dev.calibrate.panel.logic import (
    build_codex_command,
    claude_code_command,
    opaque_pair_id,
    pi_command,
)

NOW = dt.datetime(2026, 10, 19, 9, 30, tzinfo=dt.UTC)


def _dataset(root: Path) -> Path:
    dataset = root / "dataset"
    dataset.mkdir()
    _write_jsonl(
        dataset / "items.jsonl",
        [
            {"id": "opaque-a", "text": "def a():\n    return 1", "license": "MIT"},
            {"id": "opaque-b", "text": "def b():\n    return 1", "license": "MIT"},
        ],
    )
    _write_jsonl(
        dataset / "units.jsonl",
        [
            {
                "id": "opaque-pair",
                "kind": "pair",
                "item_ids": ["opaque-a", "opaque-b"],
                "task_id": "task",
            }
        ],
    )
    _write_jsonl(dataset / "tasks.jsonl", [{"id": "task", "description": "Return one"}])
    (root / "lens.md").write_text("Judge readability", encoding="utf-8")
    (root / "idiom.md").write_text("Use Python conventions", encoding="utf-8")
    return dataset


def _write_jsonl(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )


def _fake_client(
    root: Path,
    response: str | list[str] = '{"choice":"A","confidence":"medium"}',
) -> tuple[Path, Path, Path, Path, Path, Path, Path]:
    executable = root / "fake-codex"
    count_file = root / "count.txt"
    env_file = root / "environment.json"
    argv_file = root / "argv.txt"
    version_file = root / "version.txt"
    empty_file = root / "empty-workdir.txt"
    prompt_dir = root / "prompts"
    prompt_dir.mkdir()
    if isinstance(response, str):
        response_cases = f"printf '%s' {response!r} > \"$output\""
    else:
        cases = "\n".join(
            f"    {index}) printf '%s' {value!r} > \"$output\" ;;"
            for index, value in enumerate(response, 1)
        )
        response_cases = f'case "$count" in\n{cases}\nesac'
    script = f"""#!/bin/sh
if [ "$1" = "--version" ]; then printf x >> {str(version_file)!r}; \\
    printf '%s\\n' 'fake-codex 9.8.7'; exit 0; fi
count=0
if [ -f {str(count_file)!r} ]; then read count < {str(count_file)!r}; fi
count=$((count + 1))
printf '%s' "$count" > {str(count_file)!r}
unset PWD SHLVL _
/usr/bin/env -u _ > {str(env_file)!r}
printf '%s\\n' "$@" > {str(argv_file)!r}
workdir=''
while [ "$#" -gt 0 ]; do
    if [ "$1" = "-o" ]; then shift; output="$1"; fi
    if [ "$1" = "-C" ]; then shift; workdir="$1"; fi
    shift
done
if [ -z "$(/bin/ls -A "$workdir")" ]; then printf empty >> {str(empty_file)!r}; fi
/bin/cat > {str(prompt_dir)!r}/prompt-"$count".txt
{response_cases}
printf '{{"tokens_in":11,"tokens_out":3,"request_id":"request-%s"}}\\n' "$count"
while IFS= read -r input_line; do :; done
"""
    executable.write_text(script, encoding="utf-8")
    executable.chmod(0o755)
    return (
        executable,
        count_file,
        env_file,
        argv_file,
        prompt_dir,
        version_file,
        empty_file,
    )


def _window(
    root: Path,
    start: str = "2026-10-19T09:00:00Z",
    cap_per_hour: int = 20,
) -> Path:
    path = root / "window.toml"
    end = (
        "2026-10-19T09:00:00Z"
        if start == "2026-10-19T08:00:00Z"
        else "2026-10-19T10:00:00Z"
    )
    path.write_text(
        (
            f'start = "{start}"\nend = "{end}"\n'
            f"cap_per_hour = {cap_per_hour}\n"
            'stop_rule = "stop_on_first_limit_message"\n'
        ),
        encoding="utf-8",
    )
    return path


def _args(root: Path, dataset: Path, executable: Path, *extra: str) -> list[str]:
    return [
        str(dataset),
        "--lens",
        str(root / "lens.md"),
        "--idiom-notes",
        str(root / "idiom.md"),
        "--client-path",
        str(executable),
        "--run-id",
        "test-run",
        *extra,
    ]


def test_dry_run_prints_each_payload_and_never_executes_client(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = _dataset(tmp_path)
    executable, count_file, *_ = _fake_client(tmp_path)

    assert (
        main(_args(tmp_path, dataset, executable, "--dry-run"), clock=lambda: NOW) == 0
    )

    output = capsys.readouterr().out
    assert '"call_count": 4' in output
    assert '"token_estimate_total"' in output
    assert output.count("--- payload") == 4
    assert f"PAIR ID: {opaque_pair_id('opaque-pair')}" in output
    assert not count_file.exists()


@pytest.mark.parametrize(
    ("allow_live", "window", "message"),
    [
        (None, "valid", "VARDE_CALIBRATE_ALLOW_LIVE=1"),
        ("1", None, "explicit --window-file"),
        ("1", "expired", "not current"),
    ],
)
def test_live_run_requires_flag_explicit_window_and_current_time(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    allow_live: str | None,
    window: str | None,
    message: str,
) -> None:
    dataset = _dataset(tmp_path)
    executable, count_file, *_ = _fake_client(tmp_path)
    if allow_live is None:
        monkeypatch.delenv("VARDE_CALIBRATE_ALLOW_LIVE", raising=False)
    else:
        monkeypatch.setenv("VARDE_CALIBRATE_ALLOW_LIVE", allow_live)
    extra = []
    if window:
        extra.extend(
            (
                "--window-file",
                str(
                    _window(
                        tmp_path,
                        "2026-10-19T08:00:00Z"
                        if window == "expired"
                        else "2026-10-19T09:00:00Z",
                    )
                ),
            )
        )

    assert main(_args(tmp_path, dataset, executable, *extra), clock=lambda: NOW) == 1

    assert message in capsys.readouterr().err
    assert not count_file.exists()


def test_live_fake_client_gets_exact_allow_list_and_retries_invalid_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = _dataset(tmp_path)
    executable, count_file, env_file, _, _, version_file, _ = _fake_client(
        tmp_path, "not-json"
    )
    monkeypatch.setenv("VARDE_CALIBRATE_ALLOW_LIVE", "1")
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    monkeypatch.setenv("SHOULD_NOT_PASS", "secret")
    window = _window(tmp_path)

    assert (
        main(
            _args(tmp_path, dataset, executable, "--window-file", str(window)),
            clock=lambda: NOW,
        )
        == 0
    )

    assert count_file.read_text() == "8"  # four calls, each retried once
    assert version_file.read_text() == "x"
    passed = dict(line.split("=", 1) for line in env_file.read_text().splitlines())
    assert passed == {
        "PATH": str(tmp_path),
        "LC_ALL": "C.UTF-8",
        "CODEX_HOME": str(tmp_path / "codex-home"),
    }
    manifest = json.loads((dataset / "runs" / "test-run.json").read_text())
    assert manifest["data_sent"]["pair_ids"] == [opaque_pair_id("opaque-pair")]
    records = [
        json.loads(line)
        for line in (dataset / "runs" / "test-run.jsonl").read_text().splitlines()
    ]
    assert len(records) == 4
    assert all(
        record["parse_ok"] is False and record["retry_count"] == 1 for record in records
    )
    assert all(record["client_version"] == "fake-codex 9.8.7" for record in records)
    assert all(
        record["tokens_in"] == 22 and record["tokens_out"] == 6 for record in records
    )
    assert all(record["request_id"] for record in records)
    assert "SHA-256 hashes" in capsys.readouterr().out


def test_acceptance_runner_uses_six_calls_and_maps_five_of_six(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dataset = _dataset(tmp_path)
    choices = [
        '{"choice":"A","confidence":"high"}',
        '{"choice":"A","confidence":"medium"}',
        '{"choice":"A","confidence":"high"}',
        '{"choice":"B","confidence":"low"}',
        '{"choice":"B","confidence":"medium"}',
        '{"choice":"A","confidence":"low"}',
    ]
    executable, count_file, _, argv_file, prompt_dir, version_file, empty_file = (
        _fake_client(tmp_path, choices)
    )
    monkeypatch.setenv("VARDE_CALIBRATE_ALLOW_LIVE", "1")
    window = _window(tmp_path)

    assert (
        main(
            _args(
                tmp_path,
                dataset,
                executable,
                "--mode",
                "acceptance",
                "--window-file",
                str(window),
            ),
            clock=lambda: NOW,
        )
        == 0
    )

    assert count_file.read_text() == "6"
    assert version_file.read_text() == "x"
    assert empty_file.read_text() == "empty" * 6
    first_prompt = (prompt_dir / "prompt-1.txt").read_text()
    last_prompt = (prompt_dir / "prompt-6.txt").read_text()
    opaque_id = opaque_pair_id("opaque-pair")
    assert f"PAIR ID: {opaque_id}" in first_prompt
    assert "PAIR ID: opaque-pair" not in first_prompt
    assert first_prompt.index("def a") < first_prompt.index("def b")
    assert last_prompt.index("def b") < last_prompt.index("def a")
    argv = argv_file.read_text().splitlines()
    assert argv == [
        "exec",
        "-m",
        "gpt-6-luna",
        "-c",
        'model_reasoning_effort="medium"',
        "-s",
        "read-only",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--skip-git-repo-check",
        "-C",
        argv[argv.index("-C") + 1],
        "--output-schema",
        argv[argv.index("--output-schema") + 1],
        "--json",
        "-o",
        argv[argv.index("-o") + 1],
        "-",
    ]
    assert "SHA-256 hashes" in capsys.readouterr().out

    log_path = dataset / "runs" / "test-run.jsonl"
    records = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert len(records) == 6
    assert records[0]["order"] == "AB" and records[-1]["order"] == "BA"
    assert {record["pair_id"] for record in records} == {opaque_id}
    assert records[0]["lens"] == "lens"
    assert records[0]["client_name"] == "codex"
    assert records[0]["client_version"] == "fake-codex 9.8.7"
    expected_fields = {
        "run_id",
        "pair_id",
        "lens",
        "lens_sha256",
        "idiom_notes_sha256",
        "model_id",
        "provider_version",
        "client_name",
        "client_version",
        "temperature",
        "seed",
        "max_tokens",
        "top_p",
        "thinking_settings",
        "order",
        "seed_index",
        "prompt_sha256",
        "system_prompt_sha256",
        "response_raw",
        "parsed",
        "parse_ok",
        "retry_count",
        "tokens_in",
        "tokens_out",
        "request_id",
        "timestamp",
    }
    assert set(records[0]) == expected_fields
    assert (records[0]["tokens_in"], records[0]["tokens_out"]) == (11, 3)
    assert records[0]["request_id"] == "request-1"
    manifest = json.loads((dataset / "runs" / "test-run.json").read_text())
    assert manifest["verdicts"][opaque_id]["choice"] == "A"
    assert "def a" not in json.dumps(manifest["data_sent"])


def test_runner_excludes_hygiene_hit_and_dry_run_lists_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = _dataset(tmp_path)
    _write_jsonl(
        dataset / "tasks.jsonl", [{"id": "task", "description": "Over_split this"}]
    )
    executable, count_file, *_ = _fake_client(tmp_path)

    assert (
        main(_args(tmp_path, dataset, executable, "--dry-run"), clock=lambda: NOW) == 0
    )

    output = capsys.readouterr().out
    assert '"call_count": 0' in output
    assert "forbidden terminology" in output
    assert not count_file.exists()
    live_args = _args(tmp_path, dataset, executable)[:-2]
    assert main(live_args, clock=lambda: NOW) == 0
    exclusion_log = dataset / "runs" / "rate-20261019T093000Z.json"
    assert json.loads(exclusion_log.read_text())["excluded"][0]["reasons"] == [
        "forbidden terminology"
    ]


def test_runner_refuses_explicit_repeat_count_below_mode_threshold(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = _dataset(tmp_path)
    executable, count_file, *_ = _fake_client(tmp_path)

    assert (
        main(
            _args(
                tmp_path,
                dataset,
                executable,
                "--mode",
                "acceptance",
                "--repeats",
                "2",
                "--dry-run",
            ),
            clock=lambda: NOW,
        )
        == 1
    )

    assert "requires at least 3 repeats" in capsys.readouterr().err
    assert not count_file.exists()


def test_secret_hits_are_excluded_and_abort_flag_fails(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = _dataset(tmp_path)
    records = [
        {
            "id": "opaque-a",
            "text": "API_KEY = 'aB3dE5fG7hJ9kL2mN4pQ6rT8'",
            "license": "MIT",
        },
        {"id": "opaque-b", "text": "def b():\n    return 1", "license": "MIT"},
    ]
    _write_jsonl(dataset / "items.jsonl", records)
    executable, count_file, *_ = _fake_client(tmp_path)

    assert (
        main(_args(tmp_path, dataset, executable, "--dry-run"), clock=lambda: NOW) == 0
    )
    output = capsys.readouterr().out
    assert "secret-like content" in output
    assert '"call_count": 0' in output
    assert (
        main(
            _args(tmp_path, dataset, executable, "--dry-run", "--abort-on-secret"),
            clock=lambda: NOW,
        )
        == 1
    )
    assert "secret-like content" in capsys.readouterr().err
    assert not count_file.exists()


@pytest.mark.parametrize("source", ["task", "lens", "idiom"])
def test_secrets_scan_includes_all_text_sent_to_judge(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    source: str,
) -> None:
    dataset = _dataset(tmp_path)
    credential = "ACCESS_TOKEN = 'aB3dE5fG7hJ9kL2mN4pQ6rT8'"
    if source == "task":
        _write_jsonl(
            dataset / "tasks.jsonl", [{"id": "task", "description": credential}]
        )
    else:
        filename = "lens.md" if source == "lens" else "idiom.md"
        (tmp_path / filename).write_text(credential, encoding="utf-8")
    executable, count_file, *_ = _fake_client(tmp_path)

    assert (
        main(_args(tmp_path, dataset, executable, "--dry-run"), clock=lambda: NOW) == 0
    )

    output = capsys.readouterr().out
    assert "secret-like content" in output
    assert '"call_count": 0' in output
    assert not count_file.exists()


def test_retry_attempts_count_toward_live_cap_and_completed_logs_survive_abort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    dataset = _dataset(tmp_path)
    executable, count_file, *_ = _fake_client(tmp_path, "not-json")
    monkeypatch.setenv("VARDE_CALIBRATE_ALLOW_LIVE", "1")
    window = _window(tmp_path, cap_per_hour=4)

    assert (
        main(
            _args(tmp_path, dataset, executable, "--window-file", str(window)),
            clock=lambda: NOW,
        )
        == 1
    )

    assert "exceed usage window cap_per_hour" in capsys.readouterr().err
    assert count_file.read_text() == "4"
    records = [
        json.loads(line)
        for line in (dataset / "runs" / "test-run.jsonl").read_text().splitlines()
    ]
    assert len(records) == 2


def test_limit_text_in_model_response_is_not_client_limit_signal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    dataset = _dataset(tmp_path)
    response = '{"choice":"tie","confidence":"low","note":"rate limit"}'
    executable, count_file, *_ = _fake_client(tmp_path, response)
    monkeypatch.setenv("VARDE_CALIBRATE_ALLOW_LIVE", "1")

    assert (
        main(
            _args(
                tmp_path, dataset, executable, "--window-file", str(_window(tmp_path))
            ),
            clock=lambda: NOW,
        )
        == 0
    )

    assert count_file.read_text() == "4"


def test_codex_builder_and_unconfigured_clients() -> None:
    command = build_codex_command("/bin/codex", "/empty", "/schema", "/output")

    assert command[:6] == [
        "/bin/codex",
        "exec",
        "-m",
        "gpt-6-luna",
        "-c",
        'model_reasoning_effort="medium"',
    ]
    assert command[-1] == "-"
    with pytest.raises(NotImplementedError, match="not configured"):
        pi_command()
    with pytest.raises(NotImplementedError, match="not configured"):
        claude_code_command()


def test_secret_scan_blocks_common_credentials() -> None:
    assert scan_secrets(["API_KEY = 'aB3dE5fG7hJ9kL2mN4pQ6rT8'"])
    assert scan_secrets(["-----BEGIN PRIVATE KEY-----"])
    assert scan_secrets(["ghp_0123456789abcdefghijklmnopqrstuv"])
    assert scan_secrets(["xox" + "b-" + "0123456789" * 3])
    assert not scan_secrets(["PASSWORD = 'aaaaaaaaaaaaaaaaaaaaaaaa'"])
    assert not scan_secrets(["def calculate(value): return value + 1"])


@pytest.mark.parametrize(
    ("snippet", "error"),
    [("x" * 65_537, "byte transfer limit")],
)
def test_transfer_safeguards_block_payloads_before_client_execution(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    snippet: str,
    error: str,
) -> None:
    dataset = _dataset(tmp_path)
    records = [
        {"id": "opaque-a", "text": snippet, "license": "MIT"},
        {"id": "opaque-b", "text": "def b():\n    return 1", "license": "MIT"},
    ]
    _write_jsonl(dataset / "items.jsonl", records)
    executable, count_file, *_ = _fake_client(tmp_path)

    assert (
        main(_args(tmp_path, dataset, executable, "--dry-run"), clock=lambda: NOW) == 1
    )

    assert error in capsys.readouterr().err
    assert not count_file.exists()
