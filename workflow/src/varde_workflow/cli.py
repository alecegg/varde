"""Argument routing for the workflow command surface."""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

from varde_workflow.collectors import parse_stale_seconds
from varde_workflow.soak import DEFAULT_THRESHOLDS


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise ValueError(message)


def _duration(value: str) -> int:
    try:
        return parse_stale_seconds(value)
    except ValueError as exc:
        message = (
            f"invalid value '{value}' for '--stale <DURATION>': value must be a "
            "positive duration such as 90s, 20m, or 1h"
        )
        raise argparse.ArgumentTypeError(message) from exc


def _positive_seconds(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "timeout must be a positive number of seconds"
        ) from exc
    if parsed <= 0 or not math.isfinite(parsed):
        raise argparse.ArgumentTypeError("timeout must be a positive number of seconds")
    return parsed


def _positive(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("value must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("value must be greater than zero")
    return parsed


def _soak_threshold(value: str) -> tuple[str, int | float]:
    key, separator, raw_value = value.partition("=")
    if not separator or key not in DEFAULT_THRESHOLDS:
        raise argparse.ArgumentTypeError("threshold must be KEY=VALUE for a known key")
    default = DEFAULT_THRESHOLDS[key]
    try:
        parsed = int(raw_value) if isinstance(default, int) else float(raw_value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("threshold value must be numeric") from exc
    if parsed < 0 or not math.isfinite(parsed):
        raise argparse.ArgumentTypeError(
            "threshold value must be finite and nonnegative"
        )
    return key, parsed


def _address_duration(value: str) -> int:
    factors = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if (
        len(value) < 2
        or value[-1] not in factors
        or not value[:-1].isdigit()
        or int(value[:-1]) <= 0
    ):
        raise argparse.ArgumentTypeError("duration must be positive, such as 24h")
    return int(value[:-1]) * factors[value[-1]]


def _parser() -> _Parser:
    parser = _Parser(prog="varde", add_help=False)
    roots = parser.add_subparsers(dest="root", required=True, parser_class=_Parser)
    plan = roots.add_parser("plan", add_help=False)
    plans = plan.add_subparsers(dest="command", required=True, parser_class=_Parser)

    def command(name: str, *positionals: tuple[str, dict], **flags: dict) -> _Parser:
        child = plans.add_parser(name, add_help=False)
        for arg, options in positionals:
            child.add_argument(arg, **options)
        for arg, options in flags.items():
            child.add_argument(arg, **options)
        return child

    def json_flag(child: _Parser) -> None:
        child.add_argument("--json", action="store_true")

    child = command("validate", ("artifact", {}))
    json_flag(child)
    child = command("graph", ("plan", {}))
    child.add_argument("--offset", type=int, default=0)
    child.add_argument("--limit", type=_positive, default=100)
    child.add_argument("--all", action="store_true")
    json_flag(child)
    child = command("check-task-ownership")
    child.add_argument("--task", required=True)
    child.add_argument("--commit", required=True)
    child.add_argument("--repo-root", default=".")
    child.add_argument(
        "--trusted-tip", dest="trusted_tips", action="append", default=[]
    )
    json_flag(child)
    child = command("gate", ("task", {}))
    child.add_argument("--commit")
    child = command("execution-wave", ("plan_dir", {}))
    child.add_argument("--repo-root")
    child.add_argument("--max-workers", type=int)
    json_flag(child)
    child = command("readiness", ("plan", {}))
    json_flag(child)
    child = command("comments", ("plan", {}))
    child.add_argument("--open", action="store_true")
    child = command("queue")
    queue_actions = child.add_subparsers(
        dest="queue_action", required=True, parser_class=_Parser
    )
    queue_check = queue_actions.add_parser("check", add_help=False)
    queue_check.add_argument("plan")
    json_flag(queue_check)
    for action in (
        "pull",
        "renew",
        "finish",
        "release",
        "status",
        "metrics",
        "enqueue",
    ):
        queue_action = queue_actions.add_parser(action, add_help=False)
        queue_action.add_argument("--queue", default="roles/global")
        if action == "pull":
            queue_action.add_argument("--role", required=True)
        if action in {"pull", "renew", "finish", "release"}:
            queue_action.add_argument("--slot", required=True)
            queue_action.add_argument("--epoch", type=int, required=True)
        if action in {"finish", "release"}:
            queue_action.add_argument("--item", required=True)
        if action == "finish":
            queue_action.add_argument("--outcome", default="done")
        if action == "enqueue":
            queue_action.add_argument("--plan-dir", required=True)
            queue_action.add_argument("--id", required=True)
            queue_action.add_argument("--parent")
            queue_action.add_argument("--role", required=True)
            queue_action.add_argument("--owned-file", action="append", default=[])
            queue_action.add_argument("--depends-on", action="append", default=[])
            queue_action.add_argument("--serialize-with", action="append", default=[])
            queue_action.add_argument("--kind", default="build")
            queue_action.add_argument(
                "--route", choices=("self", "builder", "orchestrator")
            )
        json_flag(queue_action)
    for action in ("merge-role-inbox", "rollback-role-inbox"):
        queue_action = queue_actions.add_parser(action, add_help=False)
        json_flag(queue_action)
    child = command("store")
    store_actions = child.add_subparsers(
        dest="store_action", required=True, parser_class=_Parser
    )
    for action in (
        "status",
        "migrate",
        "export",
        "import",
        "backup",
        "restore",
        "rollback",
        "verify",
    ):
        store_action = store_actions.add_parser(action, add_help=False)
        if action == "restore":
            store_action.add_argument("backup")
        if action in {"migrate", "export", "import", "backup", "restore", "rollback"}:
            store_action.add_argument("--dry-run", action="store_true")
        json_flag(store_action)
    child = command("slot")
    slot_actions = child.add_subparsers(
        dest="slot_action", required=True, parser_class=_Parser
    )
    for action in (
        "register",
        "heartbeat",
        "show",
        "park",
        "unpark",
        "handoff",
        "resume",
        "reclaim",
    ):
        slot_action = slot_actions.add_parser(action, add_help=False)
        if action != "reclaim":
            slot_action.add_argument("slot")
        if action == "register":
            slot_action.add_argument("--plan", required=True)
            slot_action.add_argument("--role", required=True)
            slot_action.add_argument("--agent-ref", required=True)
            slot_action.add_argument("--session-id")
            slot_action.add_argument("--lease", type=_positive, default=300)
        if action in {"heartbeat", "park", "unpark", "handoff"}:
            slot_action.add_argument("--epoch", type=_positive, required=True)
        if action == "heartbeat":
            slot_action.add_argument("--progress")
            slot_action.add_argument("--context-tokens", type=int)
            slot_action.add_argument("--turn-count", type=int)
            slot_action.add_argument("--lease", type=_positive)
        if action == "resume":
            slot_action.add_argument("--agent-ref", required=True)
            slot_action.add_argument("--session-id")
            slot_action.add_argument("--lease", type=_positive)
        json_flag(slot_action)
    child = command("status")
    child.add_argument("--repo")
    json_flag(child)
    child = command("task")
    task_actions = child.add_subparsers(
        dest="task_action", required=True, parser_class=_Parser
    )
    task_set_parser = task_actions.add_parser("set", add_help=False)
    task_set_parser.add_argument("task")
    task_set_parser.add_argument("state")
    task_set_parser.add_argument("--plan")
    json_flag(task_set_parser)
    child = command("now", ("plan", {}))
    now_choice = child.add_mutually_exclusive_group(required=True)
    now_choice.add_argument("text", nargs="?")
    now_choice.add_argument("--waiting")
    now_choice.add_argument("--clear", action="store_true")
    child.add_argument("--repo")
    json_flag(child)
    child = command("owner", ("plan", {}))
    owner_choice = child.add_mutually_exclusive_group(required=True)
    owner_choice.add_argument("owner", nargs="?")
    owner_choice.add_argument("--clear", action="store_true")
    json_flag(child)
    child = command("branch", ("branch", {}), ("plan", {}))
    child = command("answer", ("plan", {}))
    child.add_argument("--question", required=True)
    child.add_argument("--answer", required=True)
    json_flag(child)
    command("merged", ("plan", {}))
    command("approve-merge", ("plan", {}))
    child = command("approve-as-main", ("plan", {}))
    child.add_argument("--note", required=True)
    child.add_argument("--plan-followed", action="store_true", required=True)
    child.add_argument("--gate-result", required=True)
    child.add_argument("--abnormal-events", required=True)
    command("merge", ("plan", {}))
    merge_gate_parser = command("merge-gate")
    merge_gate_parser.add_argument("revs", nargs="*")
    merge_gate_parser.add_argument(
        "--mode", choices=("merge", "backstop"), default="merge"
    )
    assign = command("assign", ("plan", {}))
    assign_choice = assign.add_mutually_exclusive_group(required=True)
    assign_choice.add_argument("slot", nargs="?")
    assign_choice.add_argument("--clear", action="store_true")
    child = command("watch")
    child.add_argument("--no-inbox", action="store_true")
    child.add_argument("--no-wake", action="store_true")
    child.add_argument("--stale", type=_duration)
    child.add_argument("--interval", type=_duration, default=60)
    child.add_argument("--once", action="store_true")
    child.add_argument("--repo")
    child.add_argument("--notes", "--handoff", dest="notes", metavar="PATH")
    json_flag(child)
    child = command("pulse", ("plan", {"nargs": "?"}))
    json_flag(child)
    child = command("conclude", ("plan", {}))
    child.add_argument("--merged")
    child.add_argument("--repo")
    json_flag(child)
    child = command("distill", ("plan_dir", {}))
    json_flag(child)
    child = command("handoff-check", ("file", {}))
    child.add_argument("--root", dest="repo_root", default=".")
    json_flag(child)

    msg = roots.add_parser("msg", add_help=False)
    messages = msg.add_subparsers(
        dest="message_command", required=True, parser_class=_Parser
    )
    send = messages.add_parser("send", add_help=False)
    send.add_argument("--from", dest="from_address", required=True)
    send.add_argument("--to", required=True)
    send.add_argument("--kind", required=True)
    send.add_argument("--notes")
    send.add_argument("--reply-to")
    send.add_argument("--urgent", action="store_true")
    send.add_argument("text")
    doctor = messages.add_parser("doctor", add_help=False)
    doctor.add_argument("--json", action="store_true")
    show = messages.add_parser("show", add_help=False)
    show.add_argument("id")
    show.add_argument("--json", action="store_true")
    read = messages.add_parser("read", add_help=False)
    read.add_argument("--as", dest="address", default="main")
    read.add_argument("--all", action="store_true")
    read.add_argument("--json", action="store_true")
    ack = messages.add_parser("ack", add_help=False)
    ack.add_argument("id")
    ack.add_argument("--as", dest="address", required=True)
    status = messages.add_parser("status", add_help=False)
    status.add_argument("--json", action="store_true")
    status.add_argument("--now")
    prune = messages.add_parser("prune", add_help=False)
    prune.add_argument("--dry-run", action="store_true")
    retire = messages.add_parser("retire", add_help=False)
    retire.add_argument("--dry-run", type=Path, metavar="AUDIT_DIR")
    retire.add_argument("--min-age-days", type=_positive, default=30, metavar="N")
    retire.add_argument("--apply", type=Path, metavar="DRY_RUN_FILE")
    retire.add_argument("--restore", type=Path, metavar="AUDIT_FILE")
    nudge = messages.add_parser("nudge", add_help=False)
    nudge.add_argument("--to", required=True)
    nudge.add_argument(
        "--reason", required=True, choices=("idle-unread", "stalled", "other")
    )
    soak = messages.add_parser("soak", add_help=False)
    soak.add_argument("--window-days", type=_positive, default=3)
    soak.add_argument("--threshold", action="append", type=_soak_threshold, default=[])
    soak.add_argument("--write", action="store_true")
    soak.add_argument("--json", action="store_true")
    relay = messages.add_parser("relay", add_help=False)
    relay_mode = relay.add_mutually_exclusive_group()
    relay_mode.add_argument("--once", action="store_true")
    relay_mode.add_argument("--wait", action="store_true")
    relay.add_argument("--timeout", type=_positive_seconds, default=540)
    relay.add_argument("--as", dest="as_id")
    relay.add_argument("--now")
    relay.add_argument("--context-tokens", type=int)
    relay_actions = relay.add_subparsers(dest="relay_action", parser_class=_Parser)
    confirm = relay_actions.add_parser("confirm", add_help=False)
    confirm.add_argument("action_id")
    confirm.add_argument(
        "--result",
        required=True,
        choices=("pushed", "skipped-busy", "failed", "target-gone"),
    )
    confirm.add_argument("--evidence")
    confirm.add_argument("--by")
    confirm.add_argument("--harness")
    confirm.add_argument("--now")
    renew = relay_actions.add_parser("renew", add_help=False)
    renew.add_argument("action_id")
    renew.add_argument("--now")
    finish = relay_actions.add_parser("end", add_help=False)
    finish.add_argument("--as", dest="as_id", required=True)
    finish.add_argument("--now")
    store = messages.add_parser("store", add_help=False)
    store_actions = store.add_subparsers(
        dest="store_action", required=True, parser_class=_Parser
    )
    for action in ("import", "sync", "verify"):
        store_command = store_actions.add_parser(action, add_help=False)
        store_command.add_argument(
            "--from", dest="from_store", choices=("files", "sqlite"), default="files"
        )
        store_command.add_argument(
            "--to", dest="to_store", choices=("files", "sqlite"), default="sqlite"
        )
        if action == "verify":
            store_command.add_argument("--repair-mode", action="store_true")
            store_command.add_argument("--force-adopt", action="store_true")
    store_command = store_actions.add_parser("export", add_help=False)
    store_command.add_argument("--dest", required=True)
    store_mode = store_actions.add_parser("mode", add_help=False)
    store_mode.add_argument(
        "mode", choices=("files", "sqlite", "mirror-files", "mirror-sqlite")
    )
    migrate = messages.add_parser("migrate", add_help=False)
    migrate.add_argument("--strays", action="store_true")
    migrate.add_argument("--apply", action="store_true")
    address = messages.add_parser("address", add_help=False)
    address_actions = address.add_subparsers(
        dest="address_action", required=True, parser_class=_Parser
    )
    address_new = address_actions.add_parser("new", add_help=False)
    address_new.add_argument("name")
    address_new.add_argument("--plan")
    address_new.add_argument("--ttl", type=_address_duration, default=86400)
    address_new.add_argument("--uses", type=_positive, default=1)
    address_new.add_argument("--supersede", action="store_true")
    address_bind = address_actions.add_parser("bind", add_help=False)
    address_bind.add_argument("marker")
    address_bind.add_argument("--session", default="")
    address_bind.add_argument("--harness", default="unknown")
    address_refresh = address_actions.add_parser("refresh", add_help=False)
    address_refresh.add_argument("--session", default="")
    address_refresh.add_argument("--harness", default="unknown")
    address_unbind = address_actions.add_parser("unbind", add_help=False)
    address_unbind.add_argument("target")
    address_list = address_actions.add_parser("list", add_help=False)
    address_list.add_argument("--json", action="store_true")
    address_list.add_argument("--archived-paseo-id", action="append", default=[])

    setup = roots.add_parser("setup", add_help=False)
    setups = setup.add_subparsers(
        dest="setup_command", required=True, parser_class=_Parser
    )
    instructions = setups.add_parser("instructions", add_help=False)
    actions = instructions.add_subparsers(
        dest="instructions_command", required=True, parser_class=_Parser
    )
    install = actions.add_parser("install", add_help=False)
    install.add_argument("--target", dest="targets", action="append", default=[])
    install.add_argument("--builders", type=_positive)
    install.add_argument("--sections", default="orchestration,toz")
    install.add_argument("--learn", action="store_true")
    install.add_argument("--dry-run", action="store_true")
    remove = actions.add_parser("remove", add_help=False)
    remove.add_argument("--dry-run", action="store_true")
    actions.add_parser("targets", add_help=False)
    return parser


def _help_path(argv: list[str]) -> str | None:
    indexes = [index for index, item in enumerate(argv) if item in {"--help", "-h"}]
    if not indexes:
        return None
    route = argv[: indexes[0]]
    if route and route[0] in {"plan", "msg"}:
        return " ".join(route)
    if len(route) >= 2 and route[:2] == ["setup", "instructions"]:
        return " ".join(route)
    return None


def _short_help_text(path: str) -> str:
    return help_text(path, short=True)


def _warn_missing_review_commit(args: argparse.Namespace) -> None:
    from varde_learn.knowledge.frontmatter import parse
    from varde_learn.knowledge.memory import MemoryPaths

    from varde_workflow.commands.now import resolve_plan

    cwd = Path.cwd()
    plans = MemoryPaths.resolve(cwd).working.path / "plans"
    plan = resolve_plan(args.plan, cwd, plans)
    metadata, _ = parse(plan.read_bytes())
    commit = metadata.get("reviewed_commit")
    if not isinstance(commit, str) or not commit:
        return
    if args.repo:
        repository = Path(args.repo)
    else:
        root = subprocess.run(  # noqa: S603 - Runs a fixed Git metadata query.
            ["git", "-C", str(cwd), "rev-parse", "--show-toplevel"],  # noqa: S607 - Git is resolved from PATH.
            capture_output=True,
            check=False,
            text=True,
        )
        if root.returncode or not root.stdout.strip():
            return
        repository = Path(root.stdout.strip())
    result = subprocess.run(  # noqa: S603 - Checks a validated commit reference with fixed Git argv.
        ["git", "-C", str(repository), "cat-file", "-e", f"{commit}^{{commit}}"],  # noqa: S607 - Git is resolved from PATH.
        capture_output=True,
        check=False,
    )
    if result.returncode:
        print(f"review commit {commit} not found in {repository}", file=sys.stderr)


def help_text(path: str = "", *, short: bool = False) -> str:
    parts = path.replace("_", "-").split()
    if parts and parts[0] == "instructions":
        parts.insert(0, "setup")
    elif parts and parts[0] in {
        "validate",
        "graph",
        "check-task-ownership",
        "gate",
        "execution-wave",
        "readiness",
        "comments",
        "queue",
        "store",
        "status",
        "task",
        "now",
        "owner",
        "branch",
        "answer",
        "merged",
        "approve-merge",
        "approve-as-main",
        "merge",
        "merge-gate",
        "assign",
        "watch",
        "pulse",
        "conclude",
        "distill",
        "handoff-check",
        "slot",
    }:
        parts.insert(0, "plan")
    elif parts and parts[0] in {
        "send",
        "read",
        "show",
        "ack",
        "status",
        "address",
        "relay",
        "prune",
        "nudge",
        "soak",
    }:
        parts.insert(0, "msg")
    if parts[:2] == ["plan", "store"]:
        file = Path(__file__).with_name("help") / "plan-store.md"
        return file.read_text(encoding="utf-8")
    key = "_".join(parts)
    suffix = ".short.txt" if short else ".txt"
    file = Path(__file__).with_name("help") / f"{key}{suffix}"
    if not file.is_file():
        raise KeyError(f"no workflow help snapshot for route {path!r}")
    return file.read_text(encoding="utf-8")


def run(
    argv: list[str],
    io: object = None,
    *,
    relay_clock=None,
    relay_poll=None,
) -> int:
    """Run argv after the app router removes the ``plan``/``msg`` prefix."""
    argv = list(argv)
    plan_commands = {
        "validate",
        "graph",
        "check-task-ownership",
        "gate",
        "execution-wave",
        "readiness",
        "comments",
        "queue",
        "store",
        "status",
        "task",
        "now",
        "owner",
        "answer",
        "merged",
        "approve-merge",
        "approve-as-main",
        "merge",
        "merge-gate",
        "assign",
        "watch",
        "pulse",
        "conclude",
        "distill",
        "handoff-check",
        "slot",
    }
    if argv and argv[0] in plan_commands:
        argv.insert(0, "plan")
    elif argv and argv[0] in {
        "send",
        "read",
        "show",
        "relay",
        "prune",
        "nudge",
        "soak",
    }:
        argv.insert(0, "msg")
    elif argv and argv[0] == "instructions":
        argv.insert(0, "setup")
    help_route = _help_path(argv)
    if help_route is not None:
        try:
            help_flag = next(item for item in argv if item in {"--help", "-h"})
            output = (
                _short_help_text(help_route)
                if help_flag == "-h"
                else help_text(help_route)
            )
            sys.stdout.write(output)
        except KeyError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        else:
            return 0
    if (
        "--handoff" in argv or any(item.startswith("--handoff=") for item in argv)
    ) and argv[:2] == ["plan", "watch"]:
        print(
            "varde plan watch: --handoff is deprecated; use --notes",
            file=sys.stderr,
        )
    try:
        args = _parser().parse_args(argv)
        from varde_workflow import plan_comments
        from varde_workflow.commands import (
            approve_as_main,
            approve_merge,
            assign,
            check_task_ownership,
            conclude,
            distill,
            execution_wave,
            graph,
            handoff_check,
            instructions,
            merge,
            merge_gate,
            merged,
            msg,
            msg_prune,
            msg_retire,
            msg_soak,
            now,
            owner,
            plan_answer,
            plan_gate,
            plan_queue,
            plan_queue_roles,
            plan_store,
            pulse,
            readiness,
            slot,
            status,
            task_set,
            validate,
            watch,
        )

        if args.root == "plan":
            handlers = {
                "check-task-ownership": check_task_ownership.run,
                "gate": plan_gate.run,
                "execution-wave": execution_wave.run,
                "readiness": readiness.run,
                "comments": plan_comments.run,
                "queue": plan_queue.run,
                "store": plan_store.run,
                "status": status.run,
                "now": now.run,
                "owner": owner.run,
                "branch": owner.register_branch,
                "answer": plan_answer.run,
                "merged": merged.run,
                "approve-merge": approve_merge.run,
                "approve-as-main": approve_as_main.run,
                "merge": merge.run,
                "merge-gate": merge_gate.run,
                "assign": assign.run,
                "watch": watch.run_watch,
                "pulse": pulse.run,
                "conclude": conclude.run,
                "distill": distill.run,
                "handoff-check": handoff_check.run,
                "slot": slot.run,
            }
            if args.command == "validate":
                return validate.run(args)
            if args.command == "now":
                with contextlib.suppress(OSError, ValueError):
                    _warn_missing_review_commit(args)
            if args.command == "graph":
                from varde_workflow.output import print_cli_success_with_meta

                try:
                    data, meta = graph.graph_data(
                        args.plan,
                        offset=args.offset,
                        limit=args.limit,
                        all_items=args.all,
                    )
                except ValueError as exc:
                    from varde_workflow.errors import InternalError, report_error

                    return report_error(InternalError(str(exc)), args.json)
                if args.json:
                    print_cli_success_with_meta(data, meta)
                else:
                    print(
                        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
                    )
                return 0
            if args.command == "task":
                return task_set.run(args)
            if args.command == "queue" and args.queue_action in {
                "merge-role-inbox",
                "rollback-role-inbox",
            }:
                from varde_workflow.commands import plan_queue_merge

                return plan_queue_merge.run(args)
            if args.command == "queue" and args.queue_action != "check":
                return plan_queue_roles.run(args)
            return (
                handlers[args.command](args, io)
                if args.command == "execution-wave"
                else handlers[args.command](args)
            )
        if args.root == "msg":
            if args.message_command == "prune":
                return msg_prune.run(args)
            if args.message_command == "retire":
                from varde_workflow.binding import resolve_working_dir_with_source

                working, _project_resolved = resolve_working_dir_with_source(Path.cwd())
                return msg_retire.run(args, working)
            from varde_workflow.binding import resolve_working_dir_with_source

            working, project_resolved = resolve_working_dir_with_source(Path.cwd())
            if not project_resolved and args.message_command in {
                "send",
                "read",
                "show",
                "ack",
                "relay",
            }:
                _raise_unresolved_message_store(working)
            if not project_resolved and args.message_command == "soak" and args.write:
                _raise_unresolved_message_store(working)
            if (
                args.message_command in {"send", "read"}
                and not (working / ".cache" / "inbox").is_dir()
            ):
                (working / ".cache" / "inbox").mkdir(parents=True, exist_ok=True)
            if args.message_command == "soak":
                return msg_soak.run(args, working)
            return msg.run(
                args, working, relay_clock=relay_clock, relay_poll=relay_poll
            )
        try:
            return instructions.run(args)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    except (ValueError, argparse.ArgumentError) as exc:
        message = str(exc)
        if argv[:2] == ["msg", "relay"]:
            print(f"error: {message}", file=sys.stderr)
            return 64
        if message.startswith("argument --stale: invalid value '"):
            message = (
                message.removeprefix("argument --stale: ")
                + "\n\nFor more information, try '--help'."
            )
        print(f"error: {message}", file=sys.stderr)
        return 2


def _raise_unresolved_message_store(working: Path) -> None:
    inbox = working / ".cache" / "inbox"
    raise ValueError(
        "message store resolution fell back to cwd because no repo root or config "
        f"was found: {inbox}; set VARDE_WORKING_DIR or run `varde setup paths set`"
    )


__all__ = ["help_text", "run"]
