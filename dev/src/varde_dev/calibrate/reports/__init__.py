"""Pure statistics and panel-label rules for calibration reports."""

from collections.abc import Callable, Sequence
from math import ceil, sqrt
from random import Random
from typing import Literal

Verdict = Literal["A", "B", "tie", "split"]
LabelClass = Literal["unanimous", "decisive", "panel-tie", "contested"]

VERDICTS: tuple[Verdict, ...] = ("A", "B", "tie", "split")


# Each of the 64 vote vectors has one explicit class.
PANEL_LABEL_TRUTH_TABLE: dict[tuple[Verdict, Verdict, Verdict], LabelClass] = {
    ("A", "A", "A"): "unanimous",
    ("A", "A", "B"): "decisive",
    ("A", "A", "tie"): "decisive",
    ("A", "A", "split"): "decisive",
    ("A", "B", "A"): "decisive",
    ("A", "B", "B"): "decisive",
    ("A", "B", "tie"): "contested",
    ("A", "B", "split"): "contested",
    ("A", "tie", "A"): "decisive",
    ("A", "tie", "B"): "contested",
    ("A", "tie", "tie"): "panel-tie",
    ("A", "tie", "split"): "contested",
    ("A", "split", "A"): "decisive",
    ("A", "split", "B"): "contested",
    ("A", "split", "tie"): "contested",
    ("A", "split", "split"): "contested",
    ("B", "A", "A"): "decisive",
    ("B", "A", "B"): "decisive",
    ("B", "A", "tie"): "contested",
    ("B", "A", "split"): "contested",
    ("B", "B", "A"): "decisive",
    ("B", "B", "B"): "unanimous",
    ("B", "B", "tie"): "decisive",
    ("B", "B", "split"): "decisive",
    ("B", "tie", "A"): "contested",
    ("B", "tie", "B"): "decisive",
    ("B", "tie", "tie"): "panel-tie",
    ("B", "tie", "split"): "contested",
    ("B", "split", "A"): "contested",
    ("B", "split", "B"): "decisive",
    ("B", "split", "tie"): "contested",
    ("B", "split", "split"): "contested",
    ("tie", "A", "A"): "decisive",
    ("tie", "A", "B"): "contested",
    ("tie", "A", "tie"): "panel-tie",
    ("tie", "A", "split"): "contested",
    ("tie", "B", "A"): "contested",
    ("tie", "B", "B"): "decisive",
    ("tie", "B", "tie"): "panel-tie",
    ("tie", "B", "split"): "contested",
    ("tie", "tie", "A"): "panel-tie",
    ("tie", "tie", "B"): "panel-tie",
    ("tie", "tie", "tie"): "panel-tie",
    ("tie", "tie", "split"): "panel-tie",
    ("tie", "split", "A"): "contested",
    ("tie", "split", "B"): "contested",
    ("tie", "split", "tie"): "panel-tie",
    ("tie", "split", "split"): "contested",
    ("split", "A", "A"): "decisive",
    ("split", "A", "B"): "contested",
    ("split", "A", "tie"): "contested",
    ("split", "A", "split"): "contested",
    ("split", "B", "A"): "contested",
    ("split", "B", "B"): "decisive",
    ("split", "B", "tie"): "contested",
    ("split", "B", "split"): "contested",
    ("split", "tie", "A"): "contested",
    ("split", "tie", "B"): "contested",
    ("split", "tie", "tie"): "panel-tie",
    ("split", "tie", "split"): "contested",
    ("split", "split", "A"): "contested",
    ("split", "split", "B"): "contested",
    ("split", "split", "tie"): "contested",
    ("split", "split", "split"): "contested",
}


def panel_label(votes: Sequence[Verdict]) -> tuple[LabelClass, tuple[Verdict, ...]]:
    """Return the panel class and the dissenting verdicts, preserving lens order."""
    if len(votes) != 3 or any(vote not in VERDICTS for vote in votes):
        raise ValueError("panel labels require exactly three valid lens verdicts")
    vector = tuple(votes)
    label = PANEL_LABEL_TRUTH_TABLE[vector]  # type: ignore[index]
    dissent: tuple[Verdict, ...] = ()
    if label == "decisive":
        majority = "A" if vector.count("A") == 2 else "B"
        dissent = tuple(vote for vote in vector if vote != majority)
    return label, dissent


def accuracy(expected: Sequence[str], predicted: Sequence[str]) -> float:
    """Fraction of matching labels; empty inputs and mismatched lengths are invalid."""
    _check_label_pairs(expected, predicted)
    return sum(
        left == right for left, right in zip(expected, predicted, strict=True)
    ) / len(expected)


def cohens_kappa(left: Sequence[str], right: Sequence[str]) -> float:
    """Cohen's kappa for two nominal label sequences."""
    _check_label_pairs(left, right)
    categories = set(left) | set(right)
    observed = accuracy(left, right)
    expected = (
        sum(left.count(label) * right.count(label) for label in categories)
        / len(left) ** 2
    )
    if expected == 1:
        return 1.0 if observed == 1 else 0.0
    return (observed - expected) / (1 - expected)


def wilson_interval(
    successes: int, trials: int, confidence_z: float = 1.959963984540054
) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion."""
    if trials <= 0 or not 0 <= successes <= trials or confidence_z <= 0:
        raise ValueError("expected 0 <= successes <= positive trials and positive z")
    proportion = successes / trials
    z_squared = confidence_z**2
    denominator = 1 + z_squared / trials
    center = (proportion + z_squared / (2 * trials)) / denominator
    margin = (
        confidence_z
        * sqrt(proportion * (1 - proportion) / trials + z_squared / (4 * trials**2))
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def cluster_bootstrap_interval(
    clusters: Sequence[Sequence[tuple[str, str]]],
    statistic: Callable[[Sequence[str], Sequence[str]], float],
    *,
    confidence: float = 0.95,
    replicates: int = 2000,
    seed: int = 0,
) -> tuple[float, float]:
    """Percentile interval from resampling whole clusters with a fixed seed."""
    if not clusters or any(not cluster for cluster in clusters):
        raise ValueError("clusters must be nonempty and contain observations")
    if not 0 < confidence < 1 or replicates < 1:
        raise ValueError(
            "confidence must be between zero and one and replicates positive"
        )
    rng = Random(seed)  # noqa: S311 - Seeded randomness makes bootstrap reports reproducible.
    estimates = []
    for _ in range(replicates):
        sampled = [clusters[rng.randrange(len(clusters))] for _ in clusters]
        expected = [pair[0] for cluster in sampled for pair in cluster]
        predicted = [pair[1] for cluster in sampled for pair in cluster]
        estimates.append(statistic(expected, predicted))
    estimates.sort()
    tail = (1 - confidence) / 2
    lower = estimates[max(0, ceil(tail * replicates) - 1)]
    upper = estimates[min(replicates - 1, ceil((1 - tail) * replicates) - 1)]
    return lower, upper


def _check_label_pairs(expected: Sequence[str], predicted: Sequence[str]) -> None:
    if not expected or len(expected) != len(predicted):
        raise ValueError("label sequences must have equal, nonzero length")
