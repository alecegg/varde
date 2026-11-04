import json

from varde_code.query.output import paginate


def test_query_page_size_changes_when_capture_is_enabled():
    values = list(range(125))
    uncaptured, uncaptured_meta = paginate(values, {}, "hotspots")

    class Capture:
        def capture(self, input, source, label):
            return json.dumps(
                {"handle": "test-handle", "items": len(input.items or []), "toc": []}
            )

    captured, captured_meta = paginate(values, {}, "hotspots", Capture())

    assert uncaptured_meta is not None
    assert uncaptured == values[:100]
    assert uncaptured_meta["limit"] == 100
    assert captured_meta is not None
    assert captured == values[:20]
    assert captured_meta["limit"] == 20
