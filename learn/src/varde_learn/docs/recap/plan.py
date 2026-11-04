"""Read a plan's ownership and block links from its files."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from varde_learn.docs.pages.blocks.check import SPECS
from varde_learn.docs.pages.blocks.fences import find_fences
from varde_learn.docs.pages.lines import parse_lines


@dataclass(frozen=True)
class Task:
    id: str  # task file stem
    owns: tuple[str, ...]
    blocks: tuple[str, ...]  # block ids named by `blocks:` in the task file

    @property
    def short_id(self) -> str:
        return self.id.split("-", 1)[0]


@dataclass(frozen=True)
class Plan:
    shared: tuple[str, ...]
    tasks: tuple[Task, ...]
    block_ids: tuple[str, ...]
    covers: dict[str, tuple[str, ...]] = field(
        default_factory=dict
    )  # block -> task refs


def front_matter(text: str) -> dict[str, object]:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    data = yaml.safe_load(text[3:end])
    return data if isinstance(data, dict) else {}


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(str(v) for v in value if isinstance(v, str) and v.strip())


def read_task(path: Path) -> Task:
    meta = front_matter(path.read_text(encoding="utf-8"))
    return Task(path.stem, _strings(meta.get("owns")), _strings(meta.get("blocks")))


def block_links(text: str) -> tuple[tuple[str, ...], dict[str, tuple[str, ...]]]:
    """Typed block ids in document order, and each block's `covers` list."""
    ids: list[str] = []
    covers: dict[str, tuple[str, ...]] = {}
    for fence in find_fences(text, frozenset({"ui"})):
        for statement in parse_lines(fence.body, partial=True).statements:
            if statement.component not in SPECS:
                continue
            ids.append(statement.id)
            if refs := _strings(statement.props.get("covers")):
                covers[statement.id] = refs
    return tuple(dict.fromkeys(ids)), covers


def read_plan(plan_file: Path) -> Plan:
    text = plan_file.read_text(encoding="utf-8")
    shared = _strings(front_matter(text).get("shared"))
    task_files = sorted((plan_file.parent / "tasks").glob("*.md"))
    ids, covers = block_links(text)
    return Plan(shared, tuple(read_task(p) for p in task_files), ids, covers)
