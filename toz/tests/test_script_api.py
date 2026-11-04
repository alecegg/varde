from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PACKAGE = Path(__file__).parents[1]


def run_cli(
    tmp_path: Path, *args: str, input: str | None = None
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "VARDE_CONFIG_DIR": str(tmp_path / "config"),
            "VARDE_TOZ_CONFIG_DIR": str(tmp_path / "store"),
            "PYTHONPATH": str(PACKAGE / "src"),
        }
    )
    for key in ("HOME", "VARDE_CONFIG_DIR", "VARDE_TOZ_CONFIG_DIR"):
        Path(env[key]).mkdir(parents=True, exist_ok=True)
    return subprocess.run(  # noqa: S603 - Test launches this package's CLI with fixed Python module argv.
        [sys.executable, "-m", "varde_toz.cli", "run", *args],
        cwd=tmp_path,
        env=env,
        input=input,
        text=True,
        capture_output=True,
        check=False,
    )


def test_script_api_print_lines_text_and_handle(tmp_path: Path) -> None:
    result = run_cli(
        tmp_path,
        "--code",
        (
            "print(typeof toz.handle, toz.handle.handle); "
            "toz.eachLine(line => print(line)); print(toz.text())"
        ),
    )
    assert result.returncode == 0
    assert result.stdout == "object \n\n"


def test_script_exception_exit_code_and_help_options(tmp_path: Path) -> None:
    failed = run_cli(tmp_path, "--code", "throw new Error('broken')")
    assert failed.returncode == 1
    assert "script error: Error: broken" in failed.stderr

    help_result = run_cli(tmp_path, "--help")
    assert help_result.returncode == 0
    for flag in (
        "--script",
        "--code",
        "--handle",
        "--stream",
        "--partial",
        "--json",
        "--quiet",
        "--timeout-ms",
        "--memory-mb",
        "--label",
    ):
        assert flag in help_result.stdout


def test_script_record_is_saved(tmp_path: Path) -> None:
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "VARDE_CONFIG_DIR": str(tmp_path / "config"),
            "VARDE_TOZ_CONFIG_DIR": str(tmp_path / "store"),
            "PYTHONPATH": str(PACKAGE / "src"),
        }
    )
    for key in ("HOME", "VARDE_CONFIG_DIR", "VARDE_TOZ_CONFIG_DIR"):
        Path(env[key]).mkdir(parents=True, exist_ok=True)
    capture = subprocess.run(
        [
            sys.executable,
            "-m",
            "varde_toz.cli",
            "capture",
            "--source",
            "fixture",
            "--kind",
            "run",
            "--force",
        ],
        cwd=tmp_path,
        env=env,
        input="first\nsecond\n",
        text=True,
        capture_output=True,
        check=False,
    )
    assert capture.returncode == 0
    handle = capture.stdout.split("handle ", 1)[1].split()[0]
    result = subprocess.run(  # noqa: S603 - Test launches this package's CLI with fixed Python module argv.
        [
            sys.executable,
            "-m",
            "varde_toz.cli",
            "run",
            "--handle",
            handle,
            "--code",
            "toz.record('item', {n: 1}); print('saved')",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stdout == "saved\n"
    from varde_toz.project import project_key
    from varde_toz.store import Store

    database = Path(env["VARDE_TOZ_CONFIG_DIR"]) / project_key(tmp_path) / "toz.db"
    with Store.open(database) as store:
        row = store.get_by_handle(handle)
        assert store.records_for(row["id"], "item") == ['{"n":1}']


def test_script_source_file_stdin_and_small_output_flags(tmp_path: Path) -> None:
    (tmp_path / "script.js").write_text("print('from-file')\n")
    file_result = run_cli(tmp_path, "--script", "script.js")
    assert file_result.returncode == 0
    assert file_result.stdout == "from-file\n"
    stdin_result = run_cli(tmp_path, "--script", "-", input="print('from-stdin')")
    assert stdin_result.returncode == 0
    assert stdin_result.stdout == "from-stdin\n"
    for flag_args in (("--json",), ("--quiet",), ("--label", "explicit")):
        flagged = run_cli(tmp_path, *flag_args, "--code", "print('tiny')")
        assert flagged.returncode == 0
        assert flagged.stdout == "tiny\n"


def test_cli_limit_exit_codes_and_messages(tmp_path: Path) -> None:
    cases = [
        ("--timeout-ms", "25", "while(true){}", 3, "script exceeded 25ms"),
        ("--memory-mb", "8", "let a='x'.repeat(9*1024*1024)", 4, "script exceeded 8MB"),
        (
            None,
            None,
            "print('x'.repeat(1048577))",
            5,
            "script printed more than 1048576 bytes",
        ),
        (
            "--timeout-ms",
            "60000",
            "for(let i=0;i<10001;i++)toz.record('x',i)",
            6,
            "script exceeded the record limit",
        ),
    ]
    for option, value, source, code, message in cases:
        args = ([option, value] if option else []) + ["--code", source]
        result = run_cli(tmp_path, *args)
        assert result.returncode == code
        assert message in result.stderr


def test_trusted_profile_script_runs_in_capture_path(tmp_path: Path) -> None:
    env = os.environ.copy()
    config = tmp_path / "config"
    store_path = tmp_path / "store"
    (config / "toz").mkdir(parents=True)
    profile_text = (
        "[[profile]]\nid='scripted'\nmatch={command='fixture'}\n"
        "script=\"toz.eachLine(line=>toz.record('line',{line})); "
        "print('PROFILE SCRIPT')\"\n"
    )
    (config / "toz" / "profiles.toml").write_text(profile_text)
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "VARDE_CONFIG_DIR": str(config),
            "VARDE_TOZ_CONFIG_DIR": str(store_path),
            "PYTHONPATH": str(PACKAGE / "src"),
        }
    )
    Path(env["HOME"]).mkdir(parents=True)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "varde_toz.cli",
            "capture",
            "--source",
            "fixture",
            "--kind",
            "run",
            "--force",
        ],
        cwd=tmp_path,
        env=env,
        input="alpha\nbeta\n",
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert "PROFILE SCRIPT" in result.stdout


def test_exec_shell_uses_original_text_for_profile_matching(tmp_path: Path) -> None:
    env = os.environ.copy()
    config = tmp_path / "config"
    store_path = tmp_path / "store"
    (config / "toz").mkdir(parents=True)
    profile_text = (
        "[[profile]]\nid='fixture-records'\nmatch={command='fixture-records'}\n"
        "script=\"toz.eachLine(line=>toz.record('line',{line})); "
        "print('FIXTURE PROFILE')\"\n"
        "[[profile]]\nid='exact-shell'\nmatch={command='printf profile-lines'}\n"
        "script=\"toz.eachLine(line=>toz.record('line',{line})); "
        "print('PROFILE SCRIPT')\"\n"
    )
    (config / "toz" / "profiles.toml").write_text(profile_text)
    env.update(
        {
            "HOME": str(tmp_path / "home"),
            "VARDE_CONFIG_DIR": str(config),
            "VARDE_TOZ_CONFIG_DIR": str(store_path),
            "PYTHONPATH": str(PACKAGE / "src"),
        }
    )
    Path(env["HOME"]).mkdir(parents=True)
    result = subprocess.run(  # noqa: S603 - Test launches this package's CLI with fixed Python module argv.
        [
            sys.executable,
            "-m",
            "varde_toz.cli",
            "run",
            "--project",
            str(tmp_path),
            "--code",
            (
                "const r=toz.exec({shell:'printf profile-lines',capture:true}); "
                "print(r.exitCode,r.stdout,r.capture.state,'handle',r.capture.handle)"
            ),
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    fields = result.stdout.split()
    assert fields[:3] == ["0", "profile-lines", "captured"]
    handle = fields[4]
    from varde_toz.project import project_key
    from varde_toz.store import Store

    database = Path(env["VARDE_TOZ_CONFIG_DIR"]) / project_key(tmp_path) / "toz.db"
    with Store.open(database) as store:
        row = store.get_by_handle(handle)
        assert store.records_for(row["id"], "line") == ['{"line":"profile-lines"}']


def test_exec_status_timeout_and_streams(tmp_path: Path) -> None:
    result = run_cli(
        tmp_path,
        "--code",
        (
            "const r=toz.exec({argv:['python3','-c',\"import os; "
            "os.write(1,b'o'*20000); os.write(2,b'e'*20000)\"]}); "
            "print(r.exitCode, r.stdout === 'o'.repeat(20000), "
            "r.stderr === 'e'.repeat(20000))"
        ),
    )
    assert result.returncode == 0
    assert result.stdout == "0 true true\n"

    result = run_cli(
        tmp_path,
        "--code",
        (
            "const r=toz.exec({argv:['sh','-c','printf problem >&2; exit 7']}); "
            "print(r.exitCode,r.stderr)"
        ),
    )
    assert result.returncode == 0
    assert result.stdout == "7 problem\n"

    result = run_cli(
        tmp_path,
        "--code",
        (
            "const r=toz.exec({argv:['sh','-c','sleep 1'],timeoutMs:50}); "
            "print(r.timedOut)"
        ),
        "--timeout-ms",
        "2000",
    )
    assert result.returncode == 0
    assert result.stdout == "true\n"


def test_exec_threshold_capture_and_raw_option(tmp_path: Path) -> None:
    config = tmp_path / "store"
    config.mkdir(exist_ok=True)
    (config / "config.toml").write_text("threshold = 20\n[raw]\nenabled = true\n")
    inline = run_cli(
        tmp_path,
        "--code",
        (
            "const r=toz.exec({shell:'printf ab; printf cd >&2'}); "
            "print(r.capture.state,r.stdout==='ab',r.stderr==='cd')"
        ),
    )
    assert inline.returncode == 0
    assert inline.stdout == "inline true true\n"
    captured = run_cli(
        tmp_path,
        "--code",
        (
            "const r=toz.exec({shell:'printf 123456789012345; "
            "printf 1234567890 >&2'}); print(r.capture.state)"
        ),
    )
    assert captured.returncode == 0
    assert captured.stdout == "captured\n"
    raw = run_cli(
        tmp_path,
        "--code",
        ("const r=toz.exec({shell:'printf raw-bytes',raw:true}); print(r.raw.state)"),
    )
    assert raw.returncode == 0
    assert raw.stdout == "stored\n"


def test_exec_raw_disabled_returns_state_without_failing(tmp_path: Path) -> None:
    result = run_cli(
        tmp_path,
        "--code",
        (
            "const r=toz.exec({shell:'printf raw',raw:true}); "
            "print(r.exitCode,r.stdout,r.raw.state)"
        ),
    )
    assert result.returncode == 0
    assert result.stdout == "0 raw disabled\n"


def test_cli_rejects_negative_resource_limits(tmp_path: Path) -> None:
    cases = (
        ("--timeout-ms=-1", "print('must not run')"),
        ("--memory-mb=-1", "let a=[]; for(let i=0;i<3000000;i++)a.push(i)"),
    )
    for option, source in cases:
        result = run_cli(tmp_path, "--code", source, option)
        assert result.returncode == 2
        assert result.stdout == ""


def test_exec_large_output_returns_capture_handle(tmp_path: Path) -> None:
    result = run_cli(
        tmp_path,
        "--code",
        (
            "const r=toz.exec({shell:'yes x | head -c 70000'}); "
            "print(r.truncated,r.capture.state,r.capture.handle)"
        ),
    )
    assert result.returncode == 0
    fields = result.stdout.split()
    assert fields[:2] == ["true", "captured"]
    assert len(fields[2]) >= 4
