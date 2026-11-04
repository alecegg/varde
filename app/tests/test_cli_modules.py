"""Exercise routed modules through the real application entry point."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def run_cli(
    tmp_path: Path,
    args: list[str],
    *,
    input_text: str | None = None,
    project: bool = False,
    hide_codex: bool = False,
    installed_entrypoint: bool = False,
):
    env = os.environ.copy()
    env.pop("VARDE_WORKING_DIR", None)
    for key in tuple(env):
        if key.startswith("PASEO_AGENT_"):
            env.pop(key)
    env.update(
        HOME=str(tmp_path / "home"),
        XDG_CONFIG_HOME=str(tmp_path / "config"),
        XDG_DATA_HOME=str(tmp_path / "data"),
        XDG_STATE_HOME=str(tmp_path / "state"),
        VARDE_CONFIG_DIR=str(tmp_path / "varde-config"),
        VARDE_TOZ_CONFIG_DIR=str(tmp_path / "toz-config"),
        TOZ_CONFIG_DIR=str(tmp_path / "toz-config"),
        VARDE_KNOWLEDGE_DIR=str(tmp_path / "knowledge"),
        VARDE_LEARN_STORE=str(tmp_path / "learn-store"),
    )
    if hide_codex:
        empty_path = tmp_path / "empty-path"
        empty_path.mkdir(exist_ok=True)
        env["PATH"] = str(empty_path)
    for key in (
        "HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_STATE_HOME",
        "VARDE_CONFIG_DIR",
        "VARDE_TOZ_CONFIG_DIR",
        "VARDE_KNOWLEDGE_DIR",
        "VARDE_LEARN_STORE",
    ):
        Path(env[key]).mkdir(parents=True, exist_ok=True)
    if installed_entrypoint:
        env["VARDE_WORKING_DIR"] = str(tmp_path / "working")
        Path(env["VARDE_WORKING_DIR"]).mkdir(parents=True, exist_ok=True)
    cwd = tmp_path / "cwd"
    cwd.mkdir(exist_ok=True)
    if project:
        subprocess.run(["git", "init", "-q", str(cwd)], check=True)  # noqa: S603, S607 - test initializes local fixture repo
    command = (
        [str(Path(sys.executable).with_name("varde"))]
        if installed_entrypoint
        else [
            sys.executable,
            "-c",
            "from varde.cli import main; raise SystemExit(main())",
        ]
    )
    result = subprocess.run(  # noqa: S603 - test runs isolated CLI subprocess
        [*command, *args],
        cwd=cwd,
        env=env,
        input=input_text,
        text=True,
        capture_output=True,
        check=False,
    )
    assert "Traceback" not in result.stderr
    return result


def test_installed_entrypoint_runs_plan_queue_check(tmp_path: Path) -> None:
    plan = tmp_path / "working" / "plans" / "plan"
    (plan / "tasks").mkdir(parents=True)
    (plan / "notes").mkdir()
    (plan / "plan.md").write_text("---\nid: cli-test\n---\n", encoding="utf-8")
    (plan / "tasks" / "first.md").write_text(
        "---\nid: first\nstatus: todo\nowns: [runner/example.py]\n"
        "depends_on: []\n---\n",
        encoding="utf-8",
    )
    (plan / "notes" / "queue.md").write_text(
        "first | fix:no | esc:0 | worktree:-\n", encoding="utf-8"
    )

    result = run_cli(
        tmp_path,
        ["plan", "queue", "check", str(plan / "plan.md")],
        installed_entrypoint=True,
    )

    assert_cli_success(result, "first ready (todo) esc=0 worktree=-")


def assert_cli_success(result, fragment: str | None = None) -> None:
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()
    if fragment is not None:
        assert fragment in result.stdout


@pytest.mark.parametrize(
    ("args", "fragment"),
    [
        (["plan", "status"], "No plans in a non-terminal status."),
        (["plan", "validate", "--help"], "Usage: varde plan validate"),
        (["msg", "send", "--help"], "Usage: varde msg send"),
        (
            ["learn", "knowledge", "search", "--bundle", "{bundle}", "--json"],
            '"data":[]',
        ),
        (["learn", "knowledge", "lint", "--bundle", "{bundle}", "--json"], '"data":[]'),
        (["setup", "paths", "--json"], '"working":'),
        (["setup", "instructions", "--help"], "Install or remove"),
        (["learn", "check", "--help"], "Usage: varde learn check"),
        (["learn", "docs", "spec", "--help"], "Classify domain specifications"),
        (
            ["learn", "measure", "x", "flow", "--help"],
            "Map how a skill loads its files",
        ),
        (["learn", "friction", "list"], "No friction items found."),
        (["map", "--help"], "Query the code index"),
        (["scan", "--help"], "Scan built-in"),
        (["scan", "rules", "list", "--json", '{"repoRoot":"."}'], '"data"'),
        (["scan", "setup", "--json", '{"repoRoot":".","preset":"balanced"}'], '"data"'),
        (["search", "needle", "--in", "code"], "index_missing"),
        (
            ["map", "context_pack", "--json", '{"repoRoot":".","query":"needle"}'],
            '"data"',
        ),
        (["setup", "profiles", "list", "--json"], '"profiles":['),
        (["setup", "doctor"], "all good"),
        (["run", "--help"], "Capture, query and index command output"),
        (["hook", "--help"], "Usage: varde hook"),
    ],
)
def test_cli_routes_to_modules_in_temp_user_environment(
    tmp_path: Path, args: list[str], fragment: str
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    command = [str(bundle) if arg == "{bundle}" else arg for arg in args]

    assert_cli_success(
        run_cli(tmp_path, command, hide_codex=args == ["setup", "doctor"]), fragment
    )


def test_cli_msg_read_in_configured_project_returns_empty_messages(
    tmp_path: Path,
) -> None:
    assert_cli_success(
        run_cli(tmp_path, ["msg", "read", "--json"], project=True),
        '"messages":[]',
    )


@pytest.mark.parametrize("args", [["msg", "read"], ["msg", "read", "--json"]])
def test_cli_msg_read_without_project_refuses_cwd_fallback(
    tmp_path: Path, args: list[str]
) -> None:
    result = run_cli(tmp_path, args)

    assert result.returncode == 2
    assert "message store resolution fell back to cwd" in result.stderr
    assert "set VARDE_WORKING_DIR or run `varde setup paths set`" in result.stderr


def test_real_cli_learn_friction_subcommands_use_system_stream_fallbacks(
    tmp_path: Path,
) -> None:
    assert_cli_success(
        run_cli(tmp_path, ["learn", "friction", "--help"]),
        "Usage: varde learn friction",
    )
    assert_cli_success(
        run_cli(tmp_path, ["learn", "friction", "list", "--status", "open"]),
        "No friction items found.",
    )

    added = run_cli(
        tmp_path,
        [
            "learn",
            "friction",
            "add",
            "--source",
            "cli-test",
            "--title",
            "Stream fallback",
            "--json",
        ],
        input_text="Initial evidence from stdin.\n",
    )
    assert_cli_success(added, '"data"')
    item_id = str(json.loads(added.stdout)["data"]["id"])

    listed = run_cli(
        tmp_path,
        [
            "learn",
            "friction",
            "list",
            "--status",
            "open",
            "--text",
            "Stream fallback",
            "--json",
        ],
    )
    assert_cli_success(listed, item_id)
    assert_cli_success(
        run_cli(tmp_path, ["learn", "friction", "show", item_id]),
        "Initial evidence from stdin.",
    )
    assert_cli_success(
        run_cli(
            tmp_path,
            [
                "learn",
                "friction",
                "add",
                "--item",
                item_id,
                "--text",
                "Follow-up evidence",
                "--json",
            ],
        ),
        '"data"',
    )
    assert_cli_success(
        run_cli(
            tmp_path,
            [
                "learn",
                "friction",
                "set-status",
                "--reason",
                "resolved in CLI test",
                item_id,
                "resolved",
            ],
        ),
        "[resolved]",
    )
    assert_cli_success(
        run_cli(tmp_path, ["learn", "friction", "list", "--status", "resolved"]),
        "Stream fallback",
    )

    exported = tmp_path / "exported"
    assert_cli_success(
        run_cli(tmp_path, ["learn", "friction", "export", str(exported)]),
        "Exported 1 friction items",
    )
    assert_cli_success(
        run_cli(
            tmp_path,
            [
                "learn",
                "friction",
                "import",
                "--repository",
                str(tmp_path / "cwd"),
                "--dry-run",
                str(exported),
                "--json",
            ],
        ),
        '"data"',
    )


def test_real_cli_learn_diagnose_commands_print_without_stream_capabilities(
    tmp_path: Path,
) -> None:
    assert_cli_success(
        run_cli(
            tmp_path,
            [
                "learn",
                "sessions",
                "show",
                "--harness",
                "codex",
                "--repository",
                str(tmp_path / "cwd"),
                "--json",
            ],
        ),
        '"data"',
    )
    from varde_learn.loop.diagnose.snapshot import snapshot_document, write_snapshot

    record = {"anchor": {"record_index": 0}, "session_thread_id": "thread"}
    snapshot = snapshot_document(
        {
            "session": {"harness": "codex", "thread_id": "thread"},
            "children": [],
            "sources": [],
            "records": [record],
            "overlap": "not_current",
            "coverage": {"truncated": False, "record_count": 1},
            "snapshot": {"digest": ""},
        }
    )
    snapshot_path = tmp_path / "snapshot.json"
    write_snapshot(snapshot_path, snapshot)
    assert_cli_success(
        run_cli(
            tmp_path,
            [
                "learn",
                "sessions",
                "show",
                "--snapshot-in",
                str(snapshot_path),
                "--json",
            ],
        ),
        '"records"',
    )
    assert_cli_success(
        run_cli(tmp_path, ["learn", "sessions", "capture", "--help"]),
        "Usage: varde learn sessions capture",
    )
    assert_cli_success(
        run_cli(tmp_path, ["learn", "measure", "x", "output", "--help"]),
        "Usage: varde learn measure <SKILL> output",
    )


def test_real_cli_learn_check_prints_from_a_temporary_document(tmp_path: Path) -> None:
    document = tmp_path / "notes.md"
    document.write_text("# Notes\n\nA short temporary document.\n")
    assert_cli_success(
        run_cli(tmp_path, ["learn", "check", str(document), "--json"]),
        '"ok":true',
    )


def test_real_cli_toz_capture_reads_stdin_in_a_temporary_store(tmp_path: Path) -> None:
    captured = run_cli(
        tmp_path,
        ["capture", "--force", "--json"],
        input_text="Captured through the routed CLI.\n",
    )
    assert_cli_success(captured, '"preview"')


@pytest.mark.parametrize("subcommand", ["read", "send"])
def test_plan_rejects_msg_only_subcommands(subcommand: str, tmp_path: Path) -> None:
    result = run_cli(tmp_path, ["plan", subcommand])
    assert result.returncode == 2
    assert f"unrecognized subcommand '{subcommand}'" in result.stderr
    assert "Traceback" not in result.stderr


def test_real_cli_code_and_edit_non_help_routes(tmp_path: Path) -> None:
    query = run_cli(
        tmp_path,
        [
            "map",
            "context_pack",
            "--json",
            json.dumps({"repoRoot": str(tmp_path / "cwd"), "query": "needle"}),
        ],
    )
    assert_cli_success(query, '"data"')

    preview = run_cli(tmp_path, ["edit", "preview"])
    assert preview.returncode != 0
    assert "usage: varde edit preview" in preview.stderr.lower()
    assert "Traceback" not in preview.stderr


def test_real_cli_setup_autosave_usage_is_routed(tmp_path: Path) -> None:
    result = run_cli(tmp_path, ["setup", "autosave"])
    assert result.returncode != 0
    assert "usage:" in result.stderr.lower()
    assert "Traceback" not in result.stderr


def test_real_cli_runner_usage_is_routed(tmp_path: Path) -> None:
    result = run_cli(tmp_path, ["runner"])
    assert result.returncode != 0
    assert "usage:" in result.stderr.lower()
