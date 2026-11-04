def _compare_eq_mapping(
    left: Mapping[object, object],
    right: Mapping[object, object],
    highlighter: _HighlightFunc,
    verbose: int = 0,
    truncation_budget: TruncationBudget = NO_TRUNCATION_BUDGET,
) -> Iterator[str]:
    # Use the key views rather than ``set(left)``/``set(right)``: their set
    # operations resolve membership through the mappings themselves, so a
    # mapping with its own key equivalence (case-insensitive keys, for
    # example) is compared the way it compares itself.
    keys_left = left.keys()
    keys_right = right.keys()
    common = keys_left & keys_right
    same = {k: left[k] for k in common if left[k] == right[k]}
    if same and verbose < 2:
        yield f"Omitting {len(same)} identical items, use -vv to show"
    elif same:
        yield "Common items:"
        yield from highlighter(pprint.pformat(same)).splitlines()
    diff = {k for k in common if left[k] != right[k]}
    if diff:
        yield "Differing items:"
        for k in diff:
            yield (
                highlighter(saferepr({k: left[k]}))
                + " != "
                + highlighter(saferepr({k: right[k]}))
            )
    extra_left = keys_left - keys_right
    len_extra_left = len(extra_left)
    if len_extra_left:
        yield f"Left contains {len_extra_left} more item{'' if len_extra_left == 1 else 's'}:"
        yield from _format_extra_items(left, extra_left, highlighter, truncation_budget)
    extra_right = keys_right - keys_left
    len_extra_right = len(extra_right)
    if len_extra_right:
        yield f"Right contains {len_extra_right} more item{'' if len_extra_right == 1 else 's'}:"
        yield from _format_extra_items(
            right, extra_right, highlighter, truncation_budget
        )
