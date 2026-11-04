from varde_code.quality_pass.graph import (
    chain_depth,
    cross_module_depth,
    distinct_callees,
    dominated_private_helpers,
    fan_out,
    fragment_counts,
)


def edge(caller, callee=None, kind="resolved", **extra):
    return {"caller": caller, "callee": callee, "kind": kind, **extra}


def fact(function_id, *, line=1, name="fn", private=False, exempt=None, module="pkg"):
    return {
        "id": function_id,
        "line": line,
        "name": name,
        "file_private": private,
        "exempt_role": exempt,
        "module": module,
    }


def test_chain_depth_uses_facts_for_exemptions_and_trivial_ids():
    edges = [edge("a", "wrapper"), edge("wrapper", "impl"), edge("impl", "done")]
    facts = [fact("a"), fact("wrapper", exempt="accessor"), fact("impl"), fact("done")]
    assert chain_depth(edges, "a", 5, 100, facts=facts) == (2, False)
    assert chain_depth(edges, "a", 5, 100, trivial_ids={"wrapper"}) == (2, False)


def test_chain_depth_skips_library_calls_and_opaque_alone_adds_depth_and_fan_out():
    edges = [edge("a", kind="external"), edge("a", kind="opaque")]
    assert chain_depth(edges, "a", 5, 100) == (1, False)
    assert distinct_callees(edges, "a") == 0
    assert fan_out(edges, "a") == 1


def test_depth_reports_h_when_expansion_cap_is_reached():
    edges = [edge("a", "b"), edge("a", "c"), edge("b", "d"), edge("c", "e")]
    assert chain_depth(edges, "a", 8, 1) == (8, True)


def test_longest_simple_depth_h_back_edge_and_cycles():
    chain = [edge("a", "b"), edge("b", "c"), edge("c", "d")]
    assert chain_depth(chain, "a", 8, 100) == (3, False)
    assert chain_depth(chain + [edge("d", "a")], "a", 8, 100) == (3, False)
    assert chain_depth(chain + [edge("d", "a")], "a", 2, 100) == (2, True)


def test_depth_order_is_stable_under_small_cap_and_shuffled_edges():
    edges = [edge("a", "c", line=5), edge("a", "b", line=2), edge("b", "d")]
    forward = chain_depth(edges, "a", 7, 2)
    reversed_edges = chain_depth(list(reversed(edges)), "a", 7, 2)
    assert forward == reversed_edges == (7, True)


def test_cross_module_path_is_reported_but_excluded_from_scored_depth():
    edges = [edge("a", "b"), edge("b", "c"), edge("c", "d")]
    facts = [
        fact("a", module="one"),
        fact("b", module="two"),
        fact("c", module="two"),
        fact("d", module="three"),
    ]
    assert chain_depth(edges, "a", 6, 100, facts=facts) == (0, False)
    assert cross_module_depth(edges, "a", 6, facts=facts) == 3


def test_distinct_callees_counts_only_unique_resolved_in_repo_targets():
    edges = [
        edge("a", "b"),
        edge("a", "b"),
        edge("a", "external", kind="external"),
        edge("a", kind="ambiguous"),
        edge("a", kind="opaque"),
    ]
    assert distinct_callees(edges, "a") == 1


def test_dominated_private_helpers_on_tree_diamond_and_shared_intermediate():
    facts = [
        fact("root"),
        fact("left", private=True),
        fact("right", private=True),
        fact("leaf", private=True),
        fact("other"),
    ]
    tree = [edge("root", "left"), edge("left", "leaf")]
    assert dominated_private_helpers(tree, facts)["root"] == 2
    diamond = [
        edge("root", "left"),
        edge("root", "right"),
        edge("left", "leaf"),
        edge("right", "leaf"),
    ]
    assert dominated_private_helpers(diamond, facts)["root"] == 3
    shared_intermediate = tree + [edge("other", "left")]
    assert dominated_private_helpers(shared_intermediate, facts)["root"] == 0


def test_dominated_helpers_follow_wrappers_without_counting_them_and_skip_root_cycle():
    facts = [
        fact("root"),
        fact("wrapper", exempt="accessor"),
        fact("helper", private=True),
    ]
    edges = [edge("root", "wrapper"), edge("wrapper", "helper"), edge("helper", "root")]
    assert dominated_private_helpers(edges, facts)["root"] == 1
    assert dominated_private_helpers(edges, facts)["helper"] == 0


def test_fragment_counts_use_function_size_private_usage_and_caller_scope():
    file_facts = [
        {
            "path": "pkg/a.py",
            "call_coverage": {"resolved": 8, "ambiguous": 1, "opaque": 1},
            "functions": [
                {
                    "id": "a",
                    "tokens": 60,
                    "file_private": True,
                    "callers_in_module": 1,
                    "fragment_scope": "file",
                },
                {
                    "id": "b",
                    "tokens": 61,
                    "file_private": True,
                    "callers_in_module": 1,
                    "fragment_scope": "file",
                },
                {
                    "id": "c",
                    "tokens": 20,
                    "file_private": False,
                    "callers_in_module": 0,
                    "fragment_scope": None,
                },
                {
                    "id": "d",
                    "tokens": 20,
                    "file_private": True,
                    "exempt_role": "accessor",
                    "callers_in_module": 1,
                    "fragment_scope": "file",
                },
                {
                    "id": "e",
                    "tokens": 30,
                    "file_private": True,
                    "callers_in_module": 1,
                    "fragment_scope": "module",
                },
            ],
        },
        {
            "path": "pkg/b.py",
            "call_coverage": {"resolved": 20, "ambiguous": 0, "opaque": 0},
            "functions": [
                {
                    "id": "f",
                    "tokens": 40,
                    "file_private": True,
                    "callers_in_module": 2,
                    "fragment_scope": "module",
                }
            ],
        },
    ]
    result = fragment_counts(file_facts, 60)
    assert result["file"] == 1
    assert result["module"] == 1
    assert result["per_file"]["pkg/a.py"]["unresolved_share"] == 200_000
    assert result["per_file"]["pkg/a.py"]["structure_confidence"] == "normal"


def test_unresolved_share_uses_fixed_point_and_low_confidence_above_thirty_percent():
    facts = [
        {
            "path": "pkg/a.py",
            "call_coverage": {"resolved": 6, "ambiguous": 2, "opaque": 2},
            "functions": [],
        }
    ]
    result = fragment_counts(facts, 60)
    assert result["per_file"]["pkg/a.py"]["unresolved_share"] == 400_000
    assert result["per_file"]["pkg/a.py"]["structure_confidence"] == "low"


def test_long_trivial_chain_does_not_use_python_recursion():
    wrapper_ids = {f"w{index}" for index in range(1200)}
    edges = [edge("root", "w0")]
    edges.extend(edge(f"w{index}", f"w{index + 1}") for index in range(1199))
    edges.append(edge("w1199", "impl"))
    assert chain_depth(edges, "root", 6, 2000, trivial_ids=wrapper_ids) == (1, False)
