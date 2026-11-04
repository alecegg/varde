import json

from varde.setup.sync.report import MigrateEnv, Report, ReportEntry
from varde.setup.sync.support import (
    install_instructions,
    instruction_sections,
    retire_session_entries,
    retire_toz,
)


def test_sync_without_instruction_targets_reports_skip_reason(tmp_path):
    env = MigrateEnv(tmp_path, tmp_path, None, "", tmp_path, tmp_path / "varde", None)
    report = Report()

    install_instructions(env, [], ["orchestration"], report)

    assert report.skipped[0].reason == (
        "No instruction target was given, so the instruction block was not touched. "
        "Check install state with `varde setup doctor`."
    )


def test_report_keeps_migration_buckets_and_optional_command(tmp_path):
    report = Report(moved=[ReportEntry(tmp_path / "AGENTS.md", "updated")])
    report.skipped.append(
        ReportEntry(tmp_path / "config.toml", "warning").with_command(
            "varde setup instructions install"
        )
    )

    data = report.data()

    assert data["moved"] == [
        {"path": str(tmp_path / "AGENTS.md"), "reason": "updated", "command": None}
    ]
    assert data["skipped"][0]["command"] == "varde setup instructions install"
    assert data["unrewritable"] == data["would"] == []


def test_learn_note_is_selected_only_when_requested():
    assert "learn" not in instruction_sections({"toz"})
    assert instruction_sections({"learn"}) == ["learn"]
    assert "learn" not in instruction_sections({"change"})


def test_sync_feature_sections_follow_resolved_skills():
    assert instruction_sections({"toz"}) == ["toz"]
    assert instruction_sections({"change"}) == ["orchestration"]
    assert instruction_sections({"learn", "toz"}) == ["toz", "learn"]


def test_retire_toz_removes_only_manifest_owned_files(tmp_path):
    directory = tmp_path / "opencode"
    path = directory / "plugin/varde-toz.ts"
    path.parent.mkdir(parents=True)
    path.write_text("owned")
    from blake3 import blake3

    digest = blake3(b"owned").hexdigest()[:32]
    (directory / ".varde-toz-install.json").write_text(
        json.dumps({"files": {"plugin/varde-toz.ts": digest}})
    )

    assert retire_toz(directory, ["plugin/varde-toz.ts"]) == []
    assert not path.exists()


def test_retire_toz_preserves_edited_file(tmp_path):
    directory = tmp_path / "opencode"
    path = directory / "plugin/varde-toz.ts"
    path.parent.mkdir(parents=True)
    path.write_text("user edit")

    assert retire_toz(directory, ["plugin/varde-toz.ts"]) == [path]
    assert path.read_text() == "user edit"


def test_retire_session_entries_preserves_json_formatting(tmp_path):
    path = tmp_path / "settings.json"
    text = (
        "{\n"
        '  "custom": { "spacing": [1,  2] },\n'
        '  "hooks": {\n'
        '    "SessionStart": [\n'
        '      {"matcher":"","hooks":[{"type":"command",'
        '"command":"varde-workflow hook session-start --harness claude",'
        '"timeout":20}]},\n'
        '      {"matcher": "UserPromptSubmit", "hooks": []}\n'
        "    ]\n"
        "  }\n"
        "}\n"
    )
    path.write_text(text)
    env = MigrateEnv(tmp_path, tmp_path, None, "", tmp_path, tmp_path / "varde", None)

    retire_session_entries(env, "claude", path, Report())

    updated = path.read_text()
    assert '"custom": { "spacing": [1,  2] }' in updated
    assert '{"matcher": "UserPromptSubmit", "hooks": []}' in updated
    assert "varde-workflow" not in updated
