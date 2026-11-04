from copy import deepcopy
from itertools import pairwise
from pathlib import Path

from mutations import (
    add_branches,
    agent_tree,
    back_edge,
    flatten,
    formatting_only,
    forwarder_chain,
    fragment,
    grow,
    inline_helper,
    nest,
    rename_to_short_names,
)
from varde_code.quality_pass.graph import chain_depth
from varde_code.quality_pass.pass_.measures import tree_size
from varde_code.quality_score import score_scope
from varde_code.quality_score.calibration import load_calibration

CALIBRATION = (
    Path(__file__).parents[3]
    / "src/varde_code/quality_score/calibration/placeholder.toml"
)


def _facts(*, tokens: int = 1200, cognitive: int = 40) -> dict:
    return {
        "contract": "facts-1",
        "path": "src/a.py",
        "language": "python",
        "module": "src",
        "tokens": tokens,
        "structure_confidence": "normal",
        "functions": [
            {
                "id": "src/a.py::work",
                "line": 4,
                "tokens": 120,
                "cognitive": cognitive,
                "params": 1,
                "depth": 1,
                "fan_out": 1,
                "tree_size": 1,
                "name_issues": [],
                "exempt_role": None,
                "fragment_scope": None,
            }
        ],
    }


def _score(facts: dict) -> int:
    calibration = load_calibration(CALIBRATION)
    return score_scope([facts], calibration).files[0].score


def _debt(facts: dict) -> int:
    calibration = load_calibration(CALIBRATION)
    return score_scope([facts], calibration).files[0].debt


def _components(facts: dict) -> dict[str, int]:
    calibration = load_calibration(CALIBRATION)
    return score_scope([facts], calibration).files[0].components


def test_name_nesting_growth_and_branch_mutations_do_not_reduce_debt():
    base = _facts()
    for changed in (
        rename_to_short_names(base),
        nest(base, 4),
        grow(base, 5),
        add_branches(base, 5),
    ):
        assert _debt(changed) >= _debt(base)
    assert _debt(rename_to_short_names(base)) > _debt(base)
    assert (
        _components(rename_to_short_names(base))["names"] > _components(base)["names"]
    )
    assert _debt(nest(base, 4)) > _debt(base)
    assert _debt(grow(base, 5)) > _debt(base)
    assert _debt(add_branches(base, 5)) > _debt(base)


def test_formatting_only_mutation_is_exactly_invariant():
    base = _facts()
    assert _score(formatting_only(base)) == _score(base)
    assert formatting_only(base) == base


def test_fragment_and_forwarder_mutations_expose_small_callable_debt():
    base = _facts(cognitive=0)
    assert _score(fragment(base, 6, piece_tokens=12)) < _score(base)
    assert _score(forwarder_chain(base, 5)) < _score(base)


def test_fragment_keeps_original_functions_and_appends_helpers():
    base = _facts(cognitive=0)
    changed = fragment(base, 6, piece_tokens=12)
    assert changed["functions"][:1] == base["functions"]
    assert len(changed["functions"]) == 7
    assert changed["tokens"] == base["tokens"] + 6 * 12
    assert _debt(changed) > _debt(base)


def test_tiny_and_padded_large_agent_trees_lose_to_thoughtful_split():
    base = _facts(cognitive=0)
    base["functions"][0]["tokens"] = 320
    thoughtful = fragment(base, 4, piece_tokens=80)
    assert _score(agent_tree(base, 20)) <= _score(thoughtful) - 10_000_000
    assert _score(agent_tree(base, 20, padded=True)) <= _score(thoughtful) - 10_000_000


def test_inline_helper_removes_trivial_callable_within_score_rise_tolerance():
    base = _facts(tokens=100_000, cognitive=0)
    base["functions"].append(
        {
            **base["functions"][0],
            "id": "src/a.py::helper",
            "tokens": 8,
            "cognitive": 0,
            "depth": 0,
            "fan_out": 0,
            "tree_size": 0,
            "fragment_scope": "file",
        }
    )
    inlined = inline_helper(base)
    assert len(inlined["functions"]) == len(base["functions"]) - 1
    assert _debt(inlined) <= _debt(base)
    assert _score(inlined) <= _score(base) + 500_000


def test_mutations_leave_the_source_facts_unchanged():
    base = _facts()
    original = deepcopy(base)
    fragment(base, 3)
    forwarder_chain(base, 3)
    agent_tree(base, 5, padded=True)
    assert base == original


CHAIN = ["src/a.py::a", "src/a.py::b", "src/a.py::c", "src/a.py::d"]
HOP_LIMIT = 8
EXPANSION_CAP = 1000


def _chain_edges() -> list[dict]:
    return [
        {"caller": caller, "callee": callee, "kind": "resolved", "site_line": line}
        for line, (caller, callee) in enumerate(pairwise(CHAIN), start=1)
    ]


def _facts_with_measures(edges: list[dict]) -> dict:
    facts = _facts(cognitive=0)
    function = facts["functions"][0]
    function["id"] = CHAIN[0]
    depth, _ = chain_depth(edges, CHAIN[0], HOP_LIMIT, EXPANSION_CAP)
    function["depth"] = depth
    function["fan_out"] = 1
    function["tree_size"] = tree_size(edges, CHAIN[0], HOP_LIMIT, EXPANSION_CAP)
    return facts


def test_back_edge_closes_the_chain_without_changing_depth_or_score():
    edges = _chain_edges()
    cyclic = back_edge(edges, CHAIN)
    assert len(cyclic) == len(edges) + 1
    assert cyclic[-1]["caller"] == CHAIN[-1]
    assert cyclic[-1]["callee"] == CHAIN[0]
    assert chain_depth(cyclic, CHAIN[0], HOP_LIMIT, EXPANSION_CAP) == (3, False)
    assert chain_depth(cyclic, CHAIN[0], HOP_LIMIT, EXPANSION_CAP) == chain_depth(
        edges, CHAIN[0], HOP_LIMIT, EXPANSION_CAP
    )
    assert tree_size(cyclic, CHAIN[0], HOP_LIMIT, EXPANSION_CAP) == tree_size(
        edges, CHAIN[0], HOP_LIMIT, EXPANSION_CAP
    )
    assert _facts_with_measures(cyclic) == _facts_with_measures(edges)
    assert _score(_facts_with_measures(cyclic)) == _score(_facts_with_measures(edges))


def test_back_edge_leaves_the_source_edges_unchanged():
    edges = _chain_edges()
    original = deepcopy(edges)
    back_edge(edges, CHAIN)
    assert edges == original


FLATTEN_RISE_PER_HELPER = 500_000


def _structured_facts(helper_tokens: int, helper_count: int) -> dict:
    base = _facts(tokens=100_000, cognitive=0)
    base["functions"][0]["tokens"] = 200
    base["functions"].extend(
        {
            **base["functions"][0],
            "id": f"src/a.py::helper{index}",
            "tokens": helper_tokens,
            "cognitive": 0,
            "depth": 0,
            "fan_out": 0,
            "tree_size": 0,
            "fragment_scope": "file",
        }
        for index in range(helper_count)
    )
    return base


def test_flatten_rise_stays_within_half_a_point_per_inlined_helper():
    for helper_tokens in (20, 40, 80):
        for helper_count in (1, 2, 3):
            base = _structured_facts(helper_tokens, helper_count)
            flat = flatten(base, helper_count)
            assert len(flat["functions"]) == 1
            rise = _score(flat) - _score(base)
            assert rise <= FLATTEN_RISE_PER_HELPER * helper_count, (
                helper_tokens,
                helper_count,
                rise,
            )


def test_flatten_merges_at_most_the_requested_helpers_and_keeps_source():
    base = _structured_facts(40, 3)
    original = deepcopy(base)
    flat = flatten(base, 2)
    assert base == original
    assert [function["id"] for function in flat["functions"]] == [
        "src/a.py::work",
        "src/a.py::helper2",
    ]
    assert flat["functions"][0]["tokens"] == 200 + 2 * 40
