"""Setup sync implementation modules."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from varde_core.envelope import negative_result, success
from varde_learn.knowledge.memory_config import Config, load_config, save_config

from varde.setup.old_store import SetupError, check_old_store

from . import agents, config, skills, support
from .harness import HarnessId, detect, select
from .report import MigrateEnv, Report

SYNC_ABOUT = (
    "Preview with --dry-run, choose explicit targets, then apply skill and agent setup"
)
RECOMMENDED_LAYOUT = (
    "Recommended layout: keep one canonical central copy (for example "
    "~/.agents/skills and ~/.agents/agents, or a private Git repo) and symlink it "
    "into each detected harness's skill and agent directories."
)


@dataclass
class SyncContext:
    skills_dir: Path
    agents_dir: Path
    selected_skills: list[str] | None
    link_mode: str
    harnesses: list
    dry_run: bool
    home: Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="varde setup sync",
        description=SYNC_ABOUT,
        epilog=RECOMMENDED_LAYOUT
        + "\nSandbox denial can leave earlier targets installed; retry the denied "
        "target. Watcher registration can time out; check setup doctor afterward.",
    )
    parser.add_argument("--skills-dir")
    parser.add_argument("--agents-dir")
    parser.add_argument("--link-mode", choices=("symlink", "copy"))
    parser.add_argument("--skills")
    parser.add_argument(
        "--preset",
        help=(
            "Preset of skills to install (combines with --skills): "
            f"{', '.join(skills.preset_names())}"
        ),
    )
    parser.add_argument("--harnesses")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--save",
        action="store_true",
        help="Persist sync flags and presets in the user config",
    )
    parser.add_argument("--instructions-target", action="append", default=[])
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--no-packs", action="store_true", help="Skip the repo-map setup step"
    )
    parser.add_argument(
        "--yes", action="store_true", help="Skip the repo-map step prompt"
    )
    return parser


def _path(value: str, home: Path, cwd: Path) -> Path:
    if value.startswith("~/"):
        value = str(home / value[2:])
    path = Path(value)
    path = path if path.is_absolute() else cwd / path
    return Path(os.path.normpath(path))


def _selection(args, saved: config.SavedSettings) -> list[str] | None:
    selected = None
    if args.skills is not None:
        names = (
            []
            if args.skills == "all"
            else [name.strip() for name in args.skills.split(",")]
        )
        if any(not name for name in names):
            raise ValueError(
                "skill names must not be empty; use --skills all to select every skill"
            )
        config.validate_skills(list(dict.fromkeys(names)))
        selected = list(dict.fromkeys(names))
    if args.preset is not None:
        preset = skills.preset_skills(args.preset)
        selected = (
            []
            if not preset or selected == []
            else list(dict.fromkeys((selected or []) + preset))
        )
    if selected is None and saved.presets:
        preset_skills = [n for p in saved.presets for n in skills.preset_skills(p)]
        selected = list(dict.fromkeys((saved.skills or []) + preset_skills))
    return selected if selected is not None else saved.skills


def _context(args) -> tuple[SyncContext, Config]:
    stored = load_config()
    notice = config.migrate_presets(stored)
    if notice is not None:
        if args.dry_run:
            notice = notice.replace("config rewritten", "config would be rewritten")
            print(notice, file=sys.stderr)
        else:
            print(notice, file=sys.stderr)
            save_config(stored)
    saved = config.read(stored)
    home = Path(
        os.environ.get("HOME") or os.environ.get("USERPROFILE") or "."
    ).resolve()
    cwd = Path.cwd()
    skills_dir = (
        _path(args.skills_dir, home, cwd) if args.skills_dir else saved.skills_dir
    )
    agents_dir = (
        _path(args.agents_dir, home, cwd) if args.agents_dir else saved.agents_dir
    )
    missing = [
        flag
        for flag, path in (("--skills-dir", skills_dir), ("--agents-dir", agents_dir))
        if path is None
    ]
    if missing:
        raise ValueError(
            f"missing required target{'s' if len(missing) > 1 else ''}: "
            f"{' and '.join(missing)}"
        )
    assert skills_dir is not None  # noqa: S101 - The missing-target check above narrows this path.
    assert agents_dir is not None  # noqa: S101 - The missing-target check above narrows this path.
    for flag, path in (("--skills-dir", skills_dir), ("--agents-dir", agents_dir)):
        if path.exists() and not path.is_dir():
            raise ValueError(f"{flag} target {path} exists and is not a directory")
    mode = args.link_mode or saved.link_mode or "symlink"
    selected = _selection(args, saved)
    if args.harnesses is None:
        harnesses = detect(
            home,
            Path(os.environ["PI_CODING_AGENT_DIR"])
            if os.environ.get("PI_CODING_AGENT_DIR")
            else None,
        )
    elif args.harnesses == "none":
        harnesses = []
    else:
        identifiers = list(
            dict.fromkeys(HarnessId.parse(item) for item in args.harnesses.split(","))
        )
        harnesses = select(
            identifiers,
            home,
            Path(os.environ["PI_CODING_AGENT_DIR"])
            if os.environ.get("PI_CODING_AGENT_DIR")
            else None,
        )
    context = SyncContext(
        skills_dir, agents_dir, selected, mode, harnesses, args.dry_run, home
    )
    return context, stored


def _install_skills(context: SyncContext) -> skills.ResolvedSelection:
    relations = skills.skill_relations()
    resolved = skills.resolve_selection(context.selected_skills, relations)
    for message in skills.install_canonical(
        context.skills_dir, resolved.skills, dry_run=context.dry_run
    ):
        print(message)
    for harness in context.harnesses:
        if harness.skills_dir is None:
            continue
        for skill in resolved.skills:
            print(
                skills.sync_entry(
                    harness.skills_dir,
                    context.skills_dir,
                    skill,
                    link_mode=context.link_mode,
                    dry_run=context.dry_run,
                )
            )
    for message in skills.remove_retired(
        context.skills_dir,
        [harness.skills_dir for harness in context.harnesses],
        context.dry_run,
    ):
        print(message)
    return resolved


def run(args: Sequence[str]) -> int:
    parsed: argparse.Namespace | None = None
    try:
        parsed = _parser().parse_args(list(args))
        check_old_store()
        context, stored = _context(parsed)
        if parsed.save and not context.dry_run:
            config.write(
                stored,
                context.skills_dir,
                context.agents_dir,
                context.link_mode,
                context.selected_skills,
            )
            save_config(stored)
        print(
            ("would use " if context.dry_run else "")
            + f"skills target: {context.skills_dir}"
        )
        print(
            ("would use " if context.dry_run else "")
            + f"agents target: {context.agents_dir}"
        )
        if context.dry_run:
            print(
                f"would use link mode: {context.link_mode}\n"
                "would process harnesses: "
                f"{', '.join(h.id.value for h in context.harnesses) or 'none'}"
            )
        else:
            print(
                f"link mode: {context.link_mode}\n"
                "harnesses: "
                f"{', '.join(h.id.value for h in context.harnesses) or 'none'}"
            )
        env = MigrateEnv.current(context.dry_run)
        report = Report()
        if parsed.save:
            support.pin_toz_store(env, report)
        resolved = _install_skills(context)
        agents.run(context)
        for harness in context.harnesses:
            support.rewrite_harness_with_features(
                env, harness.id.value, report, set(resolved.features)
            )
        targets = [
            _path(path, context.home, Path.cwd()) for path in parsed.instructions_target
        ]
        support.install_instructions(
            env, targets, support.instruction_sections(set(resolved.features)), report
        )
        if parsed.json:
            print(
                json.dumps(
                    success(report.data(), {"dry_run": context.dry_run}),
                    separators=(",", ":"),
                )
            )
        else:
            options = support.StepOptions(
                no_packs=parsed.no_packs, dry_run=context.dry_run, yes=parsed.yes
            )
            support.print_text_notes(report, Path.cwd(), options)
    except SystemExit as error:
        return int(error.code or 0)
    except (OSError, ValueError, SetupError, RuntimeError) as error:
        if isinstance(error, ValueError) and str(error).startswith(
            "unknown harness id: "
        ):
            value = str(error).removeprefix("unknown harness id: ")
            print(
                f"error: invalid value '{value}' for '--harnesses <IDS>': {error}\n\n"
                "For more information, try '--help'.",
                file=sys.stderr,
            )
            return 2
        message = str(error)
        if message.startswith("missing required target"):
            message = f"{message}\n{RECOMMENDED_LAYOUT}"
        else:
            message = f"varde setup sync: {message}"
        print(message, file=sys.stderr)
        if parsed is not None and parsed.json:
            print(
                json.dumps(
                    negative_result(
                        "sync_failed",
                        str(error),
                        {},
                        {"dry_run": bool(parsed.dry_run)},
                    ),
                    separators=(",", ":"),
                )
            )
        return getattr(error, "exit_code", 2 if isinstance(error, ValueError) else 1)
    else:
        return 0


__all__ = ["run"]
