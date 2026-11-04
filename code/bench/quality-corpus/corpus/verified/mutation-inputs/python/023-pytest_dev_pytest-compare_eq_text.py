def _compare_eq_text(
    left: str,
    right: str,
    highlighter: _HighlightFunc,
    verbose: int,
    assertion_text_diff_style: _AssertionTextDiffStyle,
    truncation_budget: TruncationBudget = NO_TRUNCATION_BUDGET,
) -> Iterator[str]:
    match assertion_text_diff_style:
        case "block":
            yield from _diff_text_block(left, right)
        case "ndiff":
            yield from _diff_text(left, right, highlighter, verbose, truncation_budget)
        case unreachable:
            assert_never(unreachable)
