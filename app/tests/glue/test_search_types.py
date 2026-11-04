from varde.glue.search.types import SearchHit, SourceResult


def test_found_result_keeps_search_hits_as_an_immutable_sequence() -> None:
    hit = SearchHit("code", "title", "file.py:1", "matching text", 2)
    hits = [hit]

    result = SourceResult.found("code", hits)
    hits.clear()

    assert result.hits == (hit,)
    assert result.reason is None


def test_unavailable_result_keeps_reason_without_hits() -> None:
    result = SourceResult.unavailable("knowledge", "store unavailable")

    assert result == SourceResult("knowledge", reason="store unavailable")
    assert result.hits is None
