"""Small compatibility steps retained by setup sync."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from varde_learn.knowledge.memory_config import load_config, save_config
from varde_toz.config import resolve_config_dir, varde_toz_dir
from varde_toz.install import retire_owned_files

from varde import json_order

from .. import repo_map_step
from ..hooks_install.common import write_atomic
from .report import MigrateEnv, Report, ReportEntry


def _defaults_table(value: object) -> dict:
    if not isinstance(value, dict):
        raise ValueError("[default] config must be a table")
    return value


def instruction_sections(features: set[str]) -> list[str]:
    return [
        section
        for feature, section in (
            ("change", "orchestration"),
            ("toz", "toz"),
            ("learn", "learn"),
        )
        if feature in features
    ]


def _run(env: MigrateEnv, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 - Runs fixed migration commands against the selected harness executable.
        [str(env.exe), *args],
        env={**os.environ, "HOME": str(env.home)},
        text=True,
        capture_output=True,
        check=False,
    )


def install_instructions(
    env: MigrateEnv,
    targets: list[Path],
    sections: list[str],
    report: Report,
) -> None:
    if not targets:
        report.skipped.append(
            ReportEntry(
                env.config_dir / "config.toml",
                "No instruction target was given, so the instruction block was not "
                "touched. Check install state with `varde setup doctor`.",
            )
        )
        return
    command = ["setup", "instructions", "install", "--sections", ",".join(sections)]
    for target in targets:
        command.extend(("--target", str(target)))
    if env.dry_run:
        report.would.extend(
            ReportEntry(
                target, "install the shared Varde instruction block", " ".join(command)
            )
            for target in targets
        )
        return
    result = _run(env, command)
    if result.returncode:
        message = result.stderr.strip() or result.stdout.strip() or "command failed"
        report.unrewritable.extend(
            ReportEntry(
                target,
                f"could not install the Varde instruction block: {message}",
                " ".join(command),
            )
            for target in targets
        )


def pin_toz_store(env: MigrateEnv, report: Report) -> None:
    config_path = env.config_dir / "config.toml"
    try:
        configured = varde_toz_dir(Path.cwd(), environ=dict(os.environ), home=env.home)
    except (OSError, ValueError) as error:
        report.unrewritable.append(
            ReportEntry(config_path, f"could not read configured Varde paths: {error}")
        )
        return
    if configured is not None:
        return

    store = env.toz_config_override or resolve_config_dir(
        environ=dict(os.environ), home=env.home
    )
    command = ["varde", "setup", "paths", "set", "--default", "--toz", str(store)]
    if env.dry_run:
        report.would.append(
            ReportEntry(
                store,
                "prediction: pin the resolved Toz store as the default",
                " ".join(command),
            )
        )
        return
    try:
        config = load_config()
        defaults = config.document.get("default")
        if defaults is None:
            defaults = {}
        defaults = _defaults_table(defaults)
        defaults["toz"] = str(store)
        config.document["default"] = defaults
        save_config(config)
    except (OSError, ValueError, RuntimeError) as error:
        report.unrewritable.append(
            ReportEntry(
                store, f"could not pin the resolved Toz store as the default: {error}"
            )
        )
        return
    report.moved.append(
        ReportEntry(
            store, "pinned the resolved Toz store as the default", " ".join(command)
        )
    )


def retire_toz(
    directory: Path, rels: list[str], *, dry_run: bool = False
) -> list[Path]:
    """Retire Toz-owned legacy files, preserving edited files."""
    if dry_run:
        return []
    return retire_owned_files(directory, rels)


def rewrite_harness_with_features(
    env: MigrateEnv, harness_id: str, report: Report, features: set[str] | None
) -> None:
    """Retire reached per-feature Toz files before unified hook installation."""
    config_home = env.xdg_config_home or env.home / ".config"
    pi_root = Path(os.environ.get("PI_CODING_AGENT_DIR") or env.home / ".pi/agent")
    layouts: dict[str, tuple[Path, tuple[tuple[Path, list[str]], ...]]] = {
        "claude": (
            env.home / ".claude/skills/varde-toz-hooks",
            (
                (
                    env.home / ".claude/skills/varde-toz-hooks",
                    [
                        ".claude-plugin/plugin.json",
                        "hooks/hooks.json",
                        "skills/toz/SKILL.md",
                    ],
                ),
                (
                    env.home / ".claude/skills/toz",
                    [
                        ".claude-plugin/plugin.json",
                        "hooks/hooks.json",
                        "skills/toz/SKILL.md",
                    ],
                ),
            ),
        ),
        "codex": (env.home / ".codex/hooks.json", ()),
        "opencode": (
            config_home / "opencode/plugin/varde-toz.ts",
            ((config_home / "opencode", ["plugin/varde-toz.ts", "plugin/toz.ts"]),),
        ),
        "pi": (
            pi_root / "extensions/varde-toz.ts",
            ((pi_root, ["extensions/varde-toz.ts", "extensions/toz.ts"]),),
        ),
    }
    layout = layouts.get(harness_id)
    if layout is None:
        return
    install, directories = layout
    for directory, files in directories:
        if not any((directory / rel).exists() for rel in files):
            continue
        if env.dry_run:
            report.would.append(
                ReportEntry(
                    install,
                    "prediction: remove the per-feature Toz integration for "
                    f"{harness_id}",
                )
            )
            continue
        kept = retire_toz(directory, files)
        if kept:
            path = kept[0]
            report.unrewritable.append(
                ReportEntry(
                    path,
                    f"the per-feature Toz install for {harness_id} was edited and "
                    "kept; unified hooks were not installed for it. Delete "
                    f"{path}, then rerun `varde setup sync`",
                )
            )
            return
    session_path = {
        "claude": env.home / ".claude/settings.json",
        "codex": env.home / ".codex/hooks.json",
    }.get(harness_id)
    if session_path is not None:
        retire_session_entries(env, harness_id, session_path, report)


def retire_session_entries(
    env: MigrateEnv, harness_id: str, path: Path, report: Report
) -> None:
    """Remove unedited legacy workflow session entries from a JSON hook file."""
    try:
        original = path.read_text()
        document = json.loads(original)
    except OSError, UnicodeError, json.JSONDecodeError:
        return
    hooks = document.get("hooks") if isinstance(document, dict) else None
    events = hooks.get("SessionStart") if isinstance(hooks, dict) else None
    if not isinstance(events, list):
        return
    found = False
    for event in events:
        if not isinstance(event, dict):
            continue
        commands = event.get("hooks")
        if not isinstance(commands, list):
            continue
        group_pristine = (
            set(event) <= {"matcher", "hooks"}
            and event.get("matcher", "") == ""
            and len(commands) == 1
        )
        for command in commands:
            value = command.get("command") if isinstance(command, dict) else None
            try:
                words = shlex.split(value) if isinstance(value, str) else []
            except ValueError:
                words = []
            executable = Path(words[0]).name if words else ""
            args = words[1:]
            legacy = executable == "varde-workflow" and args == [
                "hook",
                "session-start",
                "--harness",
                harness_id,
            ]
            nav_map = harness_id == "codex" and (
                executable == "varde-code"
                and "nav_map" in args
                or executable == "varde"
                and args[:2] == ["map", "nav_map"]
            )
            if legacy or nav_map:
                found = True
                pristine = (
                    group_pristine
                    and isinstance(command, dict)
                    and command.get("type") == "command"
                    and command.get("timeout", 20) == 20
                    and set(command) <= {"type", "command", "timeout"}
                    and (nav_map or legacy)
                )
                if not pristine:
                    return
    if not found or env.dry_run:
        if found and env.dry_run:
            report.would.append(
                ReportEntry(
                    path,
                    f"prediction: remove legacy session hook entries for {harness_id}",
                )
            )
        return

    def owned(command: str) -> bool:
        try:
            words = shlex.split(command)
        except ValueError:
            return False
        executable = Path(words[0]).name if words else ""
        args = words[1:]
        legacy = executable == "varde-workflow" and args == [
            "hook",
            "session-start",
            "--harness",
            harness_id,
        ]
        nav_map = harness_id == "codex" and (
            executable == "varde-code"
            and "nav_map" in args
            or executable == "varde"
            and args[:2] == ["map", "nav_map"]
        )
        return legacy or nav_map

    updated, removed = json_order.remove_matching_commands_with_options(
        original, "SessionStart", owned
    )
    if not removed:
        return
    write_atomic(path, updated)
    report.moved.append(
        ReportEntry(path, f"removed legacy session hook entries for {harness_id}")
    )


@dataclass
class StepOptions:
    no_packs: bool = False
    dry_run: bool = False
    yes: bool = False


SUMMARY_LINES = {
    "edit-agents-md": "edit AGENTS.md (tracked file): add the varde-map pointer block",
    "build-packs": "build packs into docs/repo-map/ (first build takes minutes)",
}
SANDBOX_NOTE = (
    "note: the grammar download fails inside a sandbox; if the build failed, "
    "rerun `varde map packs build --all` outside it."
)
FRESHNESS = (
    "keep packs fresh: `varde map packs status --check`, "
    "`varde map packs build --stale`"
)


def _tracked_files(root: Path) -> list[str]:
    result = subprocess.run(  # noqa: S603 - Fixed git argv.
        ["git", "-C", str(root), "ls-files"],  # noqa: S607
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.splitlines()


def _confirmed() -> bool:
    if not sys.stdin.isatty():
        return True
    return input("Proceed? [Y/n] ").strip().lower() not in ("n", "no")


def _write_modules(root: Path) -> None:
    modules = root / "docs" / "repo-map" / "modules.txt"
    if modules.exists():
        return
    modules.parent.mkdir(parents=True, exist_ok=True)
    modules.write_text(
        "\n".join(repo_map_step.default_modules(_tracked_files(root))) + "\n"
    )


def _build_packs(root: Path) -> None:
    subprocess.run(  # noqa: S603 - Fixed argv against the installed CLI.
        ["varde", "map", "packs", "build", "--all", "--repo-root", str(root)],  # noqa: S607
        check=False,
    )


def run_step(cwd: Path, options: StepOptions) -> None:
    """Add the repo-map pointer block and build packs at a git main checkout."""
    if options.no_packs:
        return
    is_main = (cwd / ".git").is_dir()
    agents = cwd / "AGENTS.md"
    existing = agents.read_text() if agents.exists() else None
    actions = repo_map_step.plan_step(
        is_main,
        (cwd / "docs" / "repo-map" / "README.md").exists(),
        existing is not None and repo_map_step.START in existing,
    )
    if not actions:
        return
    for action in actions:
        print(("would " if options.dry_run else "") + SUMMARY_LINES[action])
    if options.dry_run:
        return
    if not options.yes and not _confirmed():
        print("repo map step skipped")
        return
    agents.write_text(repo_map_step.merge_block(existing))
    print("edited AGENTS.md (tracked file)")
    if "build-packs" in actions:
        _write_modules(cwd)
        print("building packs...")
        _build_packs(cwd)
        print(SANDBOX_NOTE)
    print(FRESHNESS)


def print_text_notes(
    report: Report, cwd: Path, options: StepOptions | None = None
) -> None:
    """Run the repo-map step and print any migration report in text mode."""
    run_step(cwd, options or StepOptions())
    if str(report) != "no migration actions":
        print(report)


@dataclass
class WatchMoveState:
    code_store_movable: bool
    registered_repos: list[Path]


def stop_for_move(env: MigrateEnv, report: Report) -> WatchMoveState:
    """Stop known Python watchers and preserve registered repos for restart."""
    from varde_code.index import supervise

    lock_path = env.config_dir / "code/watch-locks"
    try:
        instances = supervise.list_instances()
    except (OSError, RuntimeError, ValueError) as error:
        report.unrewritable.append(
            ReportEntry(
                lock_path,
                f"could not list code watchers before the config move: {error}",
            )
        )
        return WatchMoveState(False, [])
    repos = list(
        dict.fromkeys(
            Path(str(repo))
            for instance in instances
            if instance.get("registered")
            for repo in _instance_repos(instance)
            if repo
        )
    )
    if env.dry_run:
        for instance in instances:
            if instance.get("registered") or instance.get("alive") is not False:
                covered = _instance_repos(instance) or [lock_path]
                for repo in filter(None, covered):
                    report.would.append(
                        ReportEntry(
                            Path(str(repo)), "prediction: stop this code watcher"
                        )
                    )
        return WatchMoveState(True, repos)
    try:
        outcomes = supervise.stop_all()
        for outcome in outcomes:
            if outcome.get("error"):
                report.unrewritable.append(
                    ReportEntry(
                        lock_path, f"failed to stop a code watcher: {outcome['error']}"
                    )
                )
    except (OSError, RuntimeError, ValueError) as error:
        report.unrewritable.append(
            ReportEntry(
                lock_path,
                f"could not stop all code watchers before the config move: {error}",
            )
        )
        return WatchMoveState(False, repos)
    # The current Python watcher implementation has no separate lock registry.
    return WatchMoveState(not any(item.get("error") for item in outcomes), repos)


def restart_after_move(env: MigrateEnv, repos: list[Path], report: Report) -> None:
    """Restore only repos that had registered watcher services."""
    from varde_code.index.supervise import ensure

    for repo in repos:
        command = f"varde setup watch --ensure --repo {repo}"
        if env.dry_run:
            report.would.append(
                ReportEntry(
                    repo,
                    "prediction: re-register this code watcher after the config move",
                    command,
                )
            )
            continue
        try:
            ensure(repo)
        except (OSError, RuntimeError, ValueError) as error:
            report.unrewritable.append(
                ReportEntry(
                    repo,
                    f"ensure failed and the repo remains unregistered: {error}",
                    command,
                )
            )
            continue


def _instance_repos(instance: dict[str, object]) -> list[object]:
    repos = instance.get("repos")
    if not isinstance(repos, list):
        return []
    return repos
