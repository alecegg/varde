"""Serve step-sized how-topics from module package data.

Skills use ``<pkg>/how/<skill>/<step>.md``; agents use
``<pkg>/agents/<agent>/how/<step>.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from importlib.metadata import entry_points
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

import yaml

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.DOTALL)


@dataclass(frozen=True)
class Topic:
    skill: str
    step: str
    topic: str
    version: int
    summary: str
    body: str

    @property
    def id(self) -> str:
        return f"{self.skill}/{self.step}"


def parse_topic(skill: str, step: str, text: str) -> Topic:
    """Parse one topic file; raise ``ValueError`` on bad frontmatter."""
    match = _FRONTMATTER.match(text)
    if match is None:
        raise ValueError(f"{skill}/{step}: missing frontmatter")
    meta = yaml.safe_load(match.group(1))
    if not isinstance(meta, dict):
        raise TypeError(f"{skill}/{step}: frontmatter is not a mapping")
    for key in ("topic", "version", "summary"):
        if key not in meta:
            raise ValueError(f"{skill}/{step}: frontmatter lacks '{key}'")
    return Topic(
        skill,
        step,
        str(meta["topic"]),
        int(meta["version"]),
        str(meta["summary"]),
        match.group(2).strip("\n"),
    )


def provider_roots() -> list[Traversable]:
    """The ``how`` tree of every installed ``varde.skills`` provider."""
    return [files(point.value) / "how" for point in entry_points(group="varde.skills")]


def agent_roots() -> list[Traversable]:
    """The ``agents`` tree of every installed ``varde.agents`` provider."""
    points = entry_points(group="varde.agents")
    return [files(point.value) / "agents" for point in points]


def _load_steps(
    name: str, directory: Traversable, found: dict[str, dict[str, Topic]]
) -> None:
    for file in sorted(directory.iterdir(), key=lambda item: item.name):
        if not file.name.endswith(".md"):
            continue
        step = file.name.removesuffix(".md")
        found.setdefault(name, {})[step] = parse_topic(
            name, step, file.read_text(encoding="utf-8")
        )


def _named_dirs(root: Traversable) -> list[Traversable]:
    if not root.is_dir():
        return []
    return [
        item
        for item in sorted(root.iterdir(), key=lambda item: item.name)
        if item.is_dir() and not item.name.startswith((".", "_"))
    ]


def load_topics(roots: list[Traversable]) -> dict[str, dict[str, Topic]]:
    """Map skill to step to topic across the given ``how`` roots."""
    found: dict[str, dict[str, Topic]] = {}
    for root in roots:
        for skill_dir in _named_dirs(root):
            _load_steps(skill_dir.name, skill_dir, found)
    return found


def load_agent_topics(roots: list[Traversable]) -> dict[str, dict[str, Topic]]:
    """Map agent to step to topic across the given ``agents`` roots."""
    found: dict[str, dict[str, Topic]] = {}
    for root in roots:
        for agent_dir in _named_dirs(root):
            how = agent_dir / "how"
            if how.is_dir():
                _load_steps(agent_dir.name, how, found)
    return found


def load_installed_topics(skill_dirs: list[Path]) -> dict[str, dict[str, Topic]]:
    """Topics of synced skill dirs that hold a ``how/`` tree with topic files."""
    found: dict[str, dict[str, Topic]] = {}
    for skill_dir in skill_dirs:
        how = skill_dir / "how"
        if how.is_dir() and any(how.glob("*.md")):
            _load_steps(skill_dir.name, how, found)
    return found


def all_topics(
    skill_roots: list[Traversable],
    agent_tree: list[Traversable],
    installed: dict[str, dict[str, Topic]] | None = None,
) -> dict[str, dict[str, Topic]]:
    """Skill and agent topics together; a skill wins a name clash.

    A skill with installed topics uses only those, so a step removed
    locally stays removed.
    """
    return {
        **load_agent_topics(agent_tree),
        **load_topics(skill_roots),
        **(installed or {}),
    }


def step_line(topic: Topic) -> str:
    return f"{topic.step} - {topic.summary}"


def valid_ids_message(
    topics: dict[str, dict[str, Topic]], skill: str, step: str | None
) -> str:
    """Name what was not found and the valid ids."""
    if skill not in topics:
        valid = ", ".join(sorted(topics)) or "none"
        return f"unknown skill '{skill}'; valid skills: {valid}"
    return (
        f"unknown step '{step}' for skill '{skill}'; "
        f"valid steps: {', '.join(sorted(topics[skill]))}"
    )


def topic_json(topic: Topic, *, with_body: bool) -> dict[str, object]:
    data: dict[str, object] = {
        "id": topic.id,
        "step": topic.step,
        "topic": topic.topic,
        "version": topic.version,
        "summary": topic.summary,
    }
    if with_body:
        data["body"] = topic.body
    return data
