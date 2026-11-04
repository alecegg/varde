"""Rank skills and agent definitions to add to, trim or reset (report-only).

Direction rule, applied before ranking so opposite signals never share a score:

- `add`: friction signals (friction items, how-skip friction or failed how
  requests) are above zero; the target asks for more.
- `reset`: no friction signal and route tokens at or above RESET_TOKENS.
- `trim`: no friction signal and route tokens at or above TRIM_TOKENS.
- otherwise the target is not listed.

Within a direction the sort key is friction count, then route tokens, then
name. There are no weights and no actions; evals are never read.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from varde_learn.docs.flow.analyze import analyze_skill
from varde_learn.docs.flow.scan import text_tokens

from . import tool_entry

TRIM_TOKENS = 1000
RESET_TOKENS = 4000
DIRECTIONS = ("add", "trim", "reset")


@dataclass(frozen=True)
class Target:
    name: str
    kind: str  # "skill" or "agent"
    tokens: int


@dataclass(frozen=True)
class BaselineState:
    """A skill's newest baseline entry: its generation and whether the skill
    still equals it (tree hash match, no drift)."""

    gen: str
    at_baseline: bool


@dataclass(frozen=True)
class Candidate:
    name: str
    kind: str
    direction: str
    tokens: int
    friction: int
    how_skip: int
    failures: int
    how_requests: int
    tool_calls: int
    baseline: str = ""  # generation of the skill's baseline entry, when it has one
    evidence: dict[str, Any] | None = None  # fill-record evidence (baseline add)


def direction_for(
    friction_signals: int,
    tokens: int,
    trim_at: int,
    reset_at: int,
    baseline: BaselineState | None = None,
) -> str | None:
    """`reset` means a very large route (size only) for a skill without a baseline
    entry, and a baseline restore for one with a drifted entry. A skill already at
    its baseline is never a `reset` or `trim` candidate."""
    if friction_signals > 0:
        return "add"
    if baseline is not None and baseline.at_baseline:
        return None
    if tokens >= reset_at:
        return "reset"
    if tokens >= trim_at:
        return "trim"
    return None


def rank(
    targets: Iterable[Target],
    demand: dict[str, Any],
    tool_steps: frozenset[str] = frozenset(),
    *,
    trim_at: int = TRIM_TOKENS,
    reset_at: int = RESET_TOKENS,
    baselines: dict[str, BaselineState] | None = None,
) -> dict[str, list[Candidate]]:
    """Group targets by direction, each group sorted (pure)."""
    skills = {row["skill"]: row for row in demand.get("skills", [])}
    steps = demand.get("steps", [])
    groups: dict[str, list[Candidate]] = {name: [] for name in DIRECTIONS}
    for target in targets:
        state = (baselines or {}).get(target.name)
        candidate = _candidate(
            target, skills.get(target.name, {}), steps, tool_steps, state
        )
        signals = candidate.friction + candidate.failures
        direction = direction_for(signals, candidate.tokens, trim_at, reset_at, state)
        if direction:
            groups[direction].append(_with_direction(candidate, direction))
    for items in groups.values():
        items.sort(key=lambda c: (-c.friction, -c.tokens, c.name))
    return groups


def fill_evidence(
    skill: dict[str, Any], own: list[dict], how_requests: int
) -> dict[str, Any]:
    """The evidence block of a fill record: friction ids filed with
    `--target how/<skill>/<step>`, suspected skips and how requests."""
    return {
        "friction": sorted({fid for row in own for fid in row.get("friction_ids", [])}),
        "suspected_skips": skill.get("suspected_skips") or 0,
        "how_requests": how_requests,
    }


def _candidate(
    target: Target,
    skill: dict[str, Any],
    steps: list[dict],
    tool_steps: frozenset[str],
    state: BaselineState | None = None,
) -> Candidate:
    own = [row for row in steps if row["step"].split("/", 1)[0] == target.name]
    tool_rows = [row for row in own if row["step"] in tool_steps]
    requests = sum(row["requests"] for row in own) - sum(
        r["requests"] for r in tool_rows
    )
    return Candidate(
        target.name,
        target.kind,
        "",
        target.tokens,
        skill.get("friction_items", 0) + skill.get("how_skip_friction", 0),
        skill.get("how_skip_friction", 0),
        sum(row["failures"] for row in own),
        requests,
        sum(row["requests"] for row in tool_rows),
        state.gen if state else "",
        fill_evidence(skill, own, requests) if state else None,
    )


def _with_direction(candidate: Candidate, direction: str) -> Candidate:
    return Candidate(**{**asdict(candidate), "direction": direction})


def to_json_data(groups: dict[str, list[Candidate]]) -> dict[str, Any]:
    return {"directions": {d: [asdict(c) for c in groups[d]] for d in DIRECTIONS}}


def format_text(groups: dict[str, list[Candidate]]) -> str:
    lines = []
    for direction in DIRECTIONS:
        lines.append(f"{direction} ({len(groups[direction])})")
        lines.extend(_text_row(c) for c in groups[direction])
    return "\n".join(lines) + "\n"


def _text_row(c: Candidate) -> str:
    label = (
        f"  baseline restore ({c.baseline})"
        if c.direction == "reset" and c.baseline
        else ""
    )
    evidence = (
        f"  fill evidence {json.dumps(c.evidence, separators=(',', ':'))}"
        if c.direction == "add" and c.evidence
        else ""
    )
    return (
        f"  {c.name} [{c.kind}]  tokens {c.tokens}  friction {c.friction}  "
        f"how-skip {c.how_skip}  failures {c.failures}  "
        f"how requests {c.how_requests}  tool calls {c.tool_calls}{label}{evidence}"
    )


def gather_targets(dirs: Iterable[Path]) -> list[Target]:
    """Skills and agent definitions under module roots or plain skills dirs.

    An agent's route is its instructions plus the skills its profile loads, so
    skills from every root are known before agents are sized.
    """
    roots = list(dirs)
    by_name: dict[str, Path] = {}
    for root in roots:
        for directory in _skill_dirs(_skills_dir(root)):
            by_name.setdefault(directory.name, directory)  # first root wins
    skill_dirs = list(by_name.values())
    skill_tokens = {d.name: _skill_md_tokens(d) for d in skill_dirs}
    found = [_skill_target(d) for d in skill_dirs]
    for root in roots:
        found += _agent_targets(root / "agents" / "capabilities.json", skill_tokens)
    return found


def agent_tokens(
    instructions: str, skill_tokens: dict[str, int], skills: list[str]
) -> int:
    """Instruction tokens plus the SKILL.md tokens of each loaded skill (pure)."""
    return text_tokens(instructions) + sum(skill_tokens.get(s, 0) for s in skills)


def _skills_dir(root: Path) -> Path:
    return root / "skills" if (root / "skills").is_dir() else root


def _skill_dirs(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if (p / "SKILL.md").is_file())


def _skill_target(skill_dir: Path) -> Target:
    analysis = analyze_skill(skill_dir)
    route_max = max((r.max_tokens for r in analysis.routes), default=0)
    own = analysis.tokens.get("SKILL.md") or 0
    return Target(skill_dir.name, "skill", max(route_max, own))


def _skill_md_tokens(skill_dir: Path) -> int:
    return text_tokens((skill_dir / "SKILL.md").read_text(encoding="utf-8"))


def _agent_targets(caps: Path, skill_tokens: dict[str, int]) -> list[Target]:
    if not caps.is_file():
        return []
    profiles = json.loads(caps.read_text()).get("profiles", [])
    return [
        Target(
            p["name"],
            "agent",
            agent_tokens(p.get("instructions", ""), skill_tokens, p.get("skills", [])),
        )
        for p in profiles
        if (caps.parent / p["name"]).is_dir()
    ]


def registered_steps(dirs: Iterable[Path]) -> frozenset[str]:
    return frozenset(
        f"{row.skill}/{row.step}" for row in tool_entry.all_rows(list(dirs))
    )
