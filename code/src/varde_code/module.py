"""Stub module entry point for code."""

import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class _StubModule:
    name: str = "code"

    def run(self, argv, io=None):
        """Route implemented code commands, or report an unimplemented command."""
        argv = list(argv)
        if argv and (argv[0] == "varde" or argv[0].startswith("varde ")):
            prefix = argv.pop(0).removeprefix("varde").strip()
            if prefix:
                argv[0:0] = prefix.split()
        if argv and argv[0] == "code":
            argv.pop(0)
        if argv and argv[0] == "map":
            return _run_map(argv, io)
        if argv[:2] == ["setup", "watch"] or argv[:1] == ["watch"]:
            from .cli_index import register

            _register_provider()
            routed = ["setup", "watch", *argv[1:]] if argv[0] == "watch" else argv
            return register().run(routed, io)
        if argv and argv[0] in {
            "scan",
            "test",
            "rules_list",
            "rules_seed",
            "rules_remove",
        }:
            from .cli_scan import run

            return run(argv, io)
        if argv and argv[0] in {"edit", "score", "samples", "quality"}:
            if argv[0] == "quality":
                from .quality_score.cli.baseline import run
            elif argv[0] == "score":
                from .quality_score.cli import run
            elif argv[0] == "samples":
                from .quality_score.samples_cli import run
            else:
                from .cli_edit import run

            return run(argv, io)
        if argv and argv[0] == "_rules-scan":
            from .rules.__main__ import main

            return main(argv[1:])
        print("code: module stub", file=sys.stderr)
        return 2

    def help(self, path=""):
        """Return committed help for a code command."""
        parts = tuple(part for part in path.split(" ") if part)
        if not parts or parts[0] == "scan":
            from .cli_scan import help

            return help(" ".join(parts[1:]))
        if parts[0] == "edit":
            from .cli_edit import help

            return help(" ".join(parts[1:]))
        if parts[0] == "code":
            parts = parts[1:]
        if parts and parts[0] in {"score", "quality", "samples"}:
            return _quality_parser(parts[0]).format_help()
        if parts[0] == "map":
            if len(parts) > 1 and parts[1] == "packs":
                from .cli_packs import help

                return help(" ".join(parts))
            if len(parts) > 1 and parts[1] == "extract":
                from .cli_extract import help

                return help(" ".join(parts[1:]))
            from .cli_query import help

            return help(" ".join(parts))
        return ""


def _quality_parser(name):
    """Return the argparse parser of a quality-score command."""
    if name == "score":
        from .quality_score.cli import _parser
    elif name == "quality":
        from .quality_score.cli.baseline import _parser
    else:
        from .quality_score.samples_cli import _parser
    return _parser()


def _register_provider():
    """Register the code extraction provider for routes that index."""
    from .cli_index import register_extraction_provider
    from .extract.provider import CodeExtractionProvider

    register_extraction_provider(CodeExtractionProvider())


def _run_map(argv, io):
    """Route one ``map`` command to its handler."""
    _register_provider()
    if len(argv) > 1 and argv[1] == "packs":
        from .cli_packs import run

        return run(argv, io)
    if len(argv) > 1 and argv[1] == "extract":
        from .cli_extract import run

        return run(argv, io)
    if len(argv) > 1 and argv[1] in {"build", "prune"}:
        from .cli_index import register

        return register().run(argv, io)
    from .cli_query import run

    return run(argv, io)


def register():
    """Return this module implementation."""
    return _StubModule()
