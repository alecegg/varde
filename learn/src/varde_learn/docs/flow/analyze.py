"""Build route, structure, and finding data from scanned skill files."""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from varde_learn.docs.flow import (
    COGNITIVE_ERROR,
    COGNITIVE_WARN,
    CYCLOMATIC_WARN,
    DENSITY,
    DIAGRAM_EDGES_WARN,
    FAN_OUT,
    ROUTE_ABSENT,
    ROUTE_FILES_WARN,
    Analysis,
    CallerFinding,
    CycleFinding,
    DensityFinding,
    Dispatch,
    Edge,
    EdgeKind,
    External,
    FanOutFinding,
    Findings,
    HowTopic,
    Inline,
    MissingFinding,
    OrderedMap,
    Route,
    SharedFinding,
    Structure,
    scan,
)
from varde_learn.docs.flow.scan import Pointer, Scanned, SkillDir

DIRS = ("references", "scripts", "assets")
GATE = ("references/review-gates.md",)
BUILDER = ("varde-build", "builder")
SKIP = re.compile(r"(?i)\bskips?\b")
PRELOADS = re.compile(r"(?m)^skills:\s*(.+)$")
_ANALYZED_PATHS: dict[str, Path] = {}


def module_of(path: str) -> str:
    top = path.split("/", 1)[0]
    if top in {"scripts", "assets"}:
        return top
    return Path(path).stem.split("-", 1)[0]


def agent_dir(target: str) -> str:
    return "varde-builder" if target == "builder" else "varde-reviewer"


def preloaded_skills(definition: str) -> list[str]:
    head = definition.split("\n---", 1)[0]
    found = PRELOADS.search(head)
    return [name.strip() for name in found[1].split(",")] if found else []


def unique(items):
    return list(dict.fromkeys(items))


def sorted_unique(items: list[str]) -> list[str]:
    return sorted(set(items))


def dedupe_inline(pairs: list[tuple[str, str]]) -> list[Inline]:
    out: list[Inline] = []
    for target, resolved in pairs:
        existing = next((item for item in out if item.target == target), None)
        if existing:
            out[out.index(existing)] = Inline(target, resolved)
        else:
            out.append(Inline(target, resolved))
    return out


def merged_handoffs(route: Route, external: list[External]) -> list[str]:
    reached = [
        item
        for item in external
        if item.is_handoff()
        and (item.serves_route(route.route) or item.from_ in route.files)
    ]
    return sorted(set(route.handoffs) | {item.target for item in reached})


def _stem(path: str) -> str:
    return Path(path).stem


def _word_set(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _names_all(route: Route, words: set[str]) -> bool:
    return any(
        words <= _word_set(name) for name in [route.route, *map(_stem, route.entry)]
    )


def _fewest_entries(routes: list[Route]) -> Route | None:
    return min(routes, key=lambda item: len(item.entry), default=None)


def match_route(
    routes: list[Route], mode: str, qualifier: str | None = None
) -> Route | None:
    words = _word_set(qualifier or "")
    candidates = [route for route in routes if not words or _names_all(route, words)]
    if words and not candidates:
        return None
    stemmed = [
        route
        for route in candidates
        if any(_stem(file) == mode for file in route.entry)
    ]
    found = _fewest_entries(stemmed)
    if found:
        return found
    label = re.compile(rf"(?i)\b{re.escape(mode)}\b")
    found = next(
        (route for route in candidates if scan.matches(label, route.route)), None
    )
    return found or (_fewest_entries(candidates) if words else None)


def skip_targets(directory: SkillDir, source: str) -> list[str]:
    text = " ".join(directory.read(source).split("\n"))
    resolved = []
    for match in SKIP.finditer(text):
        _, stop = scan.bounds(text, match.start(), scan.END)
        rest = scan.slice_text(text, match.end(), stop)
        pointer = next(
            (item for item in scan.targets(rest, False) if not item.is_link), None
        )
        if pointer:
            rel, invalid = scan.resolve(directory, source, pointer.raw, False)
            if rel is not None and not invalid:
                resolved.append(rel)
    return resolved


def reach(loads: list[Edge], starts: list[str], always_only: bool = False) -> list[str]:
    reached: list[str] = []
    todo = deque(unique(starts))
    while todo:
        current = todo.popleft()
        if current in reached or current == "SKILL.md":
            continue
        todo.extend(
            edge.to
            for edge in loads
            if edge.from_ == current and not (always_only and edge.conditional)
        )
        reached.append(current)
    return reached


def _depths(loads: list[Edge], starts: list[str]) -> dict[str, int]:
    depth: dict[str, int] = {}
    todo = deque((start, 1) for start in unique(starts))
    while todo:
        current, hop = todo.popleft()
        if current == "SKILL.md" or depth.get(current, hop + 1) <= hop:
            continue
        todo.extend((edge.to, hop + 1) for edge in loads if edge.from_ == current)
        depth[current] = hop
    return depth


def route_complexity(
    edges: list[Edge],
    loads: list[Edge],
    starts: list[str],
    reached: list[str],
    references: set[str],
) -> tuple[int, int, int]:
    depth = _depths(loads, starts)
    caller_depth: dict[str, int] = {}
    for edge in loads:
        if edge.to in references and edge.from_ in reached:
            caller_depth[edge.to] = min(
                caller_depth.get(edge.to, depth.get(edge.from_, 0)),
                depth.get(edge.from_, 0),
            )
    conditional = [edge for edge in edges if edge.conditional and edge.from_ in reached]
    lookups = [edge for edge in conditional if edge.to in references]
    branches = [edge for edge in conditional if edge.to not in references]
    cognitive = sum(
        1 + caller_depth.get(edge.from_, depth.get(edge.from_, 0)) for edge in branches
    )
    return len(branches) + 1, cognitive, len(lookups)


def _edge_route(edge: Edge) -> str | None:
    return edge.route if isinstance(edge.route, str) and edge.route else None


class _RouteInputs:
    def __init__(
        self,
        directory: SkillDir,
        edges: list[Edge],
        sizes: OrderedMap[int],
        references: set[str],
    ):
        self.directory, self.edges, self.sizes, self.references = (
            directory,
            edges,
            sizes,
            references,
        )

    def cost(self, reached: list[str]) -> int:
        return (self.sizes.get("SKILL.md") or 0) + sum(
            (self.sizes.get(file) or 0) for file in reached if file.endswith(".md")
        )

    def route(self, name: str, own: list[Edge], everywhere: list[Edge]) -> Route:
        loads = [edge for edge in self.edges if edge.kind == EdgeKind.LOAD]
        entry = unique(edge.to for edge in own)
        dropped = {
            file
            for source in entry
            if source.endswith(".md")
            for file in skip_targets(self.directory, source)
        }
        route_loads = [
            edge
            for edge in loads
            if edge.from_ not in dropped and edge.to not in dropped
        ]
        candidates = [edge for edge in [*own, *everywhere] if edge.to not in dropped]
        starts = [edge.to for edge in candidates]
        min_starts = [
            edge.to for edge in candidates if edge.table or not edge.conditional
        ]
        minimum = reach(route_loads, min_starts, True)
        reached = reach(route_loads, starts)
        handoffs = sorted(
            {
                edge.to
                for edge in self.edges
                if edge.kind == EdgeKind.HANDOFF
                and edge.from_ in reached
                and edge.to not in reached
            }
        )
        cyclomatic, cognitive, lookups = route_complexity(
            self.edges, route_loads, starts, reached, self.references
        )
        return Route(
            name,
            entry,
            reached,
            minimum,
            self.cost(minimum),
            self.cost(reached),
            handoffs,
            cyclomatic,
            cognitive,
            lookups,
            0,
            0,
            [],
            [],
            [],
        )


def _mapped_files(skill: Path) -> list[str]:
    return sorted(
        path.relative_to(skill).as_posix()
        for folder in DIRS
        for path in (skill / folder).rglob("*")
        if path.is_file()
    )


def _route_sections(skill_md: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    for iter_line in skill_md.split("\n"):
        line = iter_line.strip()
        if line.startswith("|"):
            row = scan.short(line.strip("|").split("|", 1)[0])
            for match in scan.find_all(scan.SECTION, line):
                sections[scan.short(match[1])] = row
    return sections


class _Collector:
    def __init__(
        self,
        directory: SkillDir,
        sizes: OrderedMap[int],
        sections: dict[str, str],
        skill_names: set[str],
    ):
        self.directory, self.sizes, self.sections, self.skill_names = (
            directory,
            sizes,
            sections,
            skill_names,
        )
        self.edges: list[Edge] = []
        self.external: list[External] = []
        self.missing: list[MissingFinding] = []

    def source(self, source: str) -> None:
        for item in scan.scan(self.directory, source, self.skill_names):
            self.item(source, item)

    def item(self, source: str, item: Scanned) -> None:
        body = item.body
        context, table = body.context, body.table
        route = context if table else self.sections.get(item.section)
        edit_gate = source == "SKILL.md" and item.edits and not route
        if not isinstance(body, Pointer):
            from dataclasses import replace

            self.external.append(
                replace(
                    body,
                    from_=source,
                    conditional=body.conditional or edit_gate,
                    route=route if source == "SKILL.md" else body.route,
                )
            )
            return
        if not self.directory.actual_path(body.to).is_file():
            self.missing.append(MissingFinding(source, body.line, body.raw))
        elif self.sizes.contains_key(body.to):
            self.edges.append(
                Edge(
                    source,
                    body.to,
                    body.context,
                    body.conditional or edit_gate,
                    body.kind,
                    body.table,
                    body.line,
                    route if source == "SKILL.md" else ROUTE_ABSENT,
                )
            )


def analyze_skill(skill: Path) -> Analysis:
    skill = skill.resolve()
    _ANALYZED_PATHS[skill.name] = skill
    directory = SkillDir(skill)
    files = _mapped_files(skill)
    shared = directory.shared_files(files)
    listed = files + shared
    sizes = OrderedMap(
        tuple(
            (file, scan.tokens(directory.actual_path(file)))
            for file in ["SKILL.md", *listed]
        )
    )
    references = {
        file for file in listed if scan.is_reference(directory.actual_path(file))
    }
    try:
        siblings = {
            path.name for path in skill.parent.iterdir() if (path / "SKILL.md").exists()
        }
    except OSError:
        siblings = set()
    if not any(name != directory.name for name in siblings):
        siblings = set()
    collector = _Collector(
        directory, sizes, _route_sections(directory.read("SKILL.md")), siblings
    )
    collector.source("SKILL.md")
    for source in listed:
        if source.endswith(".md"):
            collector.source(source)
    edges, external = collector.edges, collector.external
    if not any(
        edge.kind == EdgeKind.LOAD and edge.from_ == "SKILL.md" and edge.table
        for edge in edges
    ):
        edges = [
            Edge(
                e.from_,
                e.to,
                e.context,
                e.conditional,
                e.kind,
                e.table,
                e.line,
                e.context,
            )
            if e.kind == EdgeKind.LOAD and e.from_ == "SKILL.md"
            else e
            for e in edges
        ]
        external = [
            External(
                x.from_,
                x.external,
                x.target,
                x.skill,
                x.mode,
                x.runs,
                x.context,
                x.conditional,
                x.kind,
                x.table,
                x.line,
                x.qualifier,
                x.context if x.from_ == "SKILL.md" else x.route,
                x.report_order,
            )
            for x in external
        ]
    routes = _build_routes(directory, edges, sizes, references)
    how_topics = _how_topics(skill)
    return Analysis(
        directory.name,
        sizes,
        sorted(references),
        edges,
        external,
        routes,
        structure(edges, routes),
        findings(files, edges, collector.missing),
        how_topics,
        sum(topic.tokens for topic in how_topics),
    )


def _how_topics(skill: Path) -> list[HowTopic]:
    """Topics under ``<pkg>/how/<skill>``, sized apart from route totals."""
    directory = skill.parent.parent / "how" / skill.name
    if not directory.is_dir():
        return []
    return [
        HowTopic(f"{skill.name}/{file.stem}", scan.tokens(file))
        for file in sorted(directory.glob("*.md"))
    ]


def _build_routes(
    directory: SkillDir, edges: list[Edge], sizes: OrderedMap[int], references: set[str]
) -> list[Route]:
    top = [e for e in edges if e.kind == EdgeKind.LOAD and e.from_ == "SKILL.md"]
    everywhere = [e for e in top if _edge_route(e) is None]
    groups: list[tuple[str, list[Edge]]] = []
    for edge in top:
        name = _edge_route(edge)
        if name is None:
            continue
        group = next((group for group in groups if group[0] == name), None)
        if group:
            group[1].append(edge)
        else:
            groups.append((name, [edge]))
    inputs = _RouteInputs(directory, edges, sizes, references)
    return [inputs.route(name, own, everywhere) for name, own in groups]


def _places(edges: list[Edge]):
    places: dict[str, dict[str, list[Edge]]] = {}
    for edge in edges:
        if edge.kind in {EdgeKind.MENTION, EdgeKind.ROLE}:
            continue
        place = f"SKILL.md: {edge.context}" if edge.from_ == "SKILL.md" else edge.from_
        places.setdefault(edge.to, {}).setdefault(place, []).append(edge)
    return places


def findings(
    files: list[str], edges: list[Edge], missing: list[MissingFinding]
) -> Findings:
    places = _places(edges)
    called = {edge.to for edge in edges}
    out = Findings([], [], [], [], missing, [], [], [])
    for file in files:
        callers = places.get(file)
        if file not in called:
            out.unreferenced.append(file)
            continue
        if not file.startswith("references/") or callers is None:
            continue
        if len(callers) > 1:
            out.shared.append(SharedFinding(file, sorted(callers)))
        elif callers:
            place, hits = next(iter(callers.items()))
            found = CallerFinding(file, place)
            always = not place.startswith("SKILL.md") and any(
                e.kind == EdgeKind.LOAD and not e.conditional for e in hits
            )
            (out.chain if always else out.single_caller).append(found)
    shape = structure(edges, [])
    cycles = [CycleFinding(pair) for pair in shape.mutual_pairs]
    fan_out = [
        FanOutFinding(file, count)
        for file, count in shape.links_out.iter()
        if count >= FAN_OUT
    ]
    density = []
    if shape.average_links > DENSITY:
        density.append(DensityFinding(shape.average_links))
    return Findings(
        out.chain,
        out.single_caller,
        out.shared,
        out.unreferenced,
        out.missing,
        cycles,
        fan_out,
        density,
    )


def structure(edges: list[Edge], routes: list[Route]) -> Structure:
    links = sorted(
        {
            (e.from_, e.to)
            for e in edges
            if e.kind in {EdgeKind.LOAD, EdgeKind.HANDOFF} and e.from_ != "SKILL.md"
        }
    )
    counts: dict[str, int] = {}
    for source, _ in links:
        counts[source] = counts.get(source, 0) + 1
    links_out = sorted(counts.items())
    pairs = [[a, b] for a, b in links if a < b and (b, a) in links]
    top = max(links_out, key=lambda item: (item[1], item[0]), default=None)
    average = round(len(links) / len(links_out), 2) if links_out else 0
    widest = max(routes, key=lambda route: len(route.files), default=None)
    return Structure(
        len(pairs),
        pairs,
        top[1] if top else 0,
        top[0] if top else None,
        average,
        len(links_out),
        len(links),
        OrderedMap(tuple(links_out)),
        sum(module_of(a) != module_of(b) for a, b in links),
        len(edges),
        max((r.cyclomatic for r in routes), default=None),
        max((r.cognitive for r in routes), default=None),
        len(widest.files) if widest else None,
        widest.route if widest else None,
    )


@dataclass
class StructureRow:
    measure: str
    value: str
    target: str
    status: str


def _row(measure: str, value: str, target: str, status: str) -> StructureRow:
    return StructureRow(measure, value, target, status)


def _warning(condition: bool) -> str:
    return "warning" if condition else "ok"


def _py_float(value: float) -> str:
    return "0" if value == 0 else str(float(value))


DIAGRAM_EDGES_MEASURE = "Diagram edges"


def structure_rows(shape: Structure) -> list[StructureRow]:
    top_file = f" ({shape.max_links_out_file})" if shape.max_links_out_file else ""
    plural = "" if shape.linking_files == 1 else "s"
    rows = [
        _row(
            "Mutual links",
            str(shape.mutual_links),
            "0",
            "defect" if shape.mutual_links else "ok",
        ),
        _row(
            "Max links out of one file",
            f"{shape.max_links_out}{top_file}",
            f"< {FAN_OUT}",
            _warning(shape.max_links_out >= FAN_OUT),
        ),
        _row(
            "Average links per linking file",
            f"{_py_float(shape.average_links)} ({shape.links} links, "
            f"{shape.linking_files} file{plural})",
            f"<= {DENSITY}",
            _warning(shape.average_links > DENSITY),
        ),
        _row("Cross-module edges", str(shape.cross_module_edges), "-", "-"),
        _row(
            DIAGRAM_EDGES_MEASURE,
            str(shape.diagram_edges),
            f"<= {DIAGRAM_EDGES_WARN}",
            _warning(shape.diagram_edges > DIAGRAM_EDGES_WARN),
        ),
    ]
    if shape.max_route_cyclomatic is not None:
        rows.append(
            _row(
                "Max route cyclomatic",
                str(shape.max_route_cyclomatic),
                f"<= {CYCLOMATIC_WARN}",
                _warning(shape.max_route_cyclomatic > CYCLOMATIC_WARN),
            )
        )
    if shape.max_route_cognitive is not None:
        status = (
            "defect"
            if shape.max_route_cognitive > COGNITIVE_ERROR
            else _warning(shape.max_route_cognitive > COGNITIVE_WARN)
        )
        rows.append(
            _row(
                "Max route cognitive",
                str(shape.max_route_cognitive),
                f"<= {COGNITIVE_WARN} warn, <= {COGNITIVE_ERROR} error",
                status,
            )
        )
    if shape.max_route_files is not None and shape.max_route_files_route is not None:
        rows.append(
            _row(
                "Most files reached by one route",
                f"{shape.max_route_files} ({shape.max_route_files_route})",
                f"<= {ROUTE_FILES_WARN}",
                _warning(shape.max_route_files > ROUTE_FILES_WARN),
            )
        )
    return rows


def dispatch_cost(dispatch: Dispatch) -> str:
    low = dispatch.min_tokens
    if low is None:
        return "unresolved"
    high = dispatch.max_tokens if dispatch.max_tokens is not None else low
    return f"~{low}" if low == high else f"~{low}-{high}"


def resolve_local_main_costs(data: Analysis) -> Analysis:
    """Resolve sibling calls and agent costs for an analyzed skill."""
    from .resolve import resolve_local_main_costs as resolve

    return resolve(data, _ANALYZED_PATHS.get(data.skill))
