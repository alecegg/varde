"""Python ports of the inline tests in Rust flow/analyze.rs."""

import json
from pathlib import Path

from varde_learn.docs.flow.analyze import (
    analyze_skill,
    dispatch_cost,
    match_route,
    module_of,
    resolve_local_main_costs,
    structure_rows,
)
from varde_learn.docs.flow.model import (
    CycleFinding,
    Dispatch,
    EdgeKind,
    MissingFinding,
    Route,
    SharedFinding,
)

SKILL_MD = (
    "# Demo\n\n| Request | Read |\n|---|---|\n"
    "| Build it | `references/build.md` |\n| Check it | `references/check.md` |\n\n"
    "Before edits, read `references/gate.md`.\n"
)
BUILD_MD = "Then see `references/shared.md`.\n"
CHECK_MD = "Run `references/shared.md` when needed.\nSee `references/ghost.md`.\n"


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def tok(text: str) -> int:
    return (len(text) + 3) // 4


def demo(tmp_path: Path):
    skill = tmp_path / "demo"
    write(skill, "SKILL.md", SKILL_MD)
    write(skill, "references/build.md", BUILD_MD)
    write(skill, "references/check.md", CHECK_MD)
    write(skill, "references/gate.md", "gate\n")
    write(skill, "references/shared.md", "<!-- kind: reference -->\nshared\n")
    write(skill, "references/lonely.md", "alone\n")
    write(skill, "scripts/tool.sh", "echo\n")
    return analyze_skill(skill)


def test_sizes_are_a_quarter_of_the_characters_rounded_up(tmp_path: Path):
    a = demo(tmp_path)
    assert a.tokens.get("references/gate.md") == 2
    assert a.tokens.get("SKILL.md") == tok(SKILL_MD)
    keys = [key for key, _ in a.tokens.iter()]
    assert keys == [
        "SKILL.md",
        "references/build.md",
        "references/check.md",
        "references/gate.md",
        "references/lonely.md",
        "references/shared.md",
        "scripts/tool.sh",
    ]
    assert a.references == ["references/shared.md"]


def test_routes_reach_files_along_load_edges_with_min_and_max(tmp_path: Path):
    a = demo(tmp_path)
    assert [route.route for route in a.routes] == ["Build it", "Check it"]
    build, check = a.routes
    assert build.entry == ["references/build.md"]
    assert build.min_files == ["references/build.md", "references/shared.md"]
    assert build.files == [
        "references/build.md",
        "references/gate.md",
        "references/shared.md",
    ]
    small = tok(SKILL_MD) + tok(BUILD_MD) + tok("<!-- kind: reference -->\nshared\n")
    assert (build.min_tokens, build.max_tokens) == (small, small + tok("gate\n"))
    assert check.min_files == ["references/check.md"]
    assert len(check.files) == 3


def test_an_edit_gate_outside_a_table_counts_in_max_not_min(tmp_path: Path):
    a = demo(tmp_path)
    gate = next(edge for edge in a.edges if edge.to == "references/gate.md")
    assert gate.conditional
    assert gate.route is None
    assert "references/gate.md" not in a.routes[0].min_files


def test_findings_cover_unreferenced_missing_shared_and_single_caller(tmp_path: Path):
    f = demo(tmp_path).findings
    assert f.unreferenced == ["references/lonely.md", "scripts/tool.sh"]
    assert f.missing == [
        MissingFinding("references/check.md", 2, "references/ghost.md")
    ]
    assert f.shared == [
        SharedFinding(
            "references/shared.md", ["references/build.md", "references/check.md"]
        )
    ]
    assert [(c.file, c.caller) for c in f.single_caller] == [
        ("references/build.md", "SKILL.md: Build it"),
        ("references/check.md", "SKILL.md: Check it"),
        ("references/gate.md", "SKILL.md: Demo"),
    ]
    assert not f.chain and not f.cycle


def test_structure_counts_links_between_files_without_skill_md(tmp_path: Path):
    a = demo(tmp_path)
    s = a.structure
    assert (s.links, s.linking_files, s.mutual_links) == (2, 2, 0)
    assert (s.average_links, s.max_links_out, s.max_links_out_file) == (
        1.0,
        1,
        "references/check.md",
    )
    assert s.diagram_edges == len(a.edges)
    assert (s.max_route_files, s.max_route_files_route) == (3, "Build it")


def test_complexity_counts_conditional_edges_that_are_not_lookups(tmp_path: Path):
    a = demo(tmp_path)
    assert (a.routes[0].cyclomatic, a.routes[0].cognitive) == (1, 0)
    assert (a.routes[1].cyclomatic, a.routes[1].lookups) == (1, 1)
    skill = tmp_path / "other"
    write(skill, "SKILL.md", "| R | A |\n|---|---|\n| Go | `references/a.md` |\n")
    write(skill, "references/a.md", "Read `references/b.md` when stale.\n")
    write(skill, "references/b.md", "b\n")
    route = analyze_skill(skill).routes[0]
    assert (route.cyclomatic, route.cognitive, route.lookups) == (2, 2, 0)


def test_an_unconditional_reference_that_loads_another_is_a_chain_and_mutual_links(
    tmp_path: Path,
):
    skill = tmp_path / "demo"
    write(skill, "SKILL.md", "| R | A |\n|---|---|\n| Go | `references/a.md` |\n")
    write(skill, "references/a.md", "Read `references/b.md`.\n")
    write(skill, "references/b.md", "See `references/a.md`.\n")
    a = analyze_skill(skill)
    assert [(c.file, c.caller) for c in a.findings.chain] == [
        ("references/b.md", "references/a.md")
    ]
    assert a.findings.cycle == [CycleFinding(["references/a.md", "references/b.md"])]
    assert a.structure.mutual_links == 1


def test_a_skill_without_a_routing_table_makes_each_label_a_route(tmp_path: Path):
    skill = tmp_path / "demo"
    write(
        skill,
        "SKILL.md",
        "## First\n\nRead `references/a.md`.\n\n## Second\n\nRead `references/b.md`.\n",
    )
    write(skill, "references/a.md", "a\n")
    write(skill, "references/b.md", "b\n")
    assert [r.route for r in analyze_skill(skill).routes] == ["First", "Second"]


def test_a_shared_file_listed_for_the_skill_is_mapped(tmp_path: Path):
    skill = tmp_path / "skills/demo"
    write(skill, "SKILL.md", "| R | A |\n|---|---|\n| Go | `references/s.md` |\n")
    write(tmp_path, "skills/shared/references/s.md", "shared body\n")
    write(tmp_path, "skills/shared/MANIFEST", "references/s.md demo other\n")
    a = analyze_skill(skill)
    assert a.tokens.get("references/s.md") == tok("shared body\n")
    assert a.routes[0].files == ["references/s.md"]


def test_shared_manifest_in_another_module_resolves_for_legacy_skill(tmp_path: Path):
    skill = tmp_path / "skills" / "varde-demo"
    shared = (
        tmp_path / "python" / "varde-core" / "src" / "varde_core" / "skills" / "shared"
    )
    write(skill, "SKILL.md", "| R | A |\n|---|---|\n| Go | `references/s.md` |\n")
    write(shared, "references/s.md", "shared body\n")
    write(shared, "MANIFEST", "references/s.md varde-demo\n")
    (tmp_path / ".git").touch()

    analysis = analyze_skill(skill)

    assert analysis.tokens.get("references/s.md") == tok("shared body\n")
    assert analysis.findings.missing == []


def test_a_skip_sentence_drops_the_named_file_from_a_route(tmp_path: Path):
    skill = tmp_path / "demo"
    write(skill, "SKILL.md", "| R | A |\n|---|---|\n| Go | `references/a.md` |\n")
    write(skill, "references/a.md", "Read `references/b.md`. Skip `references/c.md`.\n")
    write(skill, "references/b.md", "Read `references/c.md`.\n")
    write(skill, "references/c.md", "c\n")
    assert analyze_skill(skill).routes[0].files == [
        "references/a.md",
        "references/b.md",
    ]


def route(name: str, entry: list[str]) -> Route:
    return Route(name, entry, [], [], 0, 0, [], 1, 0, 0, 0, 0, [], [], [])


def test_match_route_prefers_qualified_then_stem_then_label():
    routes = [
        route("Plan work", ["references/plan.md", "references/more.md"]),
        route("Build with builder", ["references/build.md"]),
        route("Build now", ["references/build-now.md"]),
    ]

    def pick(mode: str, qualifier: str | None = None) -> str | None:
        matched = match_route(routes, mode, qualifier)
        return matched.route if matched is not None else None

    assert pick("build") == "Build with builder"
    assert pick("work") == "Plan work"
    assert pick("nothing") is None
    assert pick("build", "builder") == "Build with builder"
    assert pick("build", "absent") is None
    assert pick("zzz", "now") == "Build now"


def test_resolver_follows_sibling_mode_and_records_unresolved_calls(tmp_path: Path):
    skills = tmp_path / "skills"
    write(
        skills / "varde-a",
        "SKILL.md",
        "| Request | Read |\n|---|---|\n| Do a | `references/a.md` |\n",
    )
    write(
        skills / "varde-a",
        "references/a.md",
        "Then run `varde-b build` and `varde-b unknown`.\n",
    )
    write(
        skills / "varde-b",
        "SKILL.md",
        "| Request | Read |\n|---|---|\n| Build thing | `references/build.md` |\n",
    )
    write(skills / "varde-b", "references/build.md", "build steps\n")

    route = resolve_local_main_costs(analyze_skill(skills / "varde-a")).routes[0]

    assert [(call.target, call.resolved) for call in route.inline] == [
        ("varde-b build", "varde-b: Build thing"),
    ]
    assert route.unresolved == ["varde-b unknown"]
    assert route.main_min_tokens > route.min_tokens


def test_resolver_prefers_sibling_skill_over_repo_skill_with_same_name(
    tmp_path: Path, monkeypatch
):
    from varde_learn.docs.flow import resolve

    local = tmp_path / "project" / "python" / "skills" / "varde-same"
    repository = tmp_path / "repository" / "skills" / "varde-same"
    write(local, "SKILL.md", "# Local skill\n")
    write(repository, "SKILL.md", "# Repository skill with much more text\n")
    resolver = resolve.Resolver(local.parent)
    monkeypatch.setattr(resolve, "skill_dirs", lambda root: {"varde-same": repository})

    result = resolver.skill("varde-same")

    assert result is not None
    assert result.tokens.get("SKILL.md") == 4


def test_flow_json_lists_every_analysis_section(tmp_path: Path, capsys):
    from varde_learn.docs.cli import run

    skill = tmp_path / "demo"
    write(
        skill,
        "SKILL.md",
        "| Request | Read |\n|---|---|\n| Build it | `references/build.md` |\n",
    )
    write(skill, "references/build.md", "Build steps.\n")

    assert run(["flow", "--json", str(skill)]) == 0
    data = json.loads(capsys.readouterr().out)["data"][0]
    assert sorted(data) == [
        "edges",
        "external",
        "findings",
        "how_topics",
        "how_total_tokens",
        "references",
        "routes",
        "skill",
        "structure",
        "tokens",
    ]
    assert data["skill"] == "demo"
    assert data["edges"][0]["kind"] == "load"
    assert data["edges"][0]["route"] == "Build it"


def test_analysis_edge_and_structure_values(tmp_path: Path):
    a = demo(tmp_path)
    assert a.structure.average_links == 1.0
    assert a.findings.single_caller and not a.findings.fan_out
    edge = a.edges[0]
    assert (
        edge.from_,
        edge.to,
        edge.context,
        edge.conditional,
        edge.kind,
        edge.table,
        edge.line,
        edge.route,
    ) == (
        "SKILL.md",
        "references/build.md",
        "Build it",
        False,
        EdgeKind.LOAD,
        True,
        5,
        "Build it",
    )


def test_the_average_is_integer_zero_when_no_file_links_out(tmp_path: Path):
    skill = tmp_path / "demo"
    write(skill, "SKILL.md", "| R | A |\n|---|---|\n| Go | `references/a.md` |\n")
    write(skill, "references/a.md", "a\n")
    a = analyze_skill(skill)
    assert a.structure.average_links == 0
    assert a.structure.max_links_out_file is None


def test_structure_rows_render_average_links_as_float_text(tmp_path: Path):
    skill = tmp_path / "demo"
    write(skill, "SKILL.md", "| R | A |\n|---|---|\n| Go | `references/a.md` |\n")
    write(
        skill, "references/a.md", "Read `references/b.md`.\nRead `references/c.md`.\n"
    )
    write(skill, "references/b.md", "Read `references/c.md`.\n")
    write(skill, "references/c.md", "Read `references/b.md`.\n")
    rows = structure_rows(analyze_skill(skill).structure)
    assert (rows[2].measure, rows[2].value) == (
        "Average links per linking file",
        "1.33 (4 links, 3 files)",
    )

    lone = tmp_path / "lone"
    write(lone, "SKILL.md", "| R | A |\n|---|---|\n| Go | `references/a.md` |\n")
    write(lone, "references/a.md", "a\n")
    rows = structure_rows(analyze_skill(lone).structure)
    assert (rows[2].measure, rows[2].value) == (
        "Average links per linking file",
        "0 (0 links, 0 files)",
    )


def test_module_of_groups_by_directory_or_stem_prefix():
    assert module_of("scripts/a-b.sh") == "scripts"
    assert module_of("references/build-micro.md") == "build"
    assert module_of("references/plan.md") == "plan"


def test_structure_rows_report_status_per_measure(tmp_path: Path):
    rows = structure_rows(demo(tmp_path).structure)
    assert (rows[0].measure, rows[0].value, rows[0].status) == (
        "Mutual links",
        "0",
        "ok",
    )
    assert rows[2].value == "1.0 (2 links, 2 files)"
    assert rows[2].target == "<= 2"
    assert len(rows) == 8
    assert rows[7].value == "3 (Build it)"


def test_dispatch_cost_prints_point_range_or_unresolved():
    dispatch = Dispatch("builder", "x", [], False, 5, 5, [])
    assert dispatch_cost(dispatch) == "~5"
    dispatch = Dispatch("builder", "x", [], False, 5, 9, [])
    assert dispatch_cost(dispatch) == "~5-9"
    dispatch = Dispatch("builder", "x", [], False, None, None, [])
    assert dispatch_cost(dispatch) == "unresolved"


def test_how_topics_reported_apart_from_route_totals(tmp_path):
    from varde_learn.docs.flow.analyze import analyze_skill

    skill = tmp_path / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Demo\n", encoding="utf-8")
    before = analyze_skill(skill)
    assert (before.how_topics, before.how_total_tokens) == ([], 0)

    how = tmp_path / "how" / "demo"
    how.mkdir(parents=True)
    (how / "a.md").write_text("x" * 40, encoding="utf-8")
    (how / "b.md").write_text("y" * 80, encoding="utf-8")
    after = analyze_skill(skill)
    assert [(t.id, t.tokens) for t in after.how_topics] == [
        ("demo/a", 10),
        ("demo/b", 20),
    ]
    assert after.how_total_tokens == 30
    assert after.routes == before.routes
    assert after.tokens == before.tokens


def test_flow_doc_lists_how_topics_only_when_present(tmp_path):
    from varde_learn.docs.flow.analyze import analyze_skill
    from varde_learn.docs.flow.render import flow_doc

    skill = tmp_path / "skills" / "demo"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Demo\n", encoding="utf-8")
    assert "## How topics" not in flow_doc(analyze_skill(skill))
    how = tmp_path / "how" / "demo"
    how.mkdir(parents=True)
    (how / "a.md").write_text("x" * 40, encoding="utf-8")
    assert "| demo/a | ~10 |" in flow_doc(analyze_skill(skill))
