"""Command line for `varde design`: check, tokens and survey (static tier).

This file is the thin I/O layer (reading, printing, exit code). The report
logic lives in check.py and reports.py and takes texts, not paths.
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

from .check import check_texts
from .cli_args import Options, UsageError, parse_options
from .merge import RenderOutcome
from .output import render_check_text, render_json, render_tokens_text
from .render_tier import render_outcome
from .report import exit_code
from .reports import survey_report, tokens_report
from .settings import Settings, SettingsError
from .sources import (
    load_project_settings,
    project_root,
    read_capped,
    read_targets,
    token_sheets,
)
from .survey import files_to_read
from .survey_walk import walk_project

_ROOT_HELP = (
    "Check frontend pages for design defects\n\n"
    "Usage: varde design <COMMAND>\n\n"
    "Commands:\n"
    "  check   Check .html and .css files for design defects\n"
    "  tokens  Print the custom-property map the checker uses\n"
    "  survey  Report the project's tokens, components, pages and design docs\n\n"
    "Options:\n  -h, --help  Print help\n\n"
    "Every command takes --json for a versioned report (schema: 1).\n"
    "Exit codes: 0 clean, 1 something was not checked, 2 a fail finding or "
    "bad usage.\n"
)
_CHECK_HELP = (
    "Check .html and .css files for design defects\n\n"
    "Usage: varde design check [OPTIONS] [PATHS]...\n\n"
    "PATHS are files or folders (default: the current folder).\n\n"
    "Options:\n"
    "  --json           Print the report as JSON (schema: 1)\n"
    "  --profile <P>    core (default) or opinion (adds S1 S3 S7-S10 R4 R7 and\n"
    "                   the S5 h1 and heading-step checks)\n"
    "  --config <FILE>  Settings file (default: varde-design.toml in the project)\n"
    "  --tokens <CSS>   Stylesheet that defines the tokens (default: discovered)\n"
    "  --width <LIST>   Viewport widths for the rendered tier (default 390,768,1440)\n"
    "  --static-only    Skip the rendered tier (and do not list it as not run)\n"
    "  -h, --help       Print help\n\n"
    "Findings have tier fail (never waivable) or warn (waive with\n"
    "design-ignore <id> reason: <24+ characters>). At most 40 are shown.\n"
    "Exit codes: 0 clean, 1 something was not checked, 2 any fail finding.\n"
    "The rendered tier needs Playwright and Chromium; without them it is listed\n"
    "under not run (exit 1).\n"
)
_TOKENS_HELP = (
    "Print the custom-property map the checker uses\n\n"
    "Usage: varde design tokens [OPTIONS] [PATHS]...\n\n"
    "Options:\n"
    "  --json           Print the report as JSON (schema: 1)\n"
    "  --config <FILE>  Settings file (token_files selects the sheets)\n"
    "  -h, --help       Print help\n\n"
    "Exit codes: 0 tokens found, 1 none found or a path was not read.\n"
)
_SURVEY_HELP = (
    "Report the project's tokens, components, pages and design docs\n\n"
    "Usage: varde design survey [OPTIONS] [PATH]\n\n"
    "Options:\n"
    "  --json      Print the report as JSON (schema: 1)\n"
    "  -h, --help  Print help\n\n"
    "Reads only; output is capped at about 600 tokens. Exit codes: 0 complete,\n"
    "1 the walk was cut short or the path was not found.\n"
)
_HELP = {
    "": _ROOT_HELP,
    "design": _ROOT_HELP,
    "design check": _CHECK_HELP,
    "design tokens": _TOKENS_HELP,
    "design survey": _SURVEY_HELP,
}
_COMMANDS = ("check", "tokens", "survey")


def help_text(path: str = "") -> str:
    return _HELP.get(path.strip(), _ROOT_HELP)


def _emit(report: dict[str, object], text: str, as_json: bool) -> int:
    sys.stdout.write(render_json(report) if as_json else text)
    return exit_code(report)


def _settings(options: Options, root: Path) -> tuple[Settings, str]:
    settings, source = load_project_settings(options.config, root)
    if options.profile:
        settings = replace(settings, profile=options.profile)
    return settings, source


def _render(
    options: Options, settings: Settings, files: list[str]
) -> RenderOutcome | None:
    if options.static_only:
        return None
    return render_outcome(files, settings, options.widths or settings.widths)


def run_check(options: Options) -> int:
    args = options.paths or ["."]
    root = project_root(args)
    settings, source = _settings(options, root)
    targets = read_targets(args)
    sheets, sheet_skips = token_sheets(settings, root, options.tokens)
    render = _render(options, settings, list(targets.files))
    report = check_texts(
        targets.files,
        settings,
        extra_sheets=sheets,
        settings_source=source,
        skipped=[*targets.skipped, *sheet_skips],
        static_only=options.static_only,
        render=render,
    )
    return _emit(report, render_check_text(report), options.json)


def run_tokens(options: Options) -> int:
    args = options.paths or ["."]
    root = project_root(args)
    settings, source = _settings(options, root)
    targets = read_targets(args)
    sheets, sheet_skips = token_sheets(settings, root, None)
    report = tokens_report(
        targets.files,
        sheets,
        settings_source=source,
        skipped=[*targets.skipped, *sheet_skips],
    )
    return _emit(report, render_tokens_text(report), options.json)


def run_survey(options: Options) -> int:
    if len(options.paths) > 1:
        raise UsageError("survey takes one path")
    root = Path(options.paths[0] if options.paths else ".")
    if not root.is_dir():
        paths, texts, truncated = [], {}, False
        skipped = [f"{root}: not a folder"]
    else:
        walk = walk_project(root)
        paths, truncated, skipped = walk.paths, walk.truncated, []
        texts = {
            rel: text
            for rel in files_to_read(walk.paths, walk.sizes)
            for text, _ in [read_capped(root / rel)]
            if text is not None
        }
    report, text = survey_report(paths, texts, truncated=truncated, skipped=skipped)
    return _emit(report, text, options.json)


_HANDLERS = {"check": run_check, "tokens": run_tokens, "survey": run_survey}


def run(argv: list[str], io: object | None = None) -> int:
    del io
    if not argv or argv[0] in {"-h", "--help", "help"}:
        sys.stdout.write(_ROOT_HELP)
        return 0
    command, rest = argv[0], argv[1:]
    if command not in _COMMANDS:
        print(f"unknown argument: {command}\n\n{_ROOT_HELP}", end="")
        return 2
    if any(word in {"-h", "--help"} for word in rest):
        sys.stdout.write(help_text(f"design {command}"))
        return 0
    try:
        return _HANDLERS[command](parse_options(command, rest))
    except (UsageError, SettingsError) as error:
        print(f"error: {error}")
        return 2
