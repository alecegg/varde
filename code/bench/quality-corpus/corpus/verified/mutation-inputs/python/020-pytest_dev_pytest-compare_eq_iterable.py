def _compare_eq_iterable(
    left: Iterable[object],
    right: Iterable[object],
    highlighter: _HighlightFunc,
    verbose: int = 0,
    truncation_budget: TruncationBudget = NO_TRUNCATION_BUDGET,
) -> Iterator[str]:
    if verbose <= 0 and not running_on_ci():
        yield "Use -v to get more diff"
        return
    # dynamic import to speedup pytest
    import difflib

    pp = PrettyPrinter()
    # ``pformat_lines`` spells an unbounded dimension ``None``; the budget spells it ``0``.
    max_lines = truncation_budget.max_lines or None
    max_chars = truncation_budget.max_chars or None
    left_formatting = pp.pformat_lines(left, max_lines=max_lines, max_chars=max_chars)
    right_formatting = pp.pformat_lines(right, max_lines=max_lines, max_chars=max_chars)

    yield ""
    yield "Full diff: (-: missing in left side, +: extra in left side)"
    # "right" is the expected base against which we compare "left",
    # see https://github.com/pytest-dev/pytest/issues/3333
    # Highlight each ndiff line individually so the streaming truncator can
    # stop pulling from ``difflib.ndiff`` once its budget is full; the diff
    # lexer is line-oriented, so per-line highlighting is equivalent.
    for line in difflib.ndiff(right_formatting, left_formatting):
        yield highlighter(line.rstrip(), lexer="diff")
