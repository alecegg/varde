def _compare_eq_any(
    left: object,
    right: object,
    highlighter: _HighlightFunc,
    verbose: int,
    assertion_text_diff_style: _AssertionTextDiffStyle,
    truncation_budget: TruncationBudget = NO_TRUNCATION_BUDGET,
) -> Iterator[str]:
    """Yield the per-line explanation for ``left == right`` (without summary).

    Yields nothing when no specialised explanation applies, so consumers
    can stream the output and bail out early (e.g. for truncation) without
    materialising the entire diff first.
    """
    if istext(left) and istext(right):
        yield from _compare_eq_text(
            left,
            right,
            highlighter,
            verbose,
            assertion_text_diff_style,
            truncation_budget,
        )
    else:
        from _pytest.approx import Approx

        # Although the common order should be obtained == approx(...), allow both ways.
        if isinstance(right, Approx):
            yield from right._repr_compare(left)
        elif isinstance(left, Approx):
            yield from left._repr_compare(right)
        elif type(left) is type(right) and (
            isdatacls(left) or isattrs(left) or isnamedtuple(left)
        ):
            # Note: unlike dataclasses/attrs, namedtuples compare only the
            # field values, not the type or field names. But this branch
            # intentionally only handles the same-type case, which was often
            # used in older code bases before dataclasses/attrs were available.
            yield from _compare_eq_cls(
                left,
                right,
                highlighter,
                verbose,
                assertion_text_diff_style,
            )
        elif issequence(left) and issequence(right):
            yield from _compare_eq_sequence(left, right, highlighter, verbose)
        elif isset(left) and isset(right):
            yield from _compare_eq_set(left, right, highlighter, verbose)
        elif ismapping(left) and ismapping(right):
            yield from _compare_eq_mapping(
                left, right, highlighter, verbose, truncation_budget
            )

        if isiterable(left) and isiterable(right):
            yield from _compare_eq_iterable(
                left, right, highlighter, verbose, truncation_budget
            )
