"""Install and remove managed Varde instruction blocks."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from varde_core.constants import HOW_NOTE, LEARN_NOTE, toz_instruction_block
from varde_learn.knowledge.memory_config import load_config, save_config

from varde_workflow.blocks import (
    LEGACY_TOZ_MARKER,
    install_block,
    remove_blocks,
)

SETUP_WARNING = (
    "Varde will not work as designed until its instruction block is installed: "
    "agents will not delegate as designed or use captured command output. Install "
    "it with `varde setup instructions install --target <file>`. Use one canonical "
    "`AGENTS.md` symlinked into each harness."
)
TOZ_TEMPLATE = "<!-- varde-toz:start -->\n## varde-toz (tool-output-zone)\n\n{{TOZ_SHARED_NOTE}}\n<!-- varde-toz:end -->\n"
DEFAULT_CAPS = {
    "orchestrators": 4,
    "builders": 4,
    "planners": 2,
    "reviewers": 2,
    "explorers": 4,
}
SECTIONS = ("orchestration", "toz", "learn")


@dataclass(frozen=True)
class RoleCaps:
    orchestrators: int = 4
    builders: int = 4
    planners: int = 2
    reviewers: int = 2
    explorers: int = 4


def run(args) -> int:
    """Dispatch parsed instructions arguments."""
    if args.instructions_command == "targets":
        return targets()
    if args.instructions_command == "install":
        return install(args)
    return remove(args.dry_run)


def install(args) -> int:
    try:
        config = load_config()
    except Exception as exc:
        raise RuntimeError("could not load Varde config") from exc
    supplied_targets = bool(args.targets)
    orchestration = config.document.get("orchestration")
    if not isinstance(orchestration, dict):
        orchestration = {}
        if args.builders is not None:
            config.document["orchestration"] = orchestration
    if args.builders is not None:
        orchestration["builders"] = args.builders
        orchestration.pop("max_agents", None)

    if supplied_targets:
        paths = unique_targets(args.targets)
        config.document.setdefault("instructions", {})["targets"] = [
            str(path) for path in paths
        ]
    else:
        section = config.document.get("instructions", {})
        raw_targets = section.get("targets", []) if isinstance(section, dict) else []
        paths = unique_targets(
            [Path(target) for target in raw_targets if isinstance(target, str)]
        )

    if not args.dry_run and (supplied_targets or args.builders is not None):
        try:
            save_config(config)
        except Exception as exc:
            raise RuntimeError("could not save Varde config") from exc
    if not paths:
        print(SETUP_WARNING)
        return 0

    caps = resolved_caps(orchestration)
    sections = [] if args.sections == "" else args.sections.split(",")
    invalid = next((section for section in sections if section not in SECTIONS), None)
    if invalid is not None:
        raise ValueError(f"unknown instruction section: {invalid}")
    if args.learn and "learn" not in sections:
        sections.append("learn")
    block = render_block(caps, sections).encode()
    for path in paths:
        install_target(path, block, args.dry_run)
    return 0


def targets() -> int:
    config = load_config()
    section = config.document.get("instructions", {})
    for target in section.get("targets", []) if isinstance(section, dict) else []:
        print(target)
    return 0


def remove(dry_run: bool = False) -> int:
    config = load_config()
    section = config.document.get("instructions", {})
    configured = section.get("targets", []) if isinstance(section, dict) else []
    for path in unique_targets(
        [Path(target) for target in configured if isinstance(target, str)]
    ):
        try:
            content = path.read_bytes()
        except FileNotFoundError:
            continue
        except OSError as exc:
            print(
                f"varde-workflow instructions: cannot read {path}: {exc}",
                file=sys.stderr,
            )
            continue
        updated = remove_blocks(content)
        if updated == content:
            continue
        if dry_run:
            print(f"would remove the Varde instruction block from {path}")
        else:
            path.write_bytes(updated)
    if not dry_run and isinstance(section, dict) and section.get("targets"):
        section["targets"] = []
        save_config(config)
    return 0


def unique_targets(paths: list[str | Path]) -> list[Path]:
    result = []
    seen = set()
    for iter_path in paths:
        path = Path(iter_path)
        absolute = Path.cwd() / path if not path.is_absolute() else path
        absolute = Path(_normalize(absolute))
        try:
            key = absolute.resolve(strict=True)
        except OSError:
            try:
                key = absolute.parent.resolve(strict=True) / absolute.name
            except OSError:
                key = absolute
        if key not in seen:
            seen.add(key)
            result.append(absolute)
    return result


def _normalize(path: Path) -> str:
    parts = []
    for part in path.parts:
        if part == "..":
            if parts and parts[-1] != "..":
                parts.pop()
            elif not path.is_absolute():
                parts.append(part)
        elif part != ".":
            parts.append(part)
    return str(Path(*parts))


def resolved_caps(orchestration: dict) -> RoleCaps:
    values = {}
    for key, default in DEFAULT_CAPS.items():
        raw = orchestration.get(key)
        if key == "builders" and raw is None:
            raw = orchestration.get("max_agents")
        if raw is None:
            values[key] = default
        elif (
            isinstance(raw, int) and not isinstance(raw, bool) and 0 < raw <= 2**32 - 1
        ):
            values[key] = raw
        else:
            reason = (
                "`orchestration` is not a table"
                if orchestration is None
                else f"{raw!r} is not a positive integer"
            )
            print(
                (
                    f"varde-workflow instructions: orchestration {key} ignored "
                    f"({reason}); using {default}"
                ),
                file=sys.stderr,
            )
            values[key] = default
    return RoleCaps(**values)


def render_block(caps: RoleCaps, sections: list[str]) -> str:
    body = []
    if "orchestration" in sections:
        body.append(orchestration_brief(caps))
    if "toz" in sections:
        body.append(toz_instruction_block(TOZ_TEMPLATE).strip())
    if "learn" in sections:
        learn_block = (
            f"<!-- varde-learn:start -->\n## varde-learn\n\n{LEARN_NOTE}\n\n{HOW_NOTE}\n"
            "<!-- varde-learn:end -->"
        )
        body.append(learn_block)
    return "<!-- varde:start -->\n" + "\n\n".join(body) + "\n<!-- varde:end -->"


def orchestration_brief(caps: RoleCaps) -> str:
    return (
        "Orchestration: you are the main agent, the session manager: talk to the user, launch one orchestrator per plan, relay decisions and approvals, keep session notes; do not explore or implement. Orchestrators run their plan's workers, reviewers, merges, sync, memory commits and `varde plan conclude`.\n"
        "Use `varde-plan` when scope is unsettled. Then choose `varde-build` for one task or `varde-orchestrate` for several tasks. Run several plans one at a time via `varde-orchestrate`; use `varde-swarm` only when the user asks.\n"
        f"Role caps per orchestrator: {caps.builders} builders, {caps.planners} planners, {caps.reviewers} reviewers, {caps.explorers} explorers; at most {caps.orchestrators} orchestrators, one per plan.\n"
        "Orchestrators and workers report milestones with `varde msg send` to `main`; their final reply is one line. Main agent status format: see varde-swarm `references/status.md`. On a wake-up or without the per-prompt hook, the main agent runs `varde msg read`.\n"
        "Update the hand-written part of the session notes when a rule is set or a decision opens or closes; tidy it when nudged, before compaction, or on request, and never edit the generated block.\n"
        "Run `varde plan watch --stale 20m --notes <session notes path from the session-start hook>` under your harness's monitor while orchestrators run; the session notes block shows plan state.\n"
        "If you were launched with a bounded task, follow that brief instead."
    )


def install_target(path: Path, block: bytes, dry_run: bool) -> None:
    try:
        existing = path.read_bytes()
    except FileNotFoundError:
        existing = b""
    except OSError as exc:
        _write_failure(path, block, exc)
        return
    if LEGACY_TOZ_MARKER in existing:
        print(
            (
                f"varde-workflow instructions: {path} contains a legacy varde-toz "
                "block; run `varde setup sync` to remove it"
            ),
            file=sys.stderr,
        )
    updated = install_block(existing, block)
    if updated == existing:
        return
    if dry_run:
        print(f"would write the Varde instruction block to {path}:\n{block.decode()}")
        return
    try:
        path.write_bytes(updated)
    except OSError as exc:
        _write_failure(path, block, exc)


def _write_failure(path: Path, block: bytes, error: OSError) -> None:
    print(
        f"varde-workflow instructions: could not write {path}: {error}", file=sys.stderr
    )
    print(block.decode())
