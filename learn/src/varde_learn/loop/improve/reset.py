"""Propose slimming a skill or agent to outcomes plus validation (pure planning).

Kept: text before the first `## ` heading and sections whose heading matches
`KEEP` (outcomes, contract, validation, topics, on request). Every other
section becomes an on-request how topic (`<pkg>/how/<skill>/<step>.md`, or
`agents/<agent>/how/<step>.md`) and the `## Topics` (skill) or `## On request`
(agent) section gains a `how: <step> - <heading>` line. Nothing is lost.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from varde_learn.docs.flow.scan import text_tokens

from .extract import (
    ExtractError,
    FileChange,
    Plan,
    find_section_spans,
    slug,
    topic_file,
)
from .record import LoopRecord, hash_text

KEEP = re.compile(r"outcome|contract|validat|topics|on request", re.IGNORECASE)
KEEP_PLAIN = re.compile(r"outcome|contract|validat|on request", re.IGNORECASE)
_TOPICS = re.compile(r"^[# ]*topics$", re.IGNORECASE)
_HOW_LINE = re.compile(r"^how: .*\n?", re.MULTILINE)
_BASELINE_CHANGE = re.compile(r"to baseline (\S+) \(tree ([0-9a-f]{64})\)")
_VERSIONS = re.compile(r"model (\S+), harness (\S+):")
SKILL_TOPICS = "Topics"
AGENT_TOPICS = "On request"


class AlreadySlim(ExtractError):
    """Nothing left to move out of the text."""


@dataclass(frozen=True)
class Moved:
    step: str
    heading: str
    body: str


def slim_text(
    text: str, topics_heading: str, how_command: str
) -> tuple[str, list[Moved]]:
    """The slimmed text and the sections moved out of it."""
    kept, moved = _split_sections(text, KEEP, drop=None)
    return _with_how_lines(kept, moved, topics_heading, how_command), moved


def slim_text_plain(text: str) -> tuple[str, list[Moved]]:
    """The slimmed text with no `## Topics` section and no `how:` line, plus the
    sections moved out of it: a baseline carries no pointer to its how topics."""
    kept, moved = _split_sections(text, KEEP_PLAIN, drop=_TOPICS)
    return _HOW_LINE.sub("", kept).rstrip("\n") + "\n", moved


def _split_sections(
    text: str, keep: re.Pattern[str], drop: re.Pattern[str] | None
) -> tuple[str, list[Moved]]:
    spans = find_section_spans(text)
    kept: list[str] = [text[: spans[0][0]]] if spans else [text]
    moved: list[Moved] = []
    for start, end, heading in spans:
        chunk = text[start:end]
        if drop and drop.search(heading):
            continue
        if keep.search(heading):
            kept.append(chunk)
            continue
        body = chunk.split("\n", 1)[1] if "\n" in chunk else ""
        moved.append(Moved(slug(heading), heading, body.strip("\n")))
    steps = [item.step for item in moved]
    if not moved:
        raise AlreadySlim("already slim: no section to move")
    if len(steps) != len(set(steps)):
        raise ExtractError("two sections share one step name")
    return "".join(kept), moved


def _with_how_lines(
    text: str, moved: list[Moved], topics_heading: str, how_command: str
) -> str:
    lines = "\n".join(f"how: {item.step} - {item.heading}" for item in moved)
    spans = {heading.lower(): (s, e) for s, e, heading in find_section_spans(text)}
    found = spans.get(topics_heading.lower())
    if found is None:
        intro = (
            f"Request the topic with `{how_command}` when the step named in its "
            "summary applies."
        )
        return text.rstrip("\n") + f"\n\n## {topics_heading}\n\n{intro}\n\n{lines}\n"
    start, end = found
    section = text[start:end].rstrip("\n")
    tail = "\n\n" if end < len(text) else "\n"
    return text[:start] + section + "\n" + lines + tail + text[end:]


def _topic_changes(
    moved: list[Moved], topic_dir: Path, name: str, existing: set[str]
) -> list[FileChange]:
    clash = sorted(item.step for item in moved if item.step in existing)
    if clash:
        raise ExtractError(f"how topic already exists: {clash[0]}")
    return [
        FileChange(
            str(topic_dir / f"{item.step}.md"),
            None,
            topic_file(name, item.step, item.heading, item.body),
        )
        for item in moved
    ]


def plan_skill_reset(
    skill: str, skill_md: Path, text: str, how_dir: Path, existing: set[str]
) -> Plan:
    new, moved = slim_text(text, SKILL_TOPICS, f"varde learn how {skill} <step>")
    changes = [
        FileChange(str(skill_md), text, new),
        *_topic_changes(moved, how_dir, skill, existing),
    ]
    return Plan(tuple(changes), text_tokens(new) - text_tokens(text))


def plan_skill_plain_reset(
    skill: str, skill_md: Path, text: str, how_dir: Path, existing: set[str]
) -> Plan:
    """Slim to outcomes and validation; moved sections become how topics and the
    text keeps no pointer to them."""
    new, moved = slim_text_plain(text)
    changes = [
        FileChange(str(skill_md), text, new),
        *_topic_changes(moved, how_dir, skill, existing),
    ]
    return Plan(tuple(changes), text_tokens(new) - text_tokens(text))


def baseline_change(skill: str, gen: str, tree_hash: str) -> str:
    return f"reset {skill} to baseline {gen} (tree {tree_hash})"


def baseline_target(record: LoopRecord) -> tuple[str, str] | None:
    """The (generation, tree hash) a baseline-restore record promises."""
    found = _BASELINE_CHANGE.search(record.change)
    return (found[1], found[2]) if found else None


def plan_agent_reset(
    agent: str, caps_path: Path, caps_text: str, agent_dir: Path, existing: set[str]
) -> Plan:
    data = json.loads(caps_text)
    profile = next((p for p in data["profiles"] if p["name"] == agent), None)
    if profile is None:
        raise ExtractError(f"no agent profile '{agent}'")
    old = profile["instructions"]
    new, moved = slim_text(old, AGENT_TOPICS, f"varde learn how {agent} [step]")
    profile["instructions"] = new if old.endswith("\n") else new.rstrip("\n")
    changes = [
        FileChange(
            str(caps_path),
            caps_text,
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        ),
        *_topic_changes(moved, agent_dir / "how", agent, existing),
    ]
    return Plan(tuple(changes), text_tokens(profile["instructions"]) - text_tokens(old))


def reset_change(skill: str, model: str, harness: str, moved_count: int) -> str:
    return (
        f"reset {skill} for model {model}, harness {harness}: slim to outcomes "
        f"and validation; {moved_count} sections moved to on-request topics"
    )


def versions_of(record: LoopRecord) -> tuple[str, str] | None:
    """The (model, harness version) a reset record was made for."""
    found = _VERSIONS.search(record.change)
    return (found[1], found[2]) if found else None


def count_fields(
    counts: dict[str, int], route_before: int, route_after: int
) -> dict[str, int]:
    """Before-counts kept on the record (`later_demand` holds integer counts)."""
    before = {f"before {name}": value for name, value in counts.items()}
    return before | {
        "route tokens before": route_before,
        "route tokens after": route_after,
    }


def compare(record: LoopRecord, current: dict[str, int]) -> dict[str, tuple[int, int]]:
    """Per count: (before the reset, now) for the before-counts on a record."""
    return {
        name.removeprefix("before "): (
            value,
            current.get(name.removeprefix("before "), 0),
        )
        for name, value in record.later_demand.items()
        if name.startswith("before ") and not name.startswith("before route")
    }


def reset_id(skill: str, created: str) -> str:
    return f"r-{skill}"[:56].lower() + f"-{hash_text(created)[:7]}"


def build_record(
    skill: str,
    model: str,
    harness: str,
    plan: Plan,
    counts: dict[str, int],
    created: str,
) -> tuple[LoopRecord, str]:
    from .extract import pre_hashes, render_diff

    moved = len(plan.changes) - 1
    record = LoopRecord(
        id=reset_id(skill, created),
        skill=skill,
        direction="reset",
        change=reset_change(skill, model, harness, moved),
        created=created,
        token_delta=plan.token_delta,
        later_demand=counts,
        pre_hashes=pre_hashes(plan.changes),
    )
    return record, render_diff(plan.changes)
