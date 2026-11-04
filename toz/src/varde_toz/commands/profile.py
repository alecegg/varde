"""List output profiles and run their embedded test cases."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import tomllib
from dataclasses import asdict
from pathlib import Path

from varde_toz.capture import CaptureInput, capture
from varde_toz.profile import Scope, load_file, load_profiles
from varde_toz.store import Store

from ._maintenance import current_project, error, json_enabled

HELP_LIST = "List loaded profiles (id, scope, file, has_script) and load diagnostics"
HELP_TEST = "Run each profile's `[[profile.test]]` cases against an in-memory store"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--fallback-dir")
    parser.add_argument("--project")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    subparsers = parser.add_subparsers(dest="action", required=True)
    subparsers.add_parser("list", add_help=False)
    test = subparsers.add_parser("test", add_help=False)
    test.add_argument("--file", type=Path)
    for subparser in (subparsers.choices["list"], test):
        subparser.add_argument("--fallback-dir", default=argparse.SUPPRESS)
        subparser.add_argument("--project", default=argparse.SUPPRESS)
        subparser.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
        subparser.add_argument(
            "--quiet", action="store_true", default=argparse.SUPPRESS
        )
    return parser


def _summary(profile) -> dict:
    return {
        "id": profile.id,
        "scope": str(profile.scope),
        "file": "<builtin>" if profile.scope is Scope.BUILTIN else str(profile.file),
        "has_script": profile.script is not None,
    }


def _source(profile) -> str | None:
    if profile.match_pattern is None:
        return None
    try:
        root = tomllib.loads(profile.file.read_text())
    except OSError, tomllib.TOMLDecodeError:
        return None
    for entry in root.get("profile", []):
        if isinstance(entry, dict) and entry.get("id") == profile.id:
            match = entry.get("match")
            if isinstance(match, dict):
                return match.get("command") or match.get("source")
    return None


def _run_case(config: dict, profiles: list, profile, case) -> dict:
    def failed(reason: str) -> dict:
        return {
            "profile_id": profile.id,
            "name": case.name,
            "passed": False,
            "reason": reason,
        }

    source = _source(profile)
    if source is None:
        return failed("profile has no `match`; cannot select it for a test case")
    root = Path(tempfile.mkdtemp(prefix="varde-profile-test-"))
    config_dir_path = root / "varde-config"
    path = root / "toz.db"
    try:
        profiles_root = root / "project"
        profiles_root.mkdir()
        if profile.scope is Scope.PROJECT:
            profiles_dir = profiles_root / ".varde"
            profiles_dir.mkdir()
            profiles_path = profiles_dir / "toz-profiles.toml"
            profiles_path.write_text(profile.file.read_text())
        elif profile.file != Path("<builtin>"):
            profiles_dir = config_dir_path / "toz"
            profiles_dir.mkdir(parents=True)
            profiles_path = profiles_dir / "profiles.toml"
            profiles_path.write_text(profile.file.read_text())
        with tempfile.TemporaryDirectory(
            prefix="varde-profile-config-"
        ) as temporary_config:
            if profile.scope is Scope.PROJECT:
                config_root = temporary_config
            elif profile.file != Path("<builtin>"):
                config_root = str(config_dir_path)
            else:
                config_root = temporary_config
            previous = os.environ.get("VARDE_CONFIG_DIR")
            os.environ["VARDE_CONFIG_DIR"] = config_root
            try:
                capture_result = capture(
                    CaptureInput(
                        case.input.encode(),
                        label=profile.id,
                        source=source,
                        kind="run",
                        force=True,
                    ),
                    root=profiles_root,
                    store_path=path,
                )
                status, preview = capture_result.status, capture_result.output
            finally:
                if previous is None:
                    os.environ.pop("VARDE_CONFIG_DIR", None)
                else:
                    os.environ["VARDE_CONFIG_DIR"] = previous
        if not status:
            return failed("capture was not stored (stayed under threshold)")
        missing = [
            f"preview missing {json.dumps(item, ensure_ascii=False)}"
            for item in case.expect_preview_contains
            if item not in preview
        ]
        if case.expect_records is not None:
            try:
                expected = case.expect_records
                with Store.open(path) as store:
                    row = store.conn.execute(
                        "SELECT id FROM captures ORDER BY id DESC LIMIT 1"
                    ).fetchone()
                    if row is None:
                        return failed("no capture row found for handle")
                    if not isinstance(expected, dict):
                        return failed("expect_records is not a table")
                    for kind, wanted in expected.items():
                        got = [
                            json.loads(value)
                            for value in store.records_for(row[0], kind)
                        ]
                        if got != wanted:
                            missing.append(
                                f"records[{kind}]: expected "
                                f"{json.dumps(wanted, separators=(',', ':'))}, "
                                f"got {json.dumps(got, separators=(',', ':'))}"
                            )
            except (OSError, ValueError) as exc:
                return failed(f"capture failed: {exc}")
        if missing:
            return failed("; ".join(missing))
    except (OSError, ValueError, RuntimeError) as exc:
        return failed(f"capture failed: {exc}")
    else:
        return {
            "profile_id": profile.id,
            "name": case.name,
            "passed": True,
            "reason": None,
        }
    finally:
        import shutil

        shutil.rmtree(root, ignore_errors=True)


def _help(action: str | None) -> str:
    common = (
        "Options:\n"
        "      --fallback-dir <FALLBACK_DIR>  External store to try after "
        "primary-store access fails\n"
        "      --project <PROJECT>            Project directory (default: "
        "git root of cwd, else cwd)\n"
        "      --json                         Machine-readable JSON output\n"
        "      --quiet                        Print only the handle line on overflow\n"
        "  -h, --help                         Print help\n"
    )
    if action == "list":
        return f"{HELP_LIST}\n\nUsage: varde setup profile list [OPTIONS]\n\n{common}"
    if action == "test":
        options = common.replace(
            "      --project <PROJECT>",
            (
                "      --file <FILE>                  Load only this file's "
                "profiles (as user scope, so scripts run) instead of every "
                "scope\n      --project <PROJECT>"
            ),
            1,
        )
        return f"{HELP_TEST}\n\nUsage: varde setup profile test [OPTIONS]\n\n{options}"
    return (
        "Inspect output profiles loaded from built-in, user, and project scopes\n\n"
        "Usage: varde setup profile [OPTIONS] <COMMAND>\n\n"
        "Commands:\n"
        "  list  List loaded profiles (id, scope, file, has_script) and "
        "load diagnostics\n"
        "  test  Run each profile's `[[profile.test]]` cases against an "
        "in-memory store\n"
        "  help  Print this message or the help of the given subcommand(s)\n\n"
        f"{common}"
    )


def main(argv: list[str] | None = None) -> int:
    values = sys.argv[1:] if argv is None else argv
    if "--help" in values or "-h" in values:
        action = next((value for value in values if value in ("list", "test")), None)
        print(_help(action), end="")
        return 0
    try:
        args = _parser().parse_args(values)
        root = current_project(args.project)
        if args.action == "list":
            profiles, diagnostics = load_profiles(root)
            summaries = [_summary(profile) for profile in profiles]
            if json_enabled(args):
                print(
                    json.dumps(
                        {
                            "profiles": summaries,
                            "diagnostics": [asdict(item) for item in diagnostics],
                        },
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                )
            else:
                if not summaries:
                    print("varde-toz: no profiles loaded")
                for item in summaries:
                    suffix = "  (script)" if item["has_script"] else ""
                    print(f"{item['id']}  [{item['scope']}]  {item['file']}{suffix}")
                for item in diagnostics:
                    pid = f"{item.profile_id} " if item.profile_id else ""
                    print(f"warning: {pid}{item.file}: {item.reason}")
            return 0
        profiles, diagnostics = (
            load_file(args.file) if args.file else load_profiles(root)
        )
        if args.file:
            profiles = [
                profile for profile in profiles if profile.scope is not Scope.BUILTIN
            ]
        results = [
            _run_case({}, profiles, profile, case)
            for profile in profiles
            for case in profile.tests
        ]
        if json_enabled(args):
            print(
                json.dumps(
                    {
                        "results": results,
                        "diagnostics": [asdict(item) for item in diagnostics],
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
        else:
            if not results:
                print("varde-toz: no profile test cases")
            for result in results:
                if result["passed"]:
                    print(f"pass: {result['profile_id']} / {result['name']}")
                else:
                    print(
                        f"FAIL: {result['profile_id']} / {result['name']}: "
                        f"{result['reason'] or 'unknown failure'}"
                    )
            for item in diagnostics:
                pid = f"{item.profile_id} " if item.profile_id else ""
                print(f"warning: {pid}{item.file}: {item.reason}")
        return int(any(not result["passed"] for result in results))
    except (OSError, ValueError) as exc:
        return error(str(exc))
