import pytest
from varde_serve.mcp.protocol import handle
from varde_serve.mcp.tools import TOOL_NAMES, TOOLS, BadArguments, route_for


def never(tool, args):
    raise AssertionError("no daemon call expected")


def rpc(method: str, params=None, message_id=1) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": message_id,
        "method": method,
        "params": params or {},
    }


def test_four_tools_with_short_descriptions() -> None:
    assert {"varde_read", "varde_search", "varde_write", "varde_events"} == TOOL_NAMES
    assert all(len(t["description"]) < 80 for t in TOOLS)


def test_initialize_list_and_notification_need_no_daemon() -> None:
    init = handle(rpc("initialize", {"protocolVersion": "2025-03-26"}), never)
    assert init["result"]["protocolVersion"] == "2025-03-26"  # type: ignore[index]
    listed = handle(rpc("tools/list"), never)
    assert len(listed["result"]["tools"]) == 4  # type: ignore[index]
    assert (
        handle({"jsonrpc": "2.0", "method": "notifications/initialized"}, never) is None
    )
    assert handle(rpc("nope"), never)["error"]["code"] == -32601  # type: ignore[index]
    assert handle("junk", never)["error"]["code"] == -32600  # type: ignore[index]


def test_tool_call_wraps_result_and_bad_arguments() -> None:
    def call(tool, args):
        return False, {"tool": tool}

    ok = handle(rpc("tools/call", {"name": "varde_read", "arguments": {}}), call)
    assert ok["result"]["isError"] is False  # type: ignore[index]

    def bad(tool, args):
        raise BadArguments("nope")

    assert handle(rpc("tools/call", {"name": "x"}), bad)["error"]["code"] == -32602  # type: ignore[index]


@pytest.mark.parametrize(
    ("tool", "args", "expected"),
    [
        ("varde_read", {"resource": "plans"}, ("GET", "/api/plans")),
        (
            "varde_read",
            {"resource": "plans/p1/tasks/t1"},
            ("GET", "/api/plans/p1/tasks/t1"),
        ),
        ("varde_read", {"resource": "docs/a/b.md"}, ("GET", "/api/docs/a/b.md")),
        (
            "varde_read",
            {"resource": "friction", "query": {"tag": "x"}, "limit": 5},
            ("GET", "/api/friction?limit=5&tag=x"),
        ),
        (
            "varde_search",
            {"q": "a b", "domain": "docs"},
            ("GET", "/api/search?q=a+b&domain=docs"),
        ),
        (
            "varde_events",
            {"cursor": "g:1", "wait_s": 3},
            ("GET", "/api/events/poll?cursor=g%3A1&wait_s=3"),
        ),
        (
            "varde_write",
            {"action": "mail_send", "args": {"to": "m", "kind": "info", "text": "t"}},
            ("POST", "/api/mail"),
        ),
        (
            "varde_write",
            {
                "action": "reply",
                "args": {"path": "a.md", "comment_id": "c1", "text": "t"},
            },
            ("POST", "/api/docs/a.md/comments/c1/replies"),
        ),
    ],
)
def test_route_mapping(tool, args, expected) -> None:
    method, path, _ = route_for(tool, args)
    assert (method, path) == expected


@pytest.mark.parametrize(
    ("tool", "args"),
    [
        ("varde_read", {"resource": "config"}),
        ("varde_read", {}),
        ("varde_search", {"q": ""}),
        ("varde_write", {"action": "decision", "args": {}}),
        ("varde_write", {"action": "comment", "args": {"path": "a"}}),
        ("nope", {}),
    ],
)
def test_bad_arguments_and_human_actions_are_refused(tool, args) -> None:
    with pytest.raises(BadArguments):
        route_for(tool, args)
