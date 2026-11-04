"""Text, Mermaid, and FLOW.md renderings for flow analysis."""

from __future__ import annotations

from varde_learn.docs.flow import DENSITY, FAN_OUT, Analysis, EdgeKind, ExternalType
from varde_learn.docs.flow.analyze import (
    DIAGRAM_EDGES_MEASURE,
    dispatch_cost,
    structure_rows,
)

STRUCTURE = ("cycle:", "fan-out:", "density:")


def _tokens(data: Analysis, name: str) -> int:
    return data.tokens.get(name) or 0


def _sized(data: Analysis, name: str, text: str, unit: str) -> str:
    return f"{text} (~{_tokens(data, name)}{unit})" if name.endswith(".md") else text


def _escape(text: str) -> str:
    return text.replace('"', "#quot;").replace("<", "#lt;").replace(">", "#gt;")


def _py_float(value: float) -> str:
    return f"{value:.1f}" if value.is_integer() else str(value)


def _findings(data: Analysis) -> list[str]:
    f = data.findings
    lines = [f"chain: {x.file} <- {x.caller}" for x in f.chain]
    lines += [f"single caller: {x.file} <- {x.caller}" for x in f.single_caller]
    lines += [f"shared: {x.file} <- {'; '.join(x.callers)}" for x in f.shared]
    lines += [f"unreferenced: {x}" for x in f.unreferenced]
    lines += [f"missing: {x.from_}:{x.line} -> {x.target}" for x in f.missing]
    lines += [f"cycle: {' <-> '.join(x.files)}" for x in f.cycle]
    lines += [
        f"fan-out: {x.file} ({x.links} links out, target < {FAN_OUT})"
        for x in f.fan_out
    ]
    lines += [
        f"density: average {_py_float(x.average)} links per linking file "
        f"(target <= {DENSITY})"
        for x in f.density
    ]
    return lines


def text_report(data: Analysis) -> str:
    out = [f"== {data.skill} (SKILL.md ~{_tokens(data, 'SKILL.md')} tokens)", "Routes:"]
    for route in data.routes:
        out.append(
            f"  {route.route}  [~{route.min_tokens}-{route.max_tokens} tokens with "
            f"SKILL.md; main agent ~{route.main_min_tokens}-{route.main_max_tokens}]"
        )
        out.extend(f"    {_sized(data, f, f, '')}" for f in route.files)
        out.extend(f"    handoff: {f}" for f in route.handoffs)
        out.extend(f"    inline: {x.target} -> {x.resolved}" for x in route.inline)
        out.extend(f"    unresolved: {x}" for x in route.unresolved)
        for d in route.dispatches:
            conditional = " (conditional)" if d.conditional else ""
            out.append(
                f"    dispatch {d.agent}{conditional}: {d.runs}, "
                f"{dispatch_cost(d)} per dispatch, from {', '.join(d.from_)}"
            )
    if not data.routes:
        out.append("  (none)")
    out.append("Structure:")
    out.extend(
        f"  {r.measure}: {r.value} (target {r.target}) {r.status}"
        for r in structure_rows(data.structure)
    )
    out.append("Findings:")
    out.extend(f"  {line}" for line in _findings(data))
    if data.how_topics:
        out.append(f"How topics (not in route totals): ~{data.how_total_tokens} tokens")
        out.extend(f"  {t.id} ~{t.tokens} tokens" for t in data.how_topics)
    return "\n".join(out)


def mermaid(data: Analysis) -> str:
    ids: dict[str, str] = {}

    def node(name: str) -> str:
        if name not in ids:
            ids[name] = f"n{len(ids)}"
        return ids[name]

    skill_id = node("SKILL.md")
    out = [
        f"%% {data.skill}",
        "flowchart TD",
        f'  {skill_id}["SKILL.md (~{_tokens(data, "SKILL.md")} tok)"]',
    ]
    for name, _ in data.tokens.iter():
        if name != "SKILL.md":
            out.append(f'  {node(name)}["{_sized(data, name, _escape(name), " tok")}"]')
    for route in data.routes:
        rid = node(f"route: {route.route}")
        out.extend([f'  {rid}(["{_escape(route.route)}"])', f"  {skill_id} --> {rid}"])
    seen_targets: set[str] = set()
    seen_edges: set[tuple[str, str, str]] = set()
    pointers = [
        (e.from_, e.to, None, e.context, e.conditional, e.kind, e.route)
        for e in data.edges
    ]
    pointers += [
        (
            x.from_,
            None,
            x,
            x.context,
            x.conditional,
            x.kind if x.external == ExternalType.SKILL else None,
            x.route,
        )
        for x in data.external
    ]
    for source_name, to, external, context, conditional, kind, iter_route in pointers:
        if kind in {EdgeKind.MENTION, EdgeKind.ROLE}:
            continue
        route = iter_route if isinstance(iter_route, str) and iter_route else None
        source = node(f"route: {route}") if route else node(source_name)
        if external:
            label = (
                external.target
                if external.external == ExternalType.SKILL
                else f"agent: {external.target}"
            )
            target = node(f"external: {label}")
            if target not in seen_targets:
                out.append(f'  {target}[["{_escape(label)}"]]')
                seen_targets.add(target)
        else:
            target = node(to or "")
        key = source, target, context
        if key in seen_edges:
            continue
        seen_edges.add(key)
        if route and not external:
            out.append(f"  {source} --> {target}")
        else:
            arrow = (
                "==>" if kind == EdgeKind.HANDOFF else "-.->" if conditional else "-->"
            )
            out.append(f'  {source} {arrow}|"{_escape(context)}"| {target}')
    return "\n".join(out)


def _files_tree(data: Analysis) -> list[str]:
    refs = sorted(
        name
        for name, _ in data.tokens.iter()
        if name.startswith("references/") and name.endswith(".md")
    )
    children: dict[str, list[str]] = {"SKILL.md": []}
    stems = {name: name.rsplit("/", 1)[-1][:-3] for name in refs}
    for name in refs:
        stem = stems[name]
        parents = [
            candidate for candidate in refs if stem.startswith(stems[candidate] + "-")
        ]
        parent = max(
            parents, key=lambda candidate: len(stems[candidate]), default="SKILL.md"
        )
        children.setdefault(parent, []).append(name)
        children.setdefault(name, [])
    lines: list[str] = []

    def render(name: str, depth: int):
        routes = [r.route for r in data.routes if name == "SKILL.md" or name in r.files]
        lines.append(
            f"{'  ' * depth}- {name} (~{_tokens(data, name)} tok; routes: "
            f"{', '.join(routes) if routes else '-'})"
        )
        for child in sorted(children.get(name, [])):
            render(child, depth + 1)

    render("SKILL.md", 0)
    return lines


def _how_section(data: Analysis) -> list[str]:
    """On-request how topics: a route that loads one adds its tokens."""
    if not data.how_topics:
        return []
    return [
        "",
        "## How topics",
        "",
        "Loaded on request with `varde learn how`; a route adds its tokens when it needs one.",  # noqa: E501
        "",
        "| Topic | Tokens |",
        "|---|---|",
        *(f"| {topic.id} | ~{topic.tokens} |" for topic in data.how_topics),
    ]


def flow_doc(data: Analysis) -> str:
    out = [
        f"# {data.skill} flow",
        "",
        "Generated for human readers; agents do not load this file. Regenerate",
        "with `varde learn check --write`; draw the graph with",
        "`varde learn measure <skill> flow --mermaid` (thick arrow: handoff; dotted: conditional;",  # noqa: E501
        "double border: external skill or agent). Min and max count",
        "this skill; main adds modes the main agent runs inline, each file once.",
        "Subagents are per dispatch (multiply by the dispatch count); * marks a",
        "conditional dispatch.",
        "",
        "## Files",
        "",
        *_files_tree(data),
    ]
    out.extend(
        [
            "",
            "## Routes",
            "",
            (
                "| Route | Min tokens | Max tokens | Main min | Main max | "
                "Subagents per dispatch | Lookups | Files |"
            ),
            "|---|---|---|---|---|---|---|---|",
        ]
    )
    for r in data.routes:
        agents = (
            ", ".join(
                f"{d.agent}{'*' if d.conditional else ''} {dispatch_cost(d)}"
                for d in r.dispatches
            )
            or "-"
        )
        route_name = r.route.replace("|", "\\|")
        files = ", ".join(r.files) or "-"
        out.append(
            f"| {route_name} | ~{r.min_tokens} | ~{r.max_tokens} | "
            f"~{r.main_min_tokens} | ~{r.main_max_tokens} | {agents} | "
            f"{r.lookups} | {files} |"
        )
    out.extend(_how_section(data))
    findings = _findings(data)
    shape = [line for line in findings if line.startswith(STRUCTURE)]
    other = [line for line in findings if not line.startswith(STRUCTURE)]
    out.extend(
        [
            "",
            "## Structure",
            "",
            "| Measure | Value | Target | Status |",
            "|---|---|---|---|",
        ]
    )
    out.extend(
        f"| {r.measure} | {r.value} | {r.target} | {r.status} |"
        for r in structure_rows(data.structure)
        if r.measure != DIAGRAM_EDGES_MEASURE
    )
    if shape:
        out.extend(["", *(f"- {line}" for line in shape)])
    out.extend(
        ["", "## Findings", "", *(f"- {line}" for line in other)]
        if other
        else ["", "## Findings", "", "None."]
    )
    return "\n".join(out) + "\n"
