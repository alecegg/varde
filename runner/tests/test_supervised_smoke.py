from __future__ import annotations

import asyncio
import importlib.util
import json
from io import BytesIO
from pathlib import Path

from fakes.plugin import FakePlugin
from varde_runner.events import RunnerEvent
from varde_runner.plugins import SessionSpec

_PATH = Path(__file__).parents[1] / "scripts" / "supervised_smoke.py"
_SPEC = importlib.util.spec_from_file_location("supervised_smoke", _PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


class FakeRunner:
    def __init__(self, events: list[dict[str, object]]) -> None:
        body = b"".join(
            b"data: " + json.dumps(event).encode() + b"\n" for event in events
        )
        self.stream = BytesIO(body)


class FakeOpener:
    def __init__(self, runner: FakeRunner) -> None:
        self.runner = runner

    def open(self, request, timeout):
        return self.runner.stream


def use_fake_runner(monkeypatch, events: list[dict[str, object]]) -> None:
    runner = FakeRunner(events)
    monkeypatch.setattr(
        _MODULE.urllib.request,
        "build_opener",
        lambda *_: FakeOpener(runner),
    )


def test_fake_plugin_output_is_classified_as_frame_seen(monkeypatch) -> None:
    plugin = FakePlugin()
    ref = asyncio.run(plugin.start(SessionSpec("fake", "model", "workspace", "cwd")))
    event = RunnerEvent("text", ref.session_id, {"text": "ready"})
    use_fake_runner(monkeypatch, [{"kind": event.kind, "payload": event.payload}])
    assert _MODULE.wait_for_output(1234, "agent", 1) == "frame_seen"


def test_fake_runner_startup_diagnostic_is_classified(monkeypatch) -> None:
    event = {
        "kind": "warning",
        "payload": {"text": "The child produced no output after 30.0s."},
    }
    use_fake_runner(monkeypatch, [event])
    assert _MODULE.wait_for_output(1234, "agent", 1) == "diagnostic"


def test_non_output_events_do_not_end_wait() -> None:
    assert (
        _MODULE.classify_event({"kind": "status", "payload": {"status": "running"}})
        is None
    )


def test_missing_output_is_reported_as_failure_outcome(monkeypatch) -> None:
    use_fake_runner(monkeypatch, [])
    assert _MODULE.wait_for_output(1234, "agent", 1) == "timeout"
