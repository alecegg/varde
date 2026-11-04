"""Exact token-weighted means represented as an integer rational."""

from dataclasses import dataclass

from .arithmetic import MICRO


@dataclass(frozen=True)
class ScopeScore:
    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        if self.denominator <= 0:
            raise ValueError("scope denominator must be positive")
        if not 0 <= self.numerator <= 100 * MICRO * self.denominator:
            raise ValueError("scope score must be between zero and 100")


def score_for_tokens(score_micro: int, tokens: int) -> ScopeScore:
    if tokens <= 0:
        raise ValueError("tokens must be positive")
    return ScopeScore(score_micro * tokens, tokens)


def combine(children: list[ScopeScore]) -> ScopeScore:
    if not children:
        raise ValueError("a scope requires at least one child")
    return ScopeScore(
        sum(child.numerator for child in children),
        sum(child.denominator for child in children),
    )


def meets_threshold(score: ScopeScore, threshold_micro: int) -> bool:
    """Compare without converting the rational score or threshold to float."""
    return score.numerator >= threshold_micro * score.denominator
