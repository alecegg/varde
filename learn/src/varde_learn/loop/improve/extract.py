"""Propose moving one step into a counted tool (pure planning; no file writes).

A skill step is the how topic `<pkg>/how/<skill>/<step>.md`: the proposal
replaces its body with a pointer to the wrapper and moves the text into the
tool script. An agent step is a `## Heading` section of the profile's
`instructions` in `capabilities.json` (step = heading slug): the section body
becomes the pointer, the text moves to `agents/<agent>/how/<step>.md` and the
tool script. The whole-route token delta counts only text a run loads: the
topic body or the instructions; the new tool and topic files load on request.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import yaml

from varde_learn.docs.flow.scan import text_tokens

from . import filediff, tool_entry
from .record import LoopRecord, hash_text
from .shim import POINTER_PATH

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)
_SECTION = re.compile(r"^## (.+)$", re.MULTILINE)
JUDGMENT_MARK = "<!-- judgment -->"
NO_HOW_HINT = "Skills with no how topics: use skills reset."


class ExtractError(ValueError):
    """The step cannot be extracted; the message says why."""


@dataclass(frozen=True)
class FileChange:
    path: str
    old: str | None  # None: the file does not exist yet
    new: str | None  # None: delete the file


@dataclass(frozen=True)
class Existing:
    """Current text of files the proposal may create; None when absent."""

    registry: str | None = None
    tool: str | None = None
    topic: str | None = None


@dataclass(frozen=True)
class Plan:
    changes: tuple[FileChange, ...]
    token_delta: int


def pointer(skill: str, step: str) -> str:
    return f"Run the counted step tool: `sh {POINTER_PATH} {skill}/{step}`"


def slug(heading: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")


def tool_source(skill: str, step: str, text: str) -> str:
    return (
        f'"""Step tool for {skill}/{step}: the step text moved out of the skill."""\n\n'
        f"STEP_TEXT = {text.strip()!r}\n\n\n"
        "def run(args: list[str]) -> int:\n"
        "    print(STEP_TEXT)\n"
        "    return 0\n"
    )


def tool_changes(
    module_root: Path,
    skill: str,
    step: str,
    text: str,
    existing: Existing,
) -> list[FileChange]:
    if existing.tool is not None:
        raise ExtractError(f"tool script already exists for {skill}/{step}")
    row = tool_entry.ToolRow(skill, step, tool_entry.entry_for(skill, step))
    try:
        registry = tool_entry.add_row(existing.registry or "", row)
    except tool_entry.ToolError as error:
        raise ExtractError(str(error)) from error
    script = module_root / tool_entry.TOOLS_DIR / row.entry
    registry_file = tool_entry.registry_path(module_root)
    return [
        FileChange(str(script), None, tool_source(skill, step, text)),
        FileChange(str(registry_file), existing.registry, registry),
    ]


def split_topic(text: str) -> tuple[dict, str, str]:
    """Frontmatter mapping, its raw text and the body of a how topic."""
    match = _FRONTMATTER.match(text)
    if match is None:
        raise ExtractError("how topic has no frontmatter")
    meta = yaml.safe_load(match.group(1))
    if not isinstance(meta, dict):
        raise ExtractError("how topic frontmatter is not a mapping")
    return meta, match.group(1), match.group(2).strip("\n")


def plan_skill_step(
    skill: str,
    step: str,
    topic_path: Path,
    topic_text: str,
    module_root: Path,
    existing: Existing,
) -> Plan:
    meta, raw_meta, body = split_topic(topic_text)
    if meta.get("judgment") is True:
        raise ExtractError(f"{skill}/{step} is a judgment step; it stays in text")
    new_topic = f"---\n{raw_meta}\n---\n\n{pointer(skill, step)}\n"
    changes = [
        FileChange(str(topic_path), topic_text, new_topic),
        *tool_changes(module_root, skill, step, body, existing),
    ]
    delta = text_tokens(new_topic) - text_tokens(topic_text)
    return Plan(tuple(changes), delta)


def find_section_spans(text: str) -> list[tuple[int, int, str]]:
    """Start, end and heading of every `## ` section (heading line included)."""
    matches = list(_SECTION.finditer(text))
    if not matches:
        return []
    ends = [m.start() for m in matches[1:]] + [len(text)]
    return [(m.start(), end, m.group(1)) for m, end in zip(matches, ends, strict=True)]


def section_slugs(instructions: str) -> list[str]:
    """Step names of an agent: the slug of every `## ` heading."""
    return [slug(match.group(1)) for match in _SECTION.finditer(instructions)]


def format_steps(steps: Iterable[str]) -> str:
    return "".join(f"{step}\n" for step in sorted(set(steps)))


def unknown_step_message(name: str, step: str, steps: Iterable[str]) -> str:
    valid = ", ".join(sorted(set(steps))) or "none"
    return (
        f"no step '{step}' for skill or agent '{name}'. valid steps: {valid}. "
        f"{NO_HOW_HINT}"
    )


def find_section(instructions: str, step: str) -> tuple[int, int, str]:
    """Body start, body end and heading of the `## ` section whose slug is `step`."""
    matches = list(_SECTION.finditer(instructions))
    for index, match in enumerate(matches):
        if slug(match.group(1)) != step:
            continue
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(instructions)
        )
        return match.end(), end, match.group(1)
    raise ExtractError(f"no instructions section for step '{step}'")


def topic_file(agent: str, step: str, heading: str, body: str) -> str:
    return (
        f"---\ntopic: {agent}/{step}\nversion: 1\nsummary: {heading}\n---\n\n"
        f"{body.strip()}\n"
    )


def plan_agent_step(
    agent: str,
    step: str,
    capabilities_path: Path,
    capabilities_text: str,
    agent_dir: Path,
    existing: Existing,
) -> Plan:
    data = json.loads(capabilities_text)
    profile = next((p for p in data["profiles"] if p["name"] == agent), None)
    if profile is None:
        raise ExtractError(f"no agent profile '{agent}'")
    instructions = profile["instructions"]
    start, end, heading = find_section(instructions, step)
    body = instructions[start:end]
    if JUDGMENT_MARK in body:
        raise ExtractError(f"{agent}/{step} is a judgment step; it stays in text")
    if existing.topic is not None:
        raise ExtractError(f"how topic already exists for {agent}/{step}")
    leading = body[: len(body) - len(body.lstrip("\n"))]
    tail = body[len(body.rstrip("\n")) :]
    profile["instructions"] = (
        instructions[:start]
        + leading
        + pointer(agent, step)
        + tail
        + instructions[end:]
    )
    new_capabilities = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    topic = agent_dir / "how" / f"{step}.md"
    changes = [
        FileChange(str(capabilities_path), capabilities_text, new_capabilities),
        FileChange(str(topic), None, topic_file(agent, step, heading, body)),
        *tool_changes(agent_dir, agent, step, body, existing),
    ]
    delta = text_tokens(profile["instructions"]) - text_tokens(instructions)
    return Plan(tuple(changes), delta)


def render_diff(changes: tuple[FileChange, ...]) -> str:
    return "".join(
        filediff.make_file_diff(change.path, change.old, change.new)
        for change in changes
    )


def pre_hashes(changes: tuple[FileChange, ...]) -> dict[str, str]:
    return {
        change.path: filediff.ABSENT if change.old is None else hash_text(change.old)
        for change in changes
    }


def proposal_id(skill: str, step: str, created: str) -> str:
    base = f"x-{skill}-{step}".lower()
    return f"{base[:56]}-{hash_text(created)[:7]}"


def build_record(
    skill: str, step: str, plan: Plan, created: str
) -> tuple[LoopRecord, str]:
    """The proposal record and its diff text; nothing is written."""
    record = LoopRecord(
        id=proposal_id(skill, step, created),
        skill=skill,
        direction="trim",
        change=f"extract {skill}/{step} into a counted step tool",
        created=created,
        token_delta=plan.token_delta,
        pre_hashes=pre_hashes(plan.changes),
    )
    return record, render_diff(plan.changes)
