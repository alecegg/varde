"""Dispatch hook-oriented toz commands before discovering app modules."""

import argparse
import json
import os
import select
import sys
from collections.abc import Sequence
from pathlib import Path


def run(argv: Sequence[str]) -> int | None:  # noqa: PLR0911 - Event dispatch returns at each branch.
    """Run a toz hook command directly, or return ``None`` for normal routing."""
    if not argv:
        return None

    command = argv[0]
    if command == "hook":
        if len(argv) < 2:
            return 2
        event = argv[1]
        if event in {"--help", "-h"}:
            sys.stdout.write(
                "Usage: varde hook <EVENT> --harness <claude|codex|opencode|pi>\n\n"
                "Events:\n  session-start\n  pre-tool-use\n  post-tool-use\n  "
                "user-prompt-submit\n  stop\n  subagent-start\n  "
                "pipeline-slot-check\n  pipeline-handoff-complete\n"
            )
            return 0
        if event == "pipeline-slot-check":
            return _run_pipeline_slot_check(argv[2:])
        if event == "pipeline-handoff-complete":
            return _run_pipeline_handoff_complete(argv[2:])
        if event not in {
            "post-tool-use",
            "pre-tool-use",
            "user-prompt-submit",
            "session-start",
            "stop",
            "subagent-start",
        }:
            return 2
        if any(argument in {"--help", "-h"} for argument in argv[2:]):
            from .glue.help_snapshots import (
                HOOK_POST_TOOL_USE_HELP,
                HOOK_PRE_TOOL_USE_HELP,
                HOOK_SESSION_START_HELP,
                HOOK_STOP_HELP,
                HOOK_SUBAGENT_START_HELP,
                HOOK_USER_PROMPT_SUBMIT_HELP,
            )

            snapshots = {
                "session-start": HOOK_SESSION_START_HELP,
                "user-prompt-submit": HOOK_USER_PROMPT_SUBMIT_HELP,
                "post-tool-use": HOOK_POST_TOOL_USE_HELP,
                "pre-tool-use": HOOK_PRE_TOOL_USE_HELP,
                "stop": HOOK_STOP_HELP,
                "subagent-start": HOOK_SUBAGENT_START_HELP,
            }
            sys.stdout.write(snapshots[event])
            return 0
        return _run_hook(argv)
    is_hook_capture = command == "capture" and "--hook" in argv[1:]
    if command not in {"note", "event"} and not is_hook_capture:
        return None

    from varde_toz.cli import main as toz_main

    return int(toz_main(argv) or 0)


def _hook_harness(argv: Sequence[str]) -> str:
    for index, argument in enumerate(argv[2:], start=2):
        if argument.startswith("--harness="):
            return argument.partition("=")[2]
        if argument == "--harness":
            return argv[index + 1] if index + 1 < len(argv) else ""
    return ""


def _run_hook(argv: Sequence[str]) -> int:
    from .glue.hook import MAX_PAYLOAD_BYTES, dispatch

    event = argv[1]
    if event == "user-prompt-submit":
        if os.name != "posix" or sys.stdin.isatty():
            raw = b""
        elif select.select([sys.stdin], [], [], 0)[0]:
            buffer = sys.stdin.buffer
            reader = getattr(buffer, "read1", None)
            if reader is None:
                raw = buffer.read(MAX_PAYLOAD_BYTES + 1)
            else:
                chunks = bytearray()
                while len(chunks) <= MAX_PAYLOAD_BYTES:
                    chunk = reader(min(64 * 1024, MAX_PAYLOAD_BYTES + 1 - len(chunks)))
                    if not chunk:
                        break
                    chunks.extend(chunk)
                raw = bytes(chunks)
            if len(raw) > MAX_PAYLOAD_BYTES:
                print(
                    f"varde hook: prompt payload truncated at "
                    f"{MAX_PAYLOAD_BYTES} bytes",
                    file=sys.stderr,
                )
                raw = raw[:MAX_PAYLOAD_BYTES]
        else:
            raw = b""
    else:
        raw = sys.stdin.buffer.read(MAX_PAYLOAD_BYTES + 1)
    return dispatch({"event": event, "input": raw}, _hook_harness(argv))


def _run_pipeline_slot_check(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="varde hook pipeline-slot-check")
    parser.add_argument("--plan-dir", required=True, type=Path)
    parser.add_argument("--slot", required=True)
    parser.add_argument(
        "--role", required=True, choices=("builder", "reviewer", "orchestrator")
    )
    parser.add_argument("--item", required=True)
    parser.add_argument("--status-file", required=True, type=Path)
    try:
        args = parser.parse_args(argv)
        if not args.plan_dir.is_absolute() or not args.status_file.is_absolute():
            print(
                "varde hook pipeline-slot-check: --plan-dir and --status-file "
                "must be absolute paths",
                file=sys.stderr,
            )
            return 2
        status = json.loads(args.status_file.read_text(encoding="utf-8"))
        from .glue.handoff_checkpoint import check_paseo_slot

        result = check_paseo_slot(
            args.plan_dir, args.slot, args.role, args.item, status
        )
    except (OSError, ValueError) as error:
        print(f"varde hook pipeline-slot-check: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _run_pipeline_handoff_complete(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(prog="varde hook pipeline-handoff-complete")
    parser.add_argument(
        "--harness", required=True, choices=("claude", "codex", "paseo")
    )
    parser.add_argument("--session", required=True)
    parser.add_argument("--turn", required=True, type=int)
    parser.add_argument("--plan-dir", type=Path)
    parser.add_argument("--slot")
    try:
        args = parser.parse_args(argv)
        if args.turn < 1:
            print(
                "varde hook pipeline-handoff-complete: --turn must be positive",
                file=sys.stderr,
            )
            return 2
        if args.harness == "paseo":
            if (
                args.plan_dir is None
                or args.slot is None
                or not args.plan_dir.is_absolute()
            ):
                print(
                    "varde hook pipeline-handoff-complete: Paseo confirmation "
                    "needs absolute --plan-dir and --slot",
                    file=sys.stderr,
                )
                return 2
            from .glue.handoff_checkpoint import complete_paseo_handoff

            completed = complete_paseo_handoff(
                args.plan_dir, args.slot, args.session, args.turn
            )
        else:
            from .glue.session_notes import complete_native_handoff

            completed = complete_native_handoff(args.harness, args.session, args.turn)
    except (OSError, ValueError) as error:
        print(f"varde hook pipeline-handoff-complete: {error}", file=sys.stderr)
        return 2
    if not completed:
        print(
            "varde hook pipeline-handoff-complete: no matching pending handoff",
            file=sys.stderr,
        )
        return 2
    print(json.dumps({"completed": True, "turn": args.turn}))
    return 0
