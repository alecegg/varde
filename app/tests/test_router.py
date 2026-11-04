import json
import subprocess
import sys
from pathlib import Path

from varde.router import denied_route, resolve
from varde.routes import ROUTES


def _resolved(argv):
    result = resolve(argv)
    assert result is not None
    return result


def test_advertised_setup_help_paths_resolve_and_migrations_do_not() -> None:
    command = [
        sys.executable,
        "-c",
        "from varde.cli import main; raise SystemExit(main())",
    ]
    for path in (
        ("setup", "sync"),
        ("setup", "hooks", "install"),
        ("setup", "hooks", "remove"),
    ):
        result = subprocess.run(
            [*command, *path, "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert "Usage:" in result.stdout

    intentionally_unrouted = {
        ("setup", "migrate-metadata"),
        ("setup", "migrate-session-notes"),
    }
    assert all(
        not any(route.path[: len(path)] == path for route in ROUTES)
        for path in intentionally_unrouted
    )


def test_routes_include_supported_paths_and_drop_migrate_routes():
    paths = {route.path for route in ROUTES}
    assert ("scan", "rules", "diff") in paths
    assert ("setup", "migrate-metadata") not in paths
    assert ("setup", "migrate-session-notes") not in paths
    assert "migrate-metadata" in next(r for r in ROUTES if r.path == ("run",)).deny


def test_longest_route_preserves_legacy_arguments():
    route, forwarded = _resolved(["scan", "rules", "list", "--json", "{}"])
    assert route.path == ("scan", "rules", "list")
    assert route.module == "code"
    assert forwarded == ["varde scan rules", "rules_list", "--json", "{}"]


def test_deny_word_prevents_parent_route():
    assert resolve(["run", "migrate-metadata"]) is None


def test_app_owned_deny_words_do_not_resolve_as_commands():
    for route in ROUTES:
        child_names = {
            child.path[len(route.path)]
            for child in ROUTES
            if len(child.path) > len(route.path)
            and child.path[: len(route.path)] == route.path
        }
        for word in route.deny:
            if word in child_names:
                continue
            assert resolve([*route.path, word]) is None
            assert denied_route([*route.path, word]) == (route, word)


def test_scan_deny_words_resolve_to_expected_commands():
    expected = {
        ("scan", "test"): ["varde scan", "test"],
        ("scan", "setup"): ["varde scan", "scan"],
        ("scan", "rules"): None,
    }
    for words, forwarded in expected.items():
        resolved = resolve([*words])
        if forwarded is None:
            assert resolved is None
            continue
        assert resolved is not None
        route, actual = resolved
        assert route.module == "code"
        assert actual == forwarded


def test_plan_route_passes_the_plan_group_to_workflow_module():
    route, forwarded = _resolved(["plan", "queue", "check", "plan-dir"])

    assert route.module == "workflow"
    assert forwarded == ["plan", "queue", "check", "plan-dir"]


def test_hidden_aliases_forward_the_alias_as_legacy_command():
    route, forwarded = _resolved(["capture", "--hook", "post-tool-use"])
    assert route.hidden
    assert route.module == "toz"
    assert forwarded == ["varde", "capture", "--hook", "post-tool-use"]


def test_rules_diff_rewrites_id_to_json_and_preserves_tail():
    route, forwarded = _resolved(["scan", "rules", "diff", "no-console", "--force"])
    assert route.module == "code"
    assert forwarded[:3] == ["varde scan rules", "rules_list", "--json"]
    assert json.loads(forwarded[3]) == {
        "repoRoot": ".",
        "operation": "diff",
        "ruleId": "no-console",
    }
    assert forwarded[4:] == ["--force"]


def test_scan_setup_json_rewrite_adds_operation_and_scope():
    route, forwarded = _resolved(
        ["scan", "setup", "--json", '{"repoRoot":"/repo"}', "--user", "--force"]
    )
    assert route.module == "code"
    assert forwarded[:2] == ["varde scan", "scan"]
    assert forwarded[2] == "--json"
    assert json.loads(forwarded[3]) == {
        "repoRoot": "/repo",
        "operation": "setup",
        "scope": "user",
    }
    assert forwarded[4:] == ["--force"]


def test_scan_setup_rewrite_keeps_unicode_and_rejects_non_json_constants():
    _, forwarded = _resolved(["scan", "setup", "--json", '{"repoRoot":"/café"}'])
    assert forwarded[3] == '{"operation":"setup","repoRoot":"/café"}'

    args = ["scan", "setup", "--json", '{"repoRoot":NaN}']
    _, forwarded = _resolved(args)
    assert forwarded == ["varde scan", "scan", *args[2:]]


def test_scan_setup_help_does_not_rewrite():
    route, forwarded = _resolved(["scan", "setup", "--help"])
    assert route.module == "code"
    assert forwarded == ["varde scan", "scan", "--help"]


def test_seed_rule_id_moves_into_json():
    route, forwarded = _resolved(
        [
            "scan",
            "rules",
            "seed",
            "--json",
            '{"repoRoot":"/repo"}',
            "--rule-id",
            "no-console",
            "--force",
        ]
    )
    assert route.module == "code"
    assert forwarded[:3] == ["varde scan rules", "rules_seed", "--json"]
    assert json.loads(forwarded[3]) == {"repoRoot": "/repo", "ruleId": "no-console"}
    assert forwarded[4:] == ["--force"]


def test_invalid_rewrite_input_is_passed_through():
    _, forwarded = _resolved(["scan", "setup", "--json", "[]"])
    assert forwarded == ["varde scan", "scan", "--json", "[]"]


def test_watch_alias_and_setup_path_route_to_code_watch():
    expected = (
        (["watch", "--list"], ["varde", "watch", "--list"]),
        (["setup", "watch", "--list"], ["varde setup", "watch", "--list"]),
    )
    for args, forwarded_expected in expected:
        route, forwarded = _resolved(args)
        assert route.module == "code"
        assert forwarded == forwarded_expected


def test_toz_worker_reexec_route_preserves_run_arguments():
    args = [
        "run",
        "--project",
        "/repo",
        "--json",
        "run",
        "--code",
        "print('worker-ok')",
    ]
    route, forwarded = _resolved(args)
    assert route.module == "toz"
    assert forwarded == ["varde run", *args[1:]]


def test_map_build_and_query_route_to_code_with_original_arguments():
    for args in (
        ["map", "build", "--repo-root", "/repo"],
        [
            "map",
            "symbols_in_file",
            "--json",
            '{"repoRoot":"/repo","filePath":"src/lib.rs"}',
        ],
    ):
        route, forwarded = _resolved(args)
        assert route.module == "code"
        assert forwarded == ["varde map", *args[1:]]


def test_cli_help_and_unknown_command_outputs():
    command = [
        sys.executable,
        "-c",
        "from varde.cli import main; raise SystemExit(main())",
    ]
    known = subprocess.run(
        [*command, "map", "--help"], capture_output=True, text=True, check=False
    )
    assert known.returncode == 0
    assert known.stdout.startswith("Query the code index")
    assert "Usage:" in known.stdout
    assert "build" in known.stdout

    unknown = subprocess.run(
        [*command, "not-a-command"], capture_output=True, text=True, check=False
    )
    assert unknown.returncode == 2
    assert "not-a-command" in unknown.stderr

    version = subprocess.run(
        [*command, "--version"], capture_output=True, text=True, check=False
    )
    assert version.returncode == 0
    assert version.stdout.startswith("varde ")


def test_quality_baseline_ui_routes_to_code() -> None:
    for argv in (("quality", "baseline", "ui"), ("code", "quality", "baseline", "ui")):
        route, forwarded = _resolved(argv)
        assert route.module == "code"
        assert forwarded[-3:] == ["quality", "baseline", "ui"] or forwarded[-2:] == [
            "baseline",
            "ui",
        ]


def test_quality_commands_route_through_real_cli(tmp_path: Path):
    command = [
        sys.executable,
        "-c",
        "from varde.cli import main; raise SystemExit(main())",
    ]
    for path, program in (
        (("score", "--help"), "varde code score"),
        (("code", "score", "--help"), "varde code score"),
        (("samples", "--help"), "varde code samples"),
        (("code", "samples", "--help"), "varde code samples"),
        (("quality", "baseline", "--help"), "varde code quality baseline"),
        (("code", "quality", "baseline", "--help"), "varde code quality baseline"),
    ):
        result = subprocess.run(
            [*command, *path], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr
        assert "usage:" in result.stdout.lower()
        assert program in result.stdout

    facts = tmp_path / "facts.jsonl"
    facts.write_text(
        json.dumps(
            {
                "contract": "facts-2",
                "path": "src/example.py",
                "language": "python",
                "tokens": 10,
                "structure_confidence": "normal",
                "functions": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    calibration = (
        Path(__file__).parents[2]
        / "code/src/varde_code/quality_score/calibration/placeholder.toml"
    )
    score = subprocess.run(
        [
            *command,
            "score",
            "--facts",
            str(facts),
            "--calibration",
            str(calibration),
            "--json",
            "--debug",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert score.returncode == 0, score.stderr
    assert json.loads(score.stdout)["files"][0]["path"] == "src/example.py"

    default_view = subprocess.run(
        [*command, "score", "--facts", str(facts), "--calibration", str(calibration)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert default_view.returncode == 0, default_view.stderr
    assert default_view.stdout.strip()

    root_help = subprocess.run(
        [*command, "--help"], capture_output=True, text=True, check=False
    )
    assert root_help.returncode == 0
    assert "score" in root_help.stdout
    assert "samples" in root_help.stdout
