import json

import pytest


def test_diagnose_help_uses_snapshot(capsys):
    from varde_learn.module import register

    result = register().run(["sessions", "show", "--help"])

    assert result == 0
    assert "Usage: varde learn sessions show --harness" in capsys.readouterr().out


def test_inspect_snapshot_out_can_be_paged_as_snapshot_in(tmp_path, capsys):
    from varde_learn.loop.cli_diagnose import run
    from varde_learn.loop.diagnose.capture import load_snapshot
    from varde_learn.loop.diagnose.snapshot import snapshot_document, write_snapshot

    def record(index: int) -> dict[str, object]:
        return {
            "anchor": {"record_index": index},
            "session_thread_id": "thread",
        }

    value = {
        "session": {"harness": "codex", "thread_id": "thread"},
        "children": [],
        "sources": [],
        "records": [record(0), record(1), record(2)],
        "overlap": "not_current",
        "coverage": {"truncated": False, "record_count": 3},
        "snapshot": {"digest": ""},
    }
    frozen = snapshot_document(value)
    output = tmp_path / "snapshot.json"
    write_snapshot(output, frozen)

    assert load_snapshot(output)["digest"] == frozen["digest"]
    assert (
        run(
            [
                "diagnose",
                "inspect",
                "--snapshot-in",
                str(output),
                "--offset",
                "1",
                "--limit",
                "1",
                "--json",
            ]
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["data"]["records"] == [
        {**record(1), "tool_output_length_bytes": None}
    ]
    assert payload["meta"] == {
        "offset": 1,
        "limit": 1,
        "total": 3,
        "returned": 1,
        "truncated": True,
    }


def test_unknown_diagnose_option_returns_json_parse_error(capsys):
    from varde_learn.module import register

    result = register().run(["sessions", "show", "--wat", "--json"])

    captured = capsys.readouterr()
    assert result == 2
    assert '"outcome":"tool-error"' in captured.err
    assert "--wat" in captured.err


def test_capture_reports_strict_request_json_error_as_envelope(tmp_path, capsys):
    from varde_learn.module import register

    request = tmp_path / "capture.json"
    request.write_text("{")
    result = register().run(["sessions", "capture", "--file", str(request), "--json"])

    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    assert result == 2
    assert payload["data"]["error"]["code"] == "diagnose_capture_invalid"
    assert "invalid strict capture request JSON" in payload["data"]["error"]["message"]


def test_capture_rejects_file_with_flag_form_arguments(tmp_path, capsys):
    from varde_learn.loop.cli_diagnose import run

    request = tmp_path / "incident.json"
    request.write_text("{}")
    code = run(
        [
            "diagnose",
            "capture",
            "--file",
            str(request),
            "--source-id",
            "source",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().err)
    assert code == 2
    assert payload["data"]["error"]["code"] == "diagnose_capture_invalid"
    assert "cannot be combined" in payload["data"]["error"]["message"]


def test_eval_output_validation_matches_missing_eval_set(tmp_path, capsys):
    from varde_learn.module import register

    skill = tmp_path / "skill"
    skill.mkdir()
    skill_content = (
        "---\nname: synthetic-skill\ndescription: Synthetic skill.\n---\n"
        "# Synthetic skill\n"
    )
    (skill / "SKILL.md").write_text(skill_content)
    result = register().run(
        ["measure", str(skill), "output", "--harness", "codex", "--no-baseline"]
    )

    captured = capsys.readouterr()
    assert result == 2
    assert f"no eval set at {skill.resolve()}/evals/evals.json" in captured.err


def test_eval_output_replays_runner_transcript(tmp_path):
    from varde_learn.loop.output import OutputHarness
    from varde_learn.loop.output.command import OutputRequest, run_output

    skill = tmp_path / "skill"
    (skill / "evals").mkdir(parents=True)
    skill_content = (
        "---\nname: synthetic-skill\ndescription: Synthetic skill.\n---\n"
        "# Synthetic skill\n"
    )
    (skill / "SKILL.md").write_text(skill_content)
    (skill / "evals/evals.json").write_text(
        json.dumps({"evals": [{"id": "one", "prompt": "write result"}]})
    )
    requests = []

    def runner(request):
        requests.append(request)
        return (
            {"result": "A result", "usage": {"input_tokens": 2, "output_tokens": 3}},
            0,
            1,
        )

    report = run_output(
        OutputRequest(
            skill_dir=skill,
            harness=OutputHarness.CODEX,
            workspace=tmp_path / "runs",
            no_baseline=True,
        ),
        runner=runner,
    )

    assert len(requests) == 1
    assert requests[0].prompt.endswith("write result")
    assert report.records[0].eval_id == "one"
    assert report.records[0].outcome == "completed"


def test_eval_calibrate_validates_mutations_before_harness(tmp_path):
    from varde_learn.loop.output.command import OutputHarness, calibrate

    skill = tmp_path / "skill"
    (skill / "evals").mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Synthetic skill\n")

    with pytest.raises(ValueError) as raised:
        calibrate(skill, OutputHarness.CODEX, runner=lambda *_: ({}, 0, 0))
    assert f"cannot read {skill.resolve()}/evals/mutations.json" in str(raised.value)


def test_eval_calibrate_json_uses_tool_error_envelope(tmp_path, capsys):
    from varde_learn.module import register

    skill = tmp_path / "skill"
    (skill / "evals").mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Synthetic skill\n")
    result = register().run(
        ["measure", str(skill), "calibrate", "--harness", "codex", "--json"]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.err)
    assert result == 2
    assert payload["data"]["error"]["code"] == "usage_error"
    assert "cannot read" in payload["data"]["error"]["message"]


def test_summary_includes_skills_in_json_and_text(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace

    from varde_learn.loop.diagnose import summary

    records = [
        {
            "kind": "tool_call",
            "tool_name": "Skill",
            "tool_input_excerpt": json.dumps({"skill": "varde-plan"}),
            "tool_use_id": "s1",
        },
        {
            "kind": "tool_call",
            "tool_name": "Bash",
            "tool_input_excerpt": json.dumps({"command": "false"}),
            "tool_error": "boom",
        },
    ]
    item = SimpleNamespace(session_id="s", harness="codex", path=None)
    listing = SimpleNamespace(sessions=[item], warnings=[])
    monkeypatch.setenv("VARDE_LEARN_STORE", str(tmp_path / "store"))
    monkeypatch.setattr(summary, "list_sessions", lambda _request: listing)
    monkeypatch.setattr(
        summary,
        "harness_adapter",
        lambda _name: SimpleNamespace(
            inspect=lambda _r: SimpleNamespace(records=records)
        ),
    )
    options = {"harness": "codex", "repository": str(tmp_path)}
    data, _meta, text = summary.summarize(options)
    assert data["sessions"][0]["skills"]["varde-plan"]["suspected_skip"] is True
    assert "SKILL s varde-plan" in text
    records.clear()
    data, _meta, text = summary.summarize(options)
    assert "skills" not in data["sessions"][0]
