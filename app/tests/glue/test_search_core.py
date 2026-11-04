from varde.glue.search.core import (
    parse_search_args,
    render_json,
    render_text,
    search_all,
)
from varde.glue.search.types import SearchHit, SearchQuery, SourceResult


class Source:
    def __init__(self, name, hits=(), error=None):
        self.name = name
        self.hits = hits
        self.error = error

    def source(self):
        return self.name

    def search(self, query):
        if self.error:
            raise self.error
        return SourceResult.found(self.name, self.hits[: query.limit])


def test_parse_query_sources_limit_and_json_flag():
    query, selected, as_json = parse_search_args(
        ["needle", "--in", "friction,code", "--limit", "3", "--json"]
    )

    assert query == SearchQuery("needle", 3)
    assert selected == ("code", "friction")
    assert as_json is True


def test_search_all_orders_sources_and_turns_exceptions_into_unavailable():
    code_hit = SearchHit("code", "A", "a.py:1", "needle", 4)
    sources = [
        Source("friction", [SearchHit("friction", "F", "f", "needle")]),
        Source("code", [code_hit]),
        Source("knowledge", error=RuntimeError("store failed")),
    ]

    results = search_all(sources, SearchQuery("needle", 5))

    assert [result.source for result in results] == ["code", "knowledge", "friction"]
    assert results[0].hits == (code_hit,)
    assert results[1] == SourceResult.unavailable("knowledge", "store failed")


def test_renderers_keep_group_order_and_match_search_output_shape():
    results = [
        SourceResult.found(
            "code", [SearchHit("code", "A", "a.py:1", "line one\nline two", 2)]
        ),
        SourceResult.unavailable("knowledge", "no knowledge store"),
    ]

    assert render_text(results) == (
        "## code (1)\n- A  a.py:1\n    line one line two\n"
        "## knowledge (unavailable)\n- no knowledge store\n"
    )
    assert render_json(results, SearchQuery("needle", 5)) == {
        "schema_version": 1,
        "envelope_version": 1,
        "ok": True,
        "outcome": "success",
        "data": {
            "groups": [
                {
                    "source": "code",
                    "status": "ok",
                    "hits": [
                        {
                            "source": "code",
                            "title": "A",
                            "location": "a.py:1",
                            "snippet": "line one\nline two",
                            "score": 2,
                        }
                    ],
                },
                {
                    "source": "knowledge",
                    "status": "unavailable",
                    "reason": "no knowledge store",
                    "hits": [],
                },
            ]
        },
        "meta": {"query": "needle", "limit": 5},
    }


def test_all_six_groups_render_in_the_shared_group_order():
    sources = [
        Source(name, [SearchHit(name, name.upper(), f"{name}.md:1", "needle")])
        for name in ("friction", "output", "plans", "knowledge", "docs", "code")
    ]

    rendered = render_text(search_all(sources, SearchQuery("needle", 5)))

    assert [line for line in rendered.splitlines() if line.startswith("## ")] == [
        "## code (1)",
        "## docs (1)",
        "## knowledge (1)",
        "## plans (1)",
        "## output (1)",
        "## friction (1)",
    ]
