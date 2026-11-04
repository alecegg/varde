"""Data types shared by skill flow scanning and analysis."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TypeVar

FAN_OUT = 6
DENSITY = 2
CYCLOMATIC_WARN = 10
COGNITIVE_WARN = 10
COGNITIVE_ERROR = 15
ROUTE_FILES_WARN = 15
DIAGRAM_EDGES_WARN = 60
ROUTE_ABSENT = object()

V = TypeVar("V")


class EdgeKind(StrEnum):
    LOAD = "load"
    HANDOFF = "handoff"
    MENTION = "mention"
    ROLE = "role"


@dataclass(frozen=True)
class Edge:
    from_: str
    to: str
    context: str
    conditional: bool
    kind: EdgeKind
    table: bool
    line: int
    route: str | None | object = ROUTE_ABSENT


class ExternalType(StrEnum):
    AGENT = "agent"
    SKILL = "skill"


@dataclass(frozen=True)
class Runs:
    """An untagged Rust Runs variant, represented by its two optional keys."""

    file: str | None = None
    skill: str | None = None
    mode: str | None = None

    def __post_init__(self) -> None:
        is_file = self.file is not None and self.skill is None and self.mode is None
        is_skill = (
            self.file is None and self.skill is not None and self.mode is not None
        )
        if not (is_file or is_skill):
            raise ValueError("Runs must contain either file or both skill and mode")


@dataclass(frozen=True)
class External:
    from_: str
    external: ExternalType
    target: str
    skill: str
    mode: str
    runs: Runs | None
    context: str
    conditional: bool
    kind: EdgeKind
    table: bool
    line: int
    qualifier: str | None = None
    route: str | None | object = ROUTE_ABSENT
    report_order: bool = False

    def is_handoff(self) -> bool:
        return self.external == ExternalType.SKILL and self.kind == EdgeKind.HANDOFF

    def serves_route(self, route: str) -> bool:
        own_route = self.route
        return self.from_ == "SKILL.md" and (
            own_route is ROUTE_ABSENT or own_route is None or own_route == route
        )


@dataclass(frozen=True)
class OrderedMap[V]:
    items: tuple[tuple[str, V], ...] | list[tuple[str, V]]

    def get(self, key: str) -> V | None:
        return next((value for item_key, value in self.items if item_key == key), None)

    def contains_key(self, key: str) -> bool:
        return any(item_key == key for item_key, _ in self.items)

    def iter(self):
        return iter(self.items)


@dataclass(frozen=True)
class Inline:
    target: str
    resolved: str


@dataclass(frozen=True)
class Dispatch:
    agent: str
    runs: str
    from_: list[str]
    conditional: bool
    min_tokens: int | None
    max_tokens: int | None
    files: list[DispatchFile]


@dataclass(frozen=True)
class DispatchFile:
    file: str
    tokens: int
    via: str


@dataclass(frozen=True)
class Route:
    route: str
    entry: list[str]
    files: list[str]
    min_files: list[str]
    min_tokens: int
    max_tokens: int
    handoffs: list[str]
    cyclomatic: int
    cognitive: int
    lookups: int
    main_min_tokens: int
    main_max_tokens: int
    inline: list[Inline]
    unresolved: list[str]
    dispatches: list[Dispatch]


@dataclass(frozen=True)
class Structure:
    mutual_links: int
    mutual_pairs: list[list[str]]
    max_links_out: int
    max_links_out_file: str | None
    average_links: float
    linking_files: int
    links: int
    links_out: OrderedMap[int]
    cross_module_edges: int
    diagram_edges: int
    max_route_cyclomatic: int | None = None
    max_route_cognitive: int | None = None
    max_route_files: int | None = None
    max_route_files_route: str | None = None


@dataclass(frozen=True)
class CallerFinding:
    file: str
    caller: str


@dataclass(frozen=True)
class SharedFinding:
    file: str
    callers: list[str]


@dataclass(frozen=True)
class MissingFinding:
    from_: str
    line: int
    target: str


@dataclass(frozen=True)
class CycleFinding:
    files: list[str]


@dataclass(frozen=True)
class FanOutFinding:
    file: str
    links: int


@dataclass(frozen=True)
class DensityFinding:
    average: float


@dataclass(frozen=True)
class Findings:
    chain: list[CallerFinding]
    single_caller: list[CallerFinding]
    shared: list[SharedFinding]
    unreferenced: list[str]
    missing: list[MissingFinding]
    cycle: list[CycleFinding]
    fan_out: list[FanOutFinding]
    density: list[DensityFinding]


@dataclass(frozen=True)
class HowTopic:
    """One step topic served by ``varde learn how``; never part of a route."""

    id: str
    tokens: int


@dataclass(frozen=True)
class Analysis:
    skill: str
    tokens: OrderedMap[int]
    references: list[str]
    edges: list[Edge]
    external: list[External]
    routes: list[Route]
    structure: Structure
    findings: Findings
    how_topics: list[HowTopic] = field(default_factory=list)
    how_total_tokens: int = 0
