"""Command dispatch for the learn module."""

from __future__ import annotations

import importlib
import sys

from .docs import commands as docs_commands
from .knowledge import commands as knowledge_commands
from .loop.commands import CommandError, friction_argv, measure_argv, sessions_argv
from .loop.help import help_text

_DOCS_HELP_ROOTS = {"check", "how", "docs"}


class _LearnModule:
    name = "learn"

    def run(self, argv: list[str], io: object | None = None) -> int:
        args = list(argv)
        if args and args[0] == "learn":
            args.pop(0)
        if not args or args[0] in {"-h", "--help"}:
            print(self.help(), end="")
            return 0
        command = args[0]
        try:
            return self._dispatch(command, args[1:], io)
        except (
            CommandError,
            docs_commands.CommandError,
            knowledge_commands.CommandError,
        ) as error:
            print(f"learn: {error}", file=sys.stderr)
            return 2

    def _dispatch(self, command: str, rest: list[str], io: object | None) -> int:  # noqa: PLR0911
        if command == "sessions":
            return self._sessions(sessions_argv(rest), io)
        if command == "check":
            return self._docs_runs(docs_commands.check_runs, rest, "check")
        if command == "how":
            return self._docs_runs(lambda a: [docs_commands.how_argv(a)], rest, "how")
        if command == "docs":
            return self._docs_runs(lambda a: [docs_commands.docs_argv(a)], rest, "docs")
        if command == "measure":
            if not rest or rest[0] in {"-h", "--help"}:
                print(help_text("measure"), end="")
                return 0
            if rest[1:2] and rest[1] in docs_commands.FREE_KINDS:
                return self._docs_runs(
                    lambda a: docs_commands.measure_runs(a[0], a[1], a[2:]),
                    rest,
                    f"measure {rest[1]}",
                )
            from .loop.cli_diagnose import run

            return run(measure_argv(rest))
        if command == "skills":
            return self._skills(rest, io)
        if command == "knowledge":
            return self._knowledge(rest, io)
        if command == "paths":
            from .knowledge.cli import run as knowledge_run

            return knowledge_run([command, *rest], io)
        if command == "friction":
            from .loop import cli_friction

            return cli_friction.run(friction_argv(rest), io)
        if command == "tools":
            from .loop.cli_tools import run

            return run([command, *rest], io)
        if command == "memory":
            from .loop.cli_memory import run

            return run([command, *rest], io)
        if command == "store":
            from .loop.cli_store import run

            return run([command, *rest], io)
        print(f"learn: unexpected command `{command}`", file=sys.stderr)
        return 2

    def _docs_runs(self, plan, args: list[str], help_path: str) -> int:
        from .docs.cli import help_text as docs_help
        from .docs.cli import run as docs_run

        if args[:1] in (["-h"], ["--help"]):
            print(docs_help(help_path), end="")
            return 0
        if not args and help_path in _DOCS_HELP_ROOTS:
            print(docs_help(help_path), end="", file=sys.stderr)
            return 2
        if help_path.startswith("measure") and any(a in {"-h", "--help"} for a in args):
            print(docs_help(help_path), end="")
            return 0
        runs = plan(args)
        codes = [docs_run(argv) for argv in runs]
        return 2 if 2 in codes else max(codes)

    def _skills(self, args: list[str], io: object | None) -> int:
        if not args or args[0] in {"-h", "--help"}:
            print(help_text("skills"), end="")
            return 0
        from .loop.cli_skills import run

        return run(args, io)

    def _knowledge(self, args: list[str], io: object | None) -> int:
        from .knowledge.cli import help_text as knowledge_help
        from .knowledge.cli import run as knowledge_run

        if not args or args[0] in {"-h", "--help"}:
            print(knowledge_help("knowledge"), end="")
            return 0
        notice = knowledge_commands.deprecation_notice(args[0])
        if notice:
            print(notice, file=sys.stderr)
        return knowledge_run(knowledge_commands.knowledge_argv(args), io)

    def _sessions(self, argv: list[str], io: object | None) -> int:
        handler, rest = argv[0], argv[1:]
        if handler == "sessions":
            print(help_text("sessions"), end="")
            return 0
        if handler == "diagnose":
            from .loop.cli_diagnose import run

            return run(argv)
        if handler == "calls":
            from .loop.cli_sessions import run_calls

            return run_calls(rest, io)
        if handler == "guardrails":
            from .loop.cli_guardrails import run

            return run(argv, io)
        module = importlib.import_module(f"{__package__}.loop.cli_{handler}")
        return module.run(argv, io)

    def help(self, path: str = "") -> str:
        command = " ".join(path.split()).removeprefix("learn ").removeprefix("varde ")
        root = command.split(" ", 1)[0]
        if root in {"knowledge", "setup"} or command.startswith("paths"):
            from .knowledge.cli import help_text as knowledge_help

            return knowledge_help(command)
        if root in _DOCS_HELP_ROOTS or command in {
            "measure flow",
            "measure ledger",
            "measure baseline",
        }:
            from .docs.cli import help_text as docs_help

            return docs_help(command)
        return help_text(path)


def register() -> _LearnModule:
    """Return the module interface used by the app entry point."""
    return _LearnModule()
