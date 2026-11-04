import json
import os
import runpy
import subprocess
import sys
import time
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_each_emitted_phase_span_is_aliased_and_reconciles_with_wall_time(tmp_path):
    profiler = runpy.run_path(str(ROOT / "toz/scripts/toz-latency/profile_phases.py"))
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.toml").write_text(
        '[hooks.post_tool_use]\nproviders=["capture","toz_note"]\nthreshold=128\n'
    )
    payload = {
        "hook_event_name": "PostToolUse",
        "session_id": "phase-test",
        "tool_name": "Bash",
        "tool_input": {"command": "make"},
        "tool_response": {"stdout": "x" * 200, "stderr": "", "interrupted": False},
    }
    env = os.environ.copy()
    source_path = str(ROOT / "toz/src")
    env["PYTHONPATH"] = source_path + os.pathsep + env.get("PYTHONPATH", "")
    env.update(
        {
            "CONFIG_DIR": str(config),
            "TOZ_CONFIG_DIR": str(config),
            "VARDE_TOZ_DATA_DIR": str(tmp_path / "data"),
            "VARDE_TOZ_PHASE_TRACE": "1",
        }
    )
    started = time.perf_counter_ns()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "varde_toz.cli",
            "hook",
            "post-tool-use",
            "--harness",
            "claude",
        ],
        input=json.dumps(payload).encode(),
        capture_output=True,
        cwd=ROOT,
        env=env,
        check=True,
    )
    wall_ms = (time.perf_counter_ns() - started) / 1e6
    spans = []
    for line in result.stderr.decode().splitlines():
        if line.startswith("PHASE_TRACE|"):
            _, name, nanoseconds = line.split("|", 2)
            assert name in profiler["ALIASES"]
            spans.append(int(nanoseconds) / 1e6)
    assert spans
    measured_ms = sum(spans)
    assert measured_ms <= wall_ms


def test_nested_phase_spans_are_reported_exclusively():
    from varde_toz.phase_trace import span

    output = StringIO()
    started = time.perf_counter_ns()
    with redirect_stderr(output), span("parent"):
        time.sleep(0.002)
        with span("child"):
            time.sleep(0.002)
    wall_ms = (time.perf_counter_ns() - started) / 1e6
    durations = [
        int(line.rsplit("|", 1)[1]) / 1e6 for line in output.getvalue().splitlines()
    ]
    assert len(durations) == 2
    assert sum(durations) <= wall_ms
