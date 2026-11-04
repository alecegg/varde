from varde_code.quality_score.costs import (
    CostParameters,
    file_costs,
    function_costs,
    function_coverage,
    module_fragmentation_cost,
    unique_functions,
)
from varde_code.quality_score.fixedpoint import MICRO


def test_size_cost_has_plateau_and_penalizes_tiny_and_large_functions():
    params = CostParameters()

    def size_cost(size):
        return (
            function_costs({"tokens": size, "cognitive": 0}, params)["long_side"]
            + function_costs({"tokens": size, "cognitive": 0}, params)["small_side"]
        )

    assert size_cost(8) > size_cost(32)
    assert size_cost(96) - size_cost(32) <= 120_000
    assert size_cost(400) > size_cost(96)


def test_splitting_plateau_function_into_plateau_pieces_changes_little():
    params = CostParameters()
    whole = function_costs({"tokens": 128, "cognitive": 0}, params)
    pieces = [function_costs({"tokens": 64, "cognitive": 0}, params) for _ in range(2)]
    stated_small_amount = 40_000
    assert (
        abs(sum(whole.values()) - sum(sum(piece.values()) for piece in pieces))
        <= stated_small_amount
    )


def test_splitting_function_into_tiny_helpers_raises_debt():
    params = CostParameters()
    whole = function_costs({"tokens": 96, "cognitive": 0}, params)
    helpers = [function_costs({"tokens": 24, "cognitive": 0}, params) for _ in range(4)]
    assert sum(sum(helper.values()) for helper in helpers) > sum(whole.values())


def test_cognitive_parameters_and_structure_cost_increase_above_comfort():
    params = CostParameters()
    easy = {
        "tokens": 60,
        "cognitive": 10,
        "params": 3,
        "depth": 3,
        "fan_out": 4,
        "tree_size": 6,
    }
    hard = {
        **easy,
        "cognitive": 40,
        "params": 9,
        "depth": 6,
        "fan_out": 10,
        "tree_size": 18,
    }
    assert sum(function_costs(hard, params).values()) > sum(
        function_costs(easy, params).values()
    )


def test_file_record_counts_null_measures_in_coverage():
    params = CostParameters()
    missing = function_costs(
        {
            "tokens": 50,
            "cognitive": 0,
            "depth": None,
            "fan_out": None,
            "tree_size": None,
        },
        params,
    )
    low = function_costs(
        {
            "tokens": 50,
            "cognitive": 0,
            "depth": 8,
            "fan_out": 20,
            "tree_size": 30,
        },
        params,
        file_record={"structure_confidence": "low"},
    )
    assert missing["depth"] == low["depth"] == 0
    assert missing["fan_out"] == low["fan_out"] == 0
    assert missing["tree_size"] == low["tree_size"] == 0
    coverage = function_coverage(
        [{"depth": None, "fan_out": None, "tree_size": None}],
        {"structure_confidence": "normal"},
    )
    assert coverage == {
        "functions": 1,
        "unmeasured_functions": 0,
        "unmeasured_depth": 1,
        "unmeasured_fan_out": 1,
        "unmeasured_tree_size": 1,
    }


def test_name_and_data_function_costs_are_capped():
    params = CostParameters(
        name_unit=MICRO, name_cap=2 * MICRO, data_function_cap=MICRO
    )
    names = function_costs({"tokens": 60, "name_issues": ["a", "b", "c"]}, params)
    data = function_costs(
        {"id": "data", "tokens": 60, "cognitive": 1000, "name_issues": ["vague"]},
        params,
        file_record={"data_functions": ["data"]},
    )
    assert names["names"] == 2 * MICRO
    assert sum(data.values()) <= MICRO


def test_file_costs_count_fragments_and_apply_per_component_caps():
    params = CostParameters(cF0=0, cFs=1, component_caps=(("fragmentation", MICRO),))
    record = {
        "tokens": 5000,
        "import_fan_out": 20,
        "functions": [
            {"tokens": 20, "fragment_scope": "file"},
            {"tokens": 30, "fragment_scope": "file"},
        ],
    }
    costs = file_costs(record, params)
    assert costs["fragmentation"] == MICRO
    assert costs["file_size"] > 0
    assert costs["import_fan_out"] > 0
    assert costs["file_overhead"] == 0


def test_module_fragmentation_counts_cross_file_helpers_once():
    params = CostParameters(cF0=0, cFs=1)
    records = [
        {"functions": [{"tokens": 20, "fragment_scope": "module"}]},
        {"functions": [{"tokens": 30, "fragment_scope": "module"}]},
    ]
    assert module_fragmentation_cost(records, params) == 4 * MICRO


def test_file_fragmentation_counts_paired_overloads_once():
    params = CostParameters(cF0=0, cFs=1)
    costs = file_costs(
        {
            "tokens": 100,
            "import_fan_out": 0,
            "functions": [
                {
                    "id": "base",
                    "overload_pair": "paired",
                    "tokens": 20,
                    "fragment_scope": "file",
                },
                {
                    "id": "paired",
                    "overload_pair": "base",
                    "tokens": 20,
                    "fragment_scope": "file",
                },
            ],
        },
        params,
    )
    assert costs["fragmentation"] == MICRO


def test_macro_overlap_is_unmeasured_and_paired_overloads_count_once():
    functions = [
        {
            "id": "f",
            "line": 10,
            "end_line": 20,
            "tokens": 50,
            "cognitive": 80,
            "unmeasured_regions": [{"start_line": 15, "end_line": 17}],
        },
        {"id": "base", "overload_pair": "paired"},
        {"id": "paired", "overload_pair": "base"},
    ]
    record = {
        "structure_confidence": "normal",
        "unmeasured_regions": [{"start_line": 15, "end_line": 17}],
        "functions": functions,
    }
    costs_without_macro = sum(
        sum(function_costs(fn, CostParameters(), file_record=record).values())
        for fn in functions[1:]
    )
    costs_with_macro = sum(
        sum(function_costs(fn, CostParameters(), file_record=record).values())
        for fn in functions
    )
    assert costs_with_macro == costs_without_macro
    assert [item["id"] for item in unique_functions(functions[1:])] == ["base"]


def test_file_level_unmeasured_regions_exclude_fragmentation():
    params = CostParameters(cF0=0, cFs=1)
    record = {
        "tokens": 100,
        "import_fan_out": 0,
        "structure_confidence": "normal",
        "unmeasured_regions": [{"start_line": 1, "end_line": 20}],
        "functions": [
            {
                "id": "macro_fn",
                "line": 3,
                "end_line": 12,
                "tokens": 10,
                "fragment_scope": "file",
            }
        ],
    }
    assert file_costs(record, params)["fragmentation"] == 0


def test_structure_costs_increase_for_forwarders_and_wide_or_deep_calls():
    params = CostParameters()

    def debt(function):
        return sum(
            function_costs({"tokens": 40, "cognitive": 0, **function}, params).values()
        )

    assert sum(
        debt({"depth": depth, "fan_out": 0, "tree_size": 0}) for depth in range(1, 5)
    ) > debt({"depth": 1, "fan_out": 0, "tree_size": 0})
    assert debt({"depth": 1, "fan_out": 0, "tree_size": 20}) > debt(
        {"depth": 1, "fan_out": 0, "tree_size": 6}
    )
    assert debt({"depth": 1, "fan_out": 20, "tree_size": 0}) > debt(
        {"depth": 1, "fan_out": 0, "tree_size": 0}
    )
    assert debt({"depth": 6, "fan_out": 0, "tree_size": 0}) > debt(
        {"depth": 1, "fan_out": 0, "tree_size": 0}
    )
