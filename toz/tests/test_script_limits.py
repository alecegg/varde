from __future__ import annotations

import time

import wasmtime
from varde_toz.runner.script import Limits, Outcome, run_detailed, run_script


def test_output_limit_stops_script() -> None:
    outcome, records = run_script(
        "print('x'.repeat(100))", limits=Limits(max_output_bytes=10)
    )
    assert outcome is Outcome.OUTPUT_LIMIT
    assert records == []


def test_timeout_stops_script() -> None:
    outcome, _ = run_script("while (true) {}", limits=Limits(timeout_ms=25))
    assert outcome is Outcome.TIMEOUT


def test_module_compilation_does_not_consume_script_timeout(monkeypatch) -> None:
    from_file = wasmtime.Module.from_file.__func__

    def slow_compile(cls, engine, path):
        time.sleep(0.5)
        return from_file(cls, engine, path)

    monkeypatch.setattr(wasmtime.Module, "from_file", classmethod(slow_compile))
    outcome, records = run_script("print('ready')", limits=Limits(timeout_ms=250))

    assert outcome is Outcome.OK
    assert records == []


def test_memory_limit_stops_script() -> None:
    outcome, _ = run_script(
        "let values = []; for (let i=0; i<3000000; i++) values.push(i)",
        limits=Limits(memory_bytes=8 * 1024 * 1024),
    )
    assert outcome is Outcome.MEMORY_LIMIT


def test_record_limit_stops_script() -> None:
    outcome, records = run_script(
        "for (let i=0; i<10001; i++) toz.record('x', i)",
        limits=Limits(timeout_ms=60_000),
    )
    assert outcome is Outcome.RECORD_LIMIT
    assert records == []


def test_text_limit_stops_full_capture_read() -> None:
    outcome, _ = run_script(
        "toz.text()", input_text="0123456789\n", limits=Limits(max_text_bytes=8)
    )
    assert outcome is Outcome.EXCEPTION


def test_stack_limit_stops_recursion() -> None:
    outcome, _ = run_script(
        "function recurse(){return recurse()} recurse()",
        limits=Limits(max_stack_bytes=64 * 1024),
    )
    assert outcome is Outcome.EXCEPTION


def test_default_limits_finish_small_script_and_stop_infinite_loop() -> None:
    outcome, records = run_script("print('ok');", limits=Limits())
    assert outcome is Outcome.OK
    assert records == []

    outcome, _records = run_script("while (true) {}", limits=Limits(timeout_ms=25))
    assert outcome is Outcome.TIMEOUT


def test_script_code_buffer_is_nul_terminated(monkeypatch) -> None:
    written_buffers = []
    memory_write = wasmtime.Memory.write

    def capture_write(memory, store, value, start=None):
        written_buffers.append(bytes(value))
        return memory_write(memory, store, value, start)

    monkeypatch.setattr(wasmtime.Memory, "write", capture_write)
    printed = run_detailed("print('ready')", limits=Limits(timeout_ms=1000))

    code_buffers = [buffer for buffer in written_buffers if buffer.startswith(b"try {")]
    assert code_buffers
    assert all(buffer.endswith(b"\0") for buffer in code_buffers)
    assert printed.outcome is Outcome.OK
    assert "ready" in printed.output
