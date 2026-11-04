from varde_serve.events.buffer import EventBuffer, parse_cursor


def test_since_replays_after_cursor_and_none_means_now() -> None:
    buf = EventBuffer(gen="g")
    first = buf.publish("plan.state", "p", {})
    buf.publish("plan.state", "q", {})
    assert buf.since(None) == ([], False)
    events, reset = buf.since(first["id"])
    assert [e["subject"] for e in events] == ["q"]
    assert reset is False
    assert buf.since(buf.cursor) == ([], False)


def test_reset_for_other_gen_malformed_future_and_evicted() -> None:
    buf = EventBuffer(capacity=3, gen="g")
    for n in range(5):
        buf.publish("plan.state", str(n), {})
    assert buf.since("other:2") == ([], True)
    assert buf.since("garbage") == ([], True)
    assert buf.since("g:99") == ([], True)
    assert buf.since("g:1") == ([], True)  # evicted: buffer holds 3..5
    events, reset = buf.since("g:2")
    assert reset is False
    assert [e["id"] for e in events] == ["g:3", "g:4", "g:5"]


def test_parse_cursor() -> None:
    assert parse_cursor("ab:3") == ("ab", 3)
    assert parse_cursor("x") is None
    assert parse_cursor(None) is None
