import json

from varde_learn.loop.diagnose.model import EvidenceRecord, ToolObservation
from varde_learn.loop.skill_runs import skill_runs


def call(name, payload, tool_id=None, error=None, **extra):
    inp = payload if isinstance(payload, str) else json.dumps(payload)
    return {
        "kind": "tool_call",
        "tool_name": name,
        "tool_input_excerpt": inp,
        "tool_use_id": tool_id,
        "tool_error": error,
        **extra,
    }


def skill(name, tool_id=None):
    return call("Skill", {"skill": name}, tool_id)


def bash(command, error=None):
    return call("Bash", {"command": command}, error=error)


def fail():
    return bash("false", error="boom")


def test_skill_tool_with_error_in_bound_is_suspected_skip():
    out = skill_runs([skill("plugin:varde-plan"), bash("ls"), fail()])
    assert out == {
        "varde-plan": {
            "loads": [],
            "post_errors": 1,
            "first_error": "boom",
            "suspected_skip": True,
        }
    }


def test_error_before_run_or_past_bound_not_counted():
    rows = [fail(), skill("varde-plan")] + [bash("ls")] * 10 + [fail()]
    out = skill_runs(rows)["varde-plan"]
    assert out["post_errors"] == 0
    assert out["first_error"] is None
    assert out["suspected_skip"] is False


def test_error_after_other_skill_run_not_counted():
    out = skill_runs([skill("varde-plan"), skill("varde-build"), fail()])
    assert out["varde-plan"]["post_errors"] == 0
    assert out["varde-build"]["post_errors"] == 1


def test_skill_md_read_is_a_run_but_ls_grep_edit_are_not():
    rows = [
        call("Read", {"file_path": "/h/skills/varde-plan/SKILL.md"}),
        bash("cat /h/skills/varde-build/SKILL.md"),
        bash("ls /h/skills/varde-learn/SKILL.md"),
        bash("grep x /h/skills/varde-code/SKILL.md"),
        bash("sed -i s/a/b/ /h/skills/varde-docs/SKILL.md"),
        call("Edit", {"file_path": "/h/skills/varde-toz/SKILL.md"}),
    ]
    assert set(skill_runs(rows)) == {"varde-plan", "varde-build"}


def test_loads_from_plain_json_and_quoted_forms_suppress_skip():
    rows = [
        skill("varde-plan"),
        bash("varde learn how varde-plan interactive-page"),
        bash("varde learn how varde-plan interactive-page --json"),
        bash('bash -c \'varde learn how "varde-plan" "interactive-page"\''),
        fail(),
    ]
    out = skill_runs(rows)["varde-plan"]
    assert out["loads"] == ["interactive-page"]
    assert out["post_errors"] == 1
    assert out["suspected_skip"] is False


def test_loads_sorted_and_deduplicated():
    rows = [
        skill("varde-plan"),
        bash("varde learn how varde-plan b"),
        bash("varde learn how varde-plan a"),
        bash("varde learn how varde-plan b"),
    ]
    assert skill_runs(rows)["varde-plan"]["loads"] == ["a", "b"]


def test_opencode_observations_only_record():
    def obs(tool_id, name, inp, error=None):
        return ToolObservation(
            "tool", tool_id, name, inp, None, "error" if error else "completed", error
        )

    record = EvidenceRecord(
        "s",
        None,  # type: ignore[arg-type]
        kind="assistant",
        tool_observations=[
            obs("1", "skill", json.dumps({"skill": "varde-plan"})),
            obs("2", "bash", json.dumps({"command": "varde learn how varde-plan x"})),
            obs("3", "bash", json.dumps({"command": "false"}), error="bad"),
        ],
    )
    out = skill_runs([record])["varde-plan"]
    assert out["loads"] == ["x"]
    assert out["post_errors"] == 1
    assert out["suspected_skip"] is False


def test_claude_parallel_calls_dedupe_by_tool_use_id():
    first = {
        "kind": "assistant",
        "tool_name": "Skill",
        "tool_input_excerpt": json.dumps({"skill": "varde-plan"}),
        "tool_use_id": "a",
        "tool_observations": [
            {
                "block_type": "tool_use",
                "tool_use_id": "a",
                "tool_name": "Skill",
                "input_excerpt": json.dumps({"skill": "varde-plan"}),
            },
            {
                "block_type": "tool_use",
                "tool_use_id": "b",
                "tool_name": "Bash",
                "input_excerpt": json.dumps(
                    {"command": "varde learn how varde-plan s"}
                ),
            },
            {
                "block_type": "tool_use",
                "tool_use_id": "c",
                "tool_name": "Bash",
                "input_excerpt": json.dumps({"command": "false"}),
            },
        ],
    }
    result = {
        "kind": "tool_result",
        "tool_observations": [
            {"block_type": "tool_result", "tool_use_id": "c", "error": "nope"}
        ],
    }
    out = skill_runs([first, result])["varde-plan"]
    assert out["loads"] == ["s"]
    assert out["post_errors"] == 1
    assert skill_runs([first])["varde-plan"]["post_errors"] == 0


def test_dataclass_records_accepted():
    record = EvidenceRecord(
        "s",
        None,  # type: ignore[arg-type]
        kind="tool_call",
        tool_name="Skill",
        tool_input_excerpt=json.dumps({"skill": "varde-build"}),
    )
    assert set(skill_runs([record])) == {"varde-build"}


def test_waste_anchor_in_bound_suspects_skip_without_errors():
    rows = [skill("varde-plan"), bash("ls"), bash("ls")]
    assert skill_runs(rows, [2])["varde-plan"]["suspected_skip"] is True
    assert skill_runs(rows, [0])["varde-plan"]["suspected_skip"] is False
    assert skill_runs(rows, [9])["varde-plan"]["suspected_skip"] is False
    assert skill_runs(rows)["varde-plan"]["suspected_skip"] is False


def test_first_error_capped_at_200_bytes_and_no_runs_is_empty():
    rows = [skill("varde-plan"), bash("x", error="e" * 500)]
    assert len(skill_runs(rows)["varde-plan"]["first_error"]) == 200
    assert skill_runs([bash("ls")]) == {}


def test_several_skills_in_one_session():
    rows = [
        skill("varde-plan"),
        bash("varde learn how varde-plan x"),
        skill("varde-build"),
        fail(),
    ]
    out = skill_runs(rows)
    assert out["varde-plan"]["suspected_skip"] is False
    assert out["varde-build"]["suspected_skip"] is True


def _read(skill_name):
    return f"sed -n 1,50p /x/{skill_name}/SKILL.md"


def test_codex_list_form_and_bash_lc_runs_detected():
    rows = [
        call("exec_command", {"command": ["bash", "-lc", _read("varde-build")]}),
        call("exec_command", {"cmd": "bash -lc 'cat /x/varde-docs/SKILL.md'"}),
        call("exec_command", {"cmd": _read("varde-plan")}),
        call(
            "exec_command",
            {"command": ["bash", "-lc", "sed -i s/a/b/ /x/varde-code/SKILL.md"]},
        ),
        call("exec_command", {"command": ["bash", "-lc", "ls /x"]}),
    ]
    assert set(skill_runs(rows)) == {"varde-build", "varde-docs", "varde-plan"}


def test_codex_list_form_doc_how_counts_as_load():
    rows = [
        call("exec_command", {"cmd": _read("varde-plan")}),
        call(
            "exec_command", {"command": ["bash", "-lc", "varde learn how varde-plan s"]}
        ),
        fail(),
    ]
    assert skill_runs(rows)["varde-plan"]["loads"] == ["s"]


def test_observation_without_id_does_not_double_count_top_level_call():
    payload = json.dumps({"command": "false"})
    row = {
        "kind": "assistant",
        "tool_name": "Bash",
        "tool_input_excerpt": payload,
        "tool_observations": [
            {"block_type": "tool_use", "tool_name": "Bash", "input_excerpt": payload}
        ],
    }
    rows = [skill("varde-plan"), row] + [bash("ls")] * 8 + [fail()]
    # the 10th call after the run is the failure only if the row counted once
    assert skill_runs(rows)["varde-plan"]["post_errors"] == 1


def test_skill_name_read_from_key_regardless_of_order():
    rows = [call("Skill", {"args": "x y", "skill": "plugin:varde-plan"})]
    assert set(skill_runs(rows)) == {"varde-plan"}
