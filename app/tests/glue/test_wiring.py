import sys
from types import ModuleType

from varde import cli
from varde.fastpath import run as run_fastpath
from varde.router import resolve


def _patch_signal(monkeypatch):
    monkeypatch.setattr(
        cli,
        "signal",
        type(
            "Signals",
            (),
            {"SIGPIPE": 1, "SIG_IGN": 0, "signal": staticmethod(lambda *_: None)},
        ),
    )


def _stub_hook_module(monkeypatch, dispatch):
    hook = ModuleType("varde.glue.hook")
    hook.__dict__["MAX_PAYLOAD_BYTES"] = 8 * 1024 * 1024
    hook.__dict__["dispatch"] = dispatch
    monkeypatch.setitem(sys.modules, "varde.glue.hook", hook)


def _stub_stdin(monkeypatch, payload=b""):
    class Buffer:
        @staticmethod
        def read(_size):
            return payload

    class Input:
        buffer = Buffer()

        @staticmethod
        def isatty():
            return False

    stream = Input()
    monkeypatch.setattr("sys.stdin", stream)
    return stream


def _resolved(argv):
    result = resolve(argv)
    assert result is not None
    return result


def test_search_edit_and_hook_resolve_to_app_routes():
    for command in ("search", "edit", "hook"):
        route, forwarded = _resolved([command, "arg"])
        assert route.module == "app"
        assert forwarded[1:] == ["arg"]


def test_hook_fastpath_dispatches_payload_without_module_discovery(monkeypatch, capsys):
    def dispatch(payload, harness):
        print(f"{payload['event']} {payload['input'].decode()} {harness}")
        return 0

    _stub_hook_module(monkeypatch, dispatch)
    monkeypatch.setattr(
        "varde.discovery.discover_modules",
        lambda: (_ for _ in ()).throw(AssertionError()),
    )
    _patch_signal(monkeypatch)
    stream = _stub_stdin(monkeypatch, b'{"session_id":"x"}')
    monkeypatch.setattr("varde.fastpath.select.select", lambda *_: ([stream], [], []))

    assert cli.main(["hook", "session-start", "--harness", "pi"]) == 0
    assert capsys.readouterr().out == 'session-start {"session_id":"x"} pi\n'


def test_hook_harness_option_forms(monkeypatch, capsys):
    _stub_hook_module(
        monkeypatch, lambda payload, harness: print(f"harness={harness}") or 0
    )
    _stub_stdin(monkeypatch)

    assert run_fastpath(["hook", "session-start", "--harness", "pi"]) == 0
    assert run_fastpath(["hook", "session-start", "--harness=claude"]) == 0
    assert run_fastpath(["hook", "session-start", "--harness"]) == 0
    assert capsys.readouterr().out == "harness=pi\nharness=claude\nharness=\n"


def test_prompt_hook_does_not_read_when_stdin_is_not_ready(monkeypatch, capsys):
    def dispatch(payload, harness):
        print(f"{payload['event']} {payload['input']!r} {harness}")
        return 0

    _stub_hook_module(monkeypatch, dispatch)

    class Buffer:
        def read(self, _size):
            raise AssertionError("stdin should not be read")

    class Input:
        buffer = Buffer()

        @staticmethod
        def isatty():
            return False

    monkeypatch.setattr("sys.stdin", Input())
    monkeypatch.setattr("varde.fastpath.select.select", lambda *_: ([], [], []))
    assert run_fastpath(["hook", "user-prompt-submit", "--harness", "pi"]) == 0
    assert capsys.readouterr().out == "user-prompt-submit b'' pi\n"


def test_fastpath_leaves_search_and_edit_to_app_route():
    assert run_fastpath(["search", "needle"]) is None
    assert run_fastpath(["edit", "preview"]) is None


def test_hook_root_help_exits_successfully(capsys):
    assert run_fastpath(["hook", "--help"]) == 0
    assert "Usage: varde hook <EVENT>" in capsys.readouterr().out
