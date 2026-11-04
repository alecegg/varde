def _set_one_sided_diff(
    posn: str,
    set1: AbstractSet[object],
    set2: AbstractSet[object],
    highlighter: _HighlightFunc,
) -> Iterator[str]:
    diff = set1 - set2
    if diff:
        yield f"Extra items in the {posn} set:"
        for item in diff:
            yield highlighter(saferepr(item))
