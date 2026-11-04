import json

from varde_code.query.output import paginate, render


def test_uncaptured_compact_modes_use_default_page_size():
    for mode in ("hotspots", "filter_symbols"):
        page, metadata = paginate(list(range(150)), {}, mode)

        assert page == list(range(100))
        assert metadata == {
            "shown": 100,
            "total": 150,
            "offset": 0,
            "limit": 100,
            "next_offset": 100,
            "request": "set resultsOffset to next_offset, or set fullResults to true",
        }

    page, metadata = paginate(list(range(150)), {}, "symbols_in_file")

    assert metadata is not None
    assert page == list(range(100))
    assert metadata["shown"] == 100


def test_captured_compact_results_include_page_recovery_metadata():
    class Capture:
        def capture(self, input, source, label):
            return json.dumps(
                {"handle": "test-handle", "items": len(input.items or []), "toc": []}
            )

    result = render(
        list(range(150)),
        {"repoRoot": "/repo", "mode": "hotspots"},
        capture=Capture(),
    )

    assert result["data"] == list(range(20))
    assert result["meta"]["pagination"]["results"] == {
        "shown": 20,
        "total": 150,
        "offset": 0,
        "limit": 20,
        "next_offset": 20,
        "request": "set resultsOffset to next_offset, or set fullResults to true",
        "toz_read": "varde run query --handle test-handle --lines 21:40",
        "toz_search": 'varde run query --handle test-handle "<term>"',
    }
    assert result["meta"]["toz"] == {
        "handle": "test-handle",
        "items": 150,
        "format": "jsonl",
        "toc": "",
    }
