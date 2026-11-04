import re

from varde_learn.docs.pages.graph import assign_layers, parse_deps, render_deps
from varde_learn.docs.pages.render import render_page
from varde_learn.docs.pages.template import static_css


def edges(text: str) -> dict[str, list[str]]:
    """`task: dep, dep` lines as the `edges` prop."""
    result: dict[str, list[str]] = {}
    for line in text.splitlines():
        task, sep, rest = line.partition(":")
        if sep and task.strip() and not task.startswith("#"):
            deps = [d.strip() for d in rest.split(",") if d.strip()]
            result.setdefault(task.strip(), []).extend(deps)
    return result


FORBIDDEN = re.compile(r"<script|foreignObject|<[^>]*\s(style|on\w+)=", re.IGNORECASE)


def test_layers_by_depth():
    graph = parse_deps(edges("a:\nb: a\nc: a, b\nd: c"))
    assert assign_layers(graph) == {"a": 0, "b": 1, "c": 2, "d": 3}
    out = render_deps(edges("a:\nb: a\nc: a, b"))
    assert out.count('class="node"') == 3
    assert out.count('class="edge"') == 3


def test_cycle_is_tolerated():
    out = render_deps(edges("a: b\nb: a\nc: c"))
    assert "<svg" in out and out.count("<g class=") == 3


def test_missing_dependency_shown():
    out = render_deps(edges("a: ghost"))
    assert 'class="node missing"' in out and "ghost (not defined)" in out


def test_labels_escaped_and_no_active_content():
    out = render_deps(edges('x"><script>alert(1)</script>: <img onerror=1>, b'))
    assert "<script" not in out and "&lt;script&gt;" in out
    assert not FORBIDDEN.search(out)


def test_empty_and_page_registration():
    assert "No dependencies" in render_deps(edges("# nothing"))
    page = render_page(
        '# Plan\n\n```ui id=g\ng = deps(edges: {"t1": [], "t2": ["t1"]})\n```\n', "plan"
    )
    assert "<svg" in page.body and not FORBIDDEN.search(page.body)


def test_unknown_dependencies_and_edges_are_capped():
    out = render_deps(edges("a: " + ",".join(f"d{i}" for i in range(20000))))
    assert out.count("<g class=") <= 200 and out.count('class="edge') <= 400
    assert "Graph truncated" in out and len(out) < 200_000


def test_many_tasks_capped_with_notice():
    out = render_deps(edges("\n".join(f"t{i}:" for i in range(500))))
    assert out.count("<g class=") == 200 and "Graph truncated" in out
    assert "Graph truncated" not in render_deps(edges("a: b"))


def test_wide_graph_scrolls_at_natural_size():
    out = render_deps(edges("\n".join(f"t{i}:" for i in range(10))))
    assert out.startswith('<div class="scroll"><svg')
    assert 'width="1' in out  # natural pixel width, not shrunk to the viewport


def test_graph_css_makes_labels_readable_and_edges_unfilled():
    css = static_css()
    assert ".dep-graph .node text { fill: var(--vd-text)" in css
    assert ".dep-graph .edge { fill: none" in css
    assert ".dep-graph .arrow { fill: var(--vd-text-secondary)" in css
