from __future__ import annotations

from varde_learn.loop.improve import tool_bypass as tb
from varde_learn.loop.improve.tool_entry import ToolRow

ROWS = [ToolRow("varde-x", "step", "varde-x/step.py")]
SCRIPT = "/pkg/varde_x/step_tools/varde-x/step.py"


def call(text: str, name: str = "Bash") -> dict:
    return {"tool_name": name, "tool_input_excerpt": text}


def test_wrapper_run_yields_no_signal() -> None:
    records = [
        call("python -m varde_learn.loop.improve.tool_entry varde-x/step --flag"),
        {"tool_name": None, "tool_input_excerpt": SCRIPT},
        {"role": "assistant"},
    ]
    assert tb.find_bypass(records, ROWS, "s1") == []


def test_running_the_script_directly_is_a_bypass() -> None:
    [signal] = tb.find_bypass([call(f"python3 {SCRIPT} a")], ROWS, "s1")
    assert signal.as_dict() == {"skill": "varde-x", "step": "step", "session": "s1"}


def test_reading_the_script_is_a_bypass() -> None:
    records = [call(f'{{"file_path": "{SCRIPT}"}}', name="Read")]
    assert [s.step for s in tb.find_bypass(records, ROWS, "s2")] == ["step"]


def test_one_signal_per_tool_and_unregistered_scripts_ignored() -> None:
    records = [call(SCRIPT), call(SCRIPT), call("cat /pkg/step_tools/varde-y/z.py")]
    assert len(tb.find_bypass(records, ROWS, "s")) == 1
