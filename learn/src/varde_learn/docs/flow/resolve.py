"""Resolve sibling skill calls and agent dispatch costs for flow routes."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from varde_core.layout import agent_dirs, skill_dirs

from varde_learn.docs.flow import (
    Dispatch,
    DispatchFile,
    EdgeKind,
    ExternalType,
    Runs,
    analyze,
)
from varde_learn.docs.flow.model import Analysis, External, Route

FileSet = set[tuple[str, str]]


class Journey:
    def __init__(self) -> None:
        self.files: FileSet = set()
        self.inline: list[tuple[str, str]] = []
        self.dispatches: list[tuple[str, External]] = []
        self.unresolved: list[str] = []


class Resolver:
    def __init__(self, parent: Path):
        self.parent = parent
        self.root = next(
            (
                candidate
                for candidate in (parent, *parent.parents)
                if (candidate / ".git").exists()
            ),
            parent.parent,
        )
        self.skill_paths = skill_dirs(self.root)
        self.agent_paths = agent_dirs(self.root)
        self.skills: dict[str, Analysis | None] = {}
        self.definitions: dict[str, int] = {}

    def skill(self, name: str) -> Analysis | None:
        if name not in self.skills:
            sibling = self.parent / name
            path = (
                sibling
                if (sibling / "SKILL.md").is_file()
                else self.skill_paths.get(name, sibling)
            )
            self.skills[name] = (
                analyze.analyze_skill(path) if (path / "SKILL.md").is_file() else None
            )
        return self.skills[name]

    def file_tokens(self, skill: str, file: str) -> int:
        if skill == "agents":
            return self.definitions.get(file, 0)
        data = self.skills.get(skill)
        if data is None or not file.endswith(".md"):
            return 0
        return data.tokens.get(file) or 0

    def tokens(self, files: FileSet) -> int:
        return sum(self.file_tokens(skill, file) for skill, file in files)

    def skill_load_via(self, skill: str, files: FileSet) -> str | None:
        possible = []
        for parent_skill, parent_file in files:
            data = self.skills.get(parent_skill)
            if data and any(
                call.external == ExternalType.SKILL
                and call.kind == EdgeKind.LOAD
                and call.skill == skill
                and call.from_ == parent_file
                for call in data.external
            ):
                possible.append(f"skills/{parent_skill}/{parent_file}")
        return min(possible, default=None)

    def dispatch_file_via(
        self,
        skill: str,
        file: str,
        files: FileSet,
        agent: str,
        source: str,
        source_file: str,
    ) -> str:
        dispatched_from = f"skills/{source}/{source_file}"
        if skill == "agents":
            return dispatched_from
        definition = self.agent_definition_label(agent)
        if file == "SKILL.md" and ("agents", agent) in files:
            return definition
        if file == "SKILL.md":
            via = self.skill_load_via(skill, files)
            if via:
                return via
        data = self.skills.get(skill)
        if data:
            linked = [
                f"skills/{skill}/{edge.from_}"
                for edge in data.edges
                if edge.kind == EdgeKind.LOAD
                and edge.to == file
                and (edge.from_ == "SKILL.md" or (skill, edge.from_) in files)
            ]
            if linked:
                return min(linked)
        return dispatched_from

    def agent_definition_label(self, agent: str) -> str:
        path = self.agent_paths[analyze.agent_dir(agent)] / "claude.md"
        return path.relative_to(self.root).as_posix()

    def dispatch_files(
        self, files: FileSet | None, agent: str, source: str, source_file: str
    ) -> list[DispatchFile]:
        if files is None:
            return []
        out = [
            DispatchFile(
                self.agent_definition_label(file)
                if skill == "agents"
                else f"skills/{skill}/{file}",
                self.file_tokens(skill, file),
                self.dispatch_file_via(skill, file, files, agent, source, source_file),
            )
            for skill, file in files
        ]
        return sorted(out, key=lambda item: item.file)

    def calls(self, name: str, route: Route, which: str) -> list[External]:
        data = self.skill(name)
        if data is None:
            return []
        files = set(route.min_files if which == "min" else route.files)
        return [
            call
            for call in data.external
            if not call.is_handoff()
            and (which == "max" or not call.conditional)
            and (call.serves_route(route.route) or call.from_ in files)
        ]

    def journey(
        self, name: str, route: Route, which: str, seen: set[tuple[str, str]]
    ) -> Journey:
        seen = seen | {(name, route.route)}
        journey = Journey()
        journey.files.add((name, "SKILL.md"))
        journey.files.update(
            (name, file)
            for file in (route.min_files if which == "min" else route.files)
        )
        for call in self.calls(name, route, which):
            if call.external == ExternalType.AGENT:
                journey.dispatches.append((name, call))
            elif call.kind == EdgeKind.LOAD:
                self.follow_inline(call, which, seen, journey)
        return journey

    def follow_inline(
        self, call: External, which: str, seen: set[tuple[str, str]], journey: Journey
    ) -> None:
        data = self.skill(call.skill)
        target = (
            analyze.match_route(data.routes, call.mode, call.qualifier)
            if data
            else None
        )
        if target is None:
            journey.unresolved.append(call.target)
            return
        if (call.skill, target.route) in seen:
            return
        journey.inline.append((call.target, f"{call.skill}: {target.route}"))
        more = self.journey(call.skill, target, which, seen)
        journey.files.update(more.files)
        journey.inline.extend(more.inline)
        journey.dispatches.extend(more.dispatches)
        journey.unresolved.extend(more.unresolved)

    def agent_preloads(self, call: External) -> FileSet:
        files: FileSet = set()
        folder = analyze.agent_dir(call.target)
        agent_path = self.agent_paths.get(folder)
        if agent_path is None:
            return files
        definition = agent_path / "claude.md"
        if not definition.is_file():
            return files
        self.definitions[call.target] = analyze.scan.tokens(definition)
        files.add(("agents", call.target))
        for name in analyze.preloaded_skills(analyze.scan.read_text(definition)):
            if self.skill(name) is not None:
                files.add((name, "SKILL.md"))
        return files

    def run_mode(
        self, skill: str, mode: str, which: str, files: FileSet
    ) -> tuple[str, FileSet | None]:
        data = self.skill(skill)
        target = analyze.match_route(data.routes, mode) if data else None
        if target is None:
            return f"{skill} {mode}", None
        files.update(self.journey(skill, target, which, set()).files)
        return f"{skill}: {target.route}", files

    def agent(
        self, name: str, call: External, which: str
    ) -> tuple[str, FileSet | None]:
        files = self.agent_preloads(call)
        data = self.skill(name)
        if data is None:
            return "", files
        loads = [edge for edge in data.edges if edge.kind == EdgeKind.LOAD]
        always_only = which == "min"
        if isinstance(call.runs, Runs) and call.runs.file is not None:
            files.update(
                (name, file)
                for file in analyze.reach(loads, [call.runs.file], always_only)
            )
            return call.runs.file, files
        if isinstance(call.runs, Runs) and call.runs.skill is not None:
            return self.run_mode(call.runs.skill, call.runs.mode or "", which, files)
        if call.runs is None and call.target == "builder":
            skill, mode = analyze.BUILDER
            return self.run_mode(skill, mode, which, files)
        gate = [file for file in analyze.GATE if data.tokens.contains_key(file)]
        reached = gate + analyze.reach(loads, gate[:1], always_only)
        files.update((name, file) for file in reached)
        return "review gate", files

    def dispatches(self, name: str, low: Journey, high: Journey) -> list[Dispatch]:
        always = {(source, call.from_, call.line) for source, call in low.dispatches}
        out: list[Dispatch] = []
        for source, call in high.dispatches:
            runs, low_files = self.agent(source, call, "min")
            _, high_files = self.agent(source, call, "max")
            min_tokens = self.tokens(low_files) if low_files is not None else None
            max_tokens = self.tokens(high_files) if high_files is not None else None
            files = self.dispatch_files(high_files, call.target, source, call.from_)
            item = next(
                (
                    item
                    for item in out
                    if item.agent == call.target and item.runs == runs
                ),
                None,
            )
            if item is None:
                item = Dispatch(call.target, runs, [], True, min_tokens, max_tokens, [])
                out.append(item)
            place = f"{call.from_}:{call.line}"
            if source != name:
                place = f"{source}/{place}"
            if place not in item.from_:
                item.from_.append(place)
            if (source, call.from_, call.line) in always:
                item_index = out.index(item)
                item = replace(item, conditional=False)
                out[item_index] = item
            for file in files:
                existing = next(
                    (value for value in item.files if value.file == file.file), None
                )
                if existing is None:
                    item.files.append(file)
                elif file.via < existing.via:
                    item.files[item.files.index(existing)] = replace(
                        existing, via=file.via
                    )
            item.files.sort(key=lambda value: value.file)
        return out

    def resolve(self, name: str) -> Analysis:
        data = self.skill(name)
        if data is None:
            raise ValueError(f"unknown skill: {name}")
        routes = []
        for route in data.routes:
            low = self.journey(name, route, "min", set())
            high = self.journey(name, route, "max", set())
            routes.append(
                replace(
                    route,
                    main_min_tokens=self.tokens(low.files),
                    main_max_tokens=self.tokens(high.files),
                    inline=analyze.dedupe_inline(high.inline),
                    unresolved=analyze.sorted_unique(high.unresolved),
                    handoffs=analyze.merged_handoffs(route, data.external),
                    dispatches=self.dispatches(name, low, high),
                )
            )
        return replace(data, routes=routes)


def resolve_local_main_costs(
    data: Analysis, skill_path: Path | None = None
) -> Analysis:
    """Resolve sibling calls and agent costs for an already scanned skill."""
    path = skill_path.resolve() if skill_path else None
    if path is None or not path.is_dir():
        routes = [
            replace(
                route,
                main_min_tokens=route.min_tokens,
                main_max_tokens=route.max_tokens,
            )
            for route in data.routes
        ]
        return replace(data, routes=routes)
    resolver = Resolver(path.parent)
    resolver.skills[data.skill] = data
    return resolver.resolve(data.skill)
