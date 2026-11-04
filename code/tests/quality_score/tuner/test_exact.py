import itertools
from collections.abc import Mapping

from varde_code.quality_score.tuner import fit_exact
from varde_code.quality_score.tuner.exact import deviation, grid_points

START = {"A": 2_000_000, "wL": 600_000, "w": 1_000_000, "structure": 1_000_000}
BOUNDS = {
    "A": (100_000, 600_000),
    "wL": (100_000, 400_000),
    "w": (100_000, 300_000),
}


def nonlinear_margins(strengths: Mapping[str, int]) -> list[int]:
    """Margins nonlinear in the strengths, like real component debts."""
    a, wl, w = strengths["A"], strengths["wL"], strengths["w"]
    return [
        1_000_000 - (a * a // 1_000_000) - wl,
        (a * wl // 1_000_000) - w // 2 - 20_000,
        400_000 - w - a // 3,
    ]


def exact_worst(strengths: Mapping[str, int], floor: int) -> int:
    return min(nonlinear_margins(strengths))


def test_grid_points_are_multiples_of_step_inside_bounds() -> None:
    assert grid_points(120_000, 260_000) == (150_000, 200_000, 250_000)


def test_search_equals_exhaustive_optimum_and_tie_prefers_start() -> None:
    result = fit_exact(exact_worst, START, BOUNDS)

    best = None
    for a, wl, w in itertools.product(
        grid_points(*BOUNDS["A"]), grid_points(*BOUNDS["wL"]), grid_points(*BOUNDS["w"])
    ):
        worst = min(nonlinear_margins({"A": a, "wL": wl, "w": w}))
        key = (
            -worst,
            deviation((a, wl, w), (2_000_000, 600_000, 1_000_000)),
            (a, wl, w),
        )
        best = key if best is None or key < best else best
    assert best is not None
    assert result.worst == -best[0]
    assert (
        result.strengths["A"],
        result.strengths["wL"],
        result.strengths["w"],
    ) == best[2]
    assert result.strengths["structure"] == START["structure"]


def test_pruning_floor_never_changes_the_result() -> None:
    calls: list[int] = []

    def pruned(strengths: Mapping[str, int], floor: int) -> int:
        worst = min(nonlinear_margins(strengths))
        calls.append(floor)
        return worst if worst >= floor else floor - 1

    assert fit_exact(pruned, START, BOUNDS) == fit_exact(exact_worst, START, BOUNDS)
    assert max(calls) > min(calls)
