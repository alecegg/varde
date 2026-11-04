"""Select memory entries for a session start within a character budget (pure)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Collection, Iterable, Sequence
from datetime import date

from varde_learn.memory.entry import Entry, is_slug, summary_of
from varde_learn.memory.expiry import is_expired
from varde_learn.memory.index import SUMMARY_LIMIT, IndexLine, render_index
from varde_learn.memory.share import MAX_TOPIC_CHARS, SHARED_PREFIX, single_line

SECTION_ORDER = ("skill", "agent", "project", "global")
MAX_TOPICS = 8


def visible_for_project(entry: Entry, project: str) -> bool:
    """An agent or skill entry with a `project` field applies to that project only."""
    return not entry.project or entry.project == project


AgentNames = str | Collection[str] | None


def _wanted_keys(scope: str, agent: AgentNames, skill: str | None, project: str):
    if scope == "agent":
        return {agent} if isinstance(agent, str) else set(agent or ())
    return {"skill": {skill}, "project": {project}}.get(scope, set())


def select_entries(
    entries: Iterable[Entry],
    agent: AgentNames,
    skill: str | None,
    project: str,
    today: date | None = None,
) -> list[Entry]:
    """Active, unexpired entries for the agent(s), skill and project, plus global."""
    today = today or date.today()
    return [
        e
        for e in entries
        if e.status == "active"
        and not is_expired(e, today)
        and visible_for_project(e, project)
        and (
            e.scope == "global"
            or e.scope_key in _wanted_keys(e.scope, agent, skill, project)
        )
    ]


def skills_with_memory(
    entries: Iterable[Entry], project: str, today: date | None = None
) -> list[tuple[str, int]]:
    """Skills with active, unexpired entries visible for `project`, with counts."""
    today = today or date.today()
    counts = Counter(
        e.scope_key
        for e in entries
        if e.scope == "skill"
        and e.status == "active"
        and not is_expired(e, today)
        and visible_for_project(e, project)
    )
    return sorted(counts.items())


def _counts_line(
    label: str, items: list[tuple[str, int]], tail: str, budget: int, limit: int
) -> str:
    """`label: a (3), b (2) +k more<tail>`, shrinking the names to fit `budget`."""
    line = ""
    for shown in range(min(limit, len(items)), -1, -1):
        names = ", ".join(f"{name} ({count})" for name, count in items[:shown])
        more = len(items) - shown
        if more:
            names = f"{names} +{more} more" if names else f"+{more} more"
        line = f"{label}: {names}{tail}"
        if len(line) <= budget:
            return line
    return line


def skill_memory_line(skills: list[tuple[str, int]], budget: int) -> str:
    """One line naming skills with memory; shrinks to `+<k> more` to fit `budget`."""
    tail = "; query: varde learn memory list --skill <name>"
    return _counts_line("Skill memory", skills, tail, budget, len(skills))


def topic_counts(
    local: Iterable[Entry], shared: Iterable[Entry]
) -> list[tuple[str, int]]:
    """Topics with counts, most used first; shared topics must be capped slugs."""
    counts: Counter[str] = Counter()
    for entry in local:
        if entry.topic:
            counts[single_line(entry.topic, MAX_TOPIC_CHARS)] += 1
    for entry in shared:
        if is_slug(entry.topic) and len(entry.topic) <= MAX_TOPIC_CHARS:
            counts[entry.topic] += 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def topics_line(topics: list[tuple[str, int]], budget: int) -> str:
    """One line with at most 8 topics and `+<k> more`, shrunk to fit `budget`."""
    tail = "; query: varde learn memory search --text <q> --topic <t>"
    return _counts_line("Topics", topics, tail, budget, MAX_TOPICS)


def fit_budget(lines: list[str], budget: int) -> tuple[list[str], int]:
    """Longest prefix of `lines` that fits, a line counting the rest, and that count."""
    if len(_joined(lines)) <= budget:
        return lines, 0
    for keep in range(len(lines), -1, -1):
        omitted = len(lines) - keep
        candidate = [*lines[:keep], _omitted_line(omitted)]
        if len(_joined(candidate)) <= budget:
            return candidate, omitted
    return [_omitted_line(len(lines))], len(lines)


def _joined(lines: list[str]) -> str:
    return "\n".join(lines)


def _omitted_line(count: int) -> str:
    return f"... {count} more omitted; varde learn memory list|show retrieves them"


def _pointer_order(entries: list[Entry]) -> list[Entry]:
    """Scope specificity, then newest `created`, then id."""
    ordered = sorted(entries, key=lambda e: e.id)
    ordered.sort(key=lambda e: e.created, reverse=True)
    ordered.sort(key=lambda e: SECTION_ORDER.index(e.scope))
    return ordered


def _pointer_line(entry: Entry, prefix: str = "") -> str:
    summary = single_line(summary_of(entry), SUMMARY_LIMIT)
    return render_index(
        [IndexLine(prefix + entry.id, entry.scope, summary, entry.tags)]
    )


def _surfaced(entries: list[Entry], skill: str | None) -> list[Entry]:
    shown = [e for e in entries if e.surface and (e.scope != "skill" or skill)]
    return _pointer_order(shown)


def entry_lines(entries: list[Entry], skill: str | None) -> list[str]:
    """Index lines of `surface: true` entries in pointer order."""
    return [_pointer_line(e) for e in _surfaced(entries, skill)]


def shared_entry_lines(entries: list[Entry], skill: str | None) -> list[str]:
    """Index lines for shared entries, ids prefixed `shared:`; never bodies."""
    return [_pointer_line(e, SHARED_PREFIX) for e in _surfaced(entries, skill)]


def render_surface(  # noqa: PLR0913 - one selection context, keyword-only
    entries: list[Entry],
    *,
    agent: AgentNames,
    skill: str | None,
    project: str,
    budget: int,
    root: str,
    shared: Sequence[Entry] = (),
    today: date | None = None,
) -> tuple[str, int]:
    """Return the pointer text and the number of omitted entries."""
    header = (
        f"Memory index at {root} (ids only; full text: varde learn memory show <id>)"
    )
    today = today or date.today()
    local = select_entries(entries, agent, skill, project, today)
    chosen = select_entries(shared, agent, skill, project, today)
    lines = entry_lines(local, skill) + shared_entry_lines(chosen, skill)
    room = budget - len(header) - 1
    head = [header]
    topics = topic_counts(local, chosen)
    if topics:
        line = topics_line(topics, room)
        head.append(line)
        room -= len(line) + 1
    skills = skills_with_memory([*entries, *shared], project, today)
    if skills and skill is None:
        line = skill_memory_line(skills, room)
        head.append(line)
        room -= len(line) + 1
    kept, omitted = fit_budget(lines, max(room, 0))
    return _joined([*head, *kept]), omitted
