from __future__ import annotations

import io
import json
from types import SimpleNamespace

from varde_data.friction import open_friction
from varde_data.records.friction import (
    AdoptionRecorded,
    Event,
    ItemAdded,
    OccurrenceAppended,
    StatusChanged,
)
from varde_learn.loop import cli_friction


def _seed_store(directory, monkeypatch):
    monkeypatch.setenv("VARDE_LEARN_STORE", str(directory))
    directory.mkdir(parents=True)
    cwd = directory / "repo"
    cwd.mkdir()
    repository = open_friction(directory)
    at = "2025-01-01T00:00:00.000Z"
    item = Event.at(at, "/repo", ItemAdded("Slow tests", "pytest", "/repo"))
    repository.import_events(
        (
            item,
            Event.at(
                "2025-01-01T00:00:01.000Z",
                "/repo",
                OccurrenceAppended(
                    item.id, at, str(cwd), "Test run took too long", "/repo", "abc"
                ),
            ),
            Event.at(
                "2025-01-01T00:00:02.000Z",
                "/repo",
                StatusChanged(
                    item.id,
                    "2025-01-01T00:00:01.000Z",
                    "open",
                    "promoted",
                    "Recorded adoption 1",
                ),
            ),
            Event.at(
                "2025-01-01T00:00:03.000Z",
                None,
                AdoptionRecorded(
                    "2025-01-01T00:00:03.000Z",
                    "Reduced test runtime",
                    ["store.py"],
                    [item.id],
                ),
            ),
            Event.at(
                "2025-01-01T00:00:04.000Z",
                "/repo",
                StatusChanged(
                    item.id, "2025-01-01T00:00:04.000Z", "promoted", "resolved", "fixed"
                ),
            ),
            Event.at(
                "2025-01-01T00:00:05.000Z",
                "/repo",
                OccurrenceAppended(
                    item.id,
                    "2025-01-01T00:00:06.000Z",
                    str(cwd),
                    "Test run took too long",
                    "/repo",
                    "abc",
                ),
            ),
        )
    )


def _io():
    return SimpleNamespace(stdout=io.StringIO(), stderr=io.StringIO())


def test_list_json_reads_store_page(tmp_path, monkeypatch):
    from varde_learn.loop.cli_friction_read import run_list

    _seed_store(tmp_path / "store", monkeypatch)
    output = _io()

    assert run_list({"json": True, "limit": 1}, output) == 0
    payload = json.loads(output.stdout.getvalue())
    assert payload == {
        "schema_version": 1,
        "envelope_version": 1,
        "ok": True,
        "outcome": "success",
        "data": {
            "items": [
                {
                    "id": 1,
                    "slug": "slow-tests",
                    "title": "Slow tests",
                    "source": "pytest",
                    "repo_root": "/repo",
                    "status": "resolved",
                    "target": None,
                    "tags": [],
                    "created_at": "2025-01-01T00:00:00.000Z",
                }
            ]
        },
        "meta": {
            "total": 1,
            "offset": 0,
            "limit": 1,
            "next_offset": None,
            "truncated": False,
        },
    }


def test_friction_commands_json_preserve_store_config_error(tmp_path, monkeypatch):
    config = tmp_path / "config"
    config.mkdir()
    (config / "config.toml").write_text('[default]\nlearn = "  "\n')
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))
    monkeypatch.delenv("VARDE_LEARN_STORE", raising=False)
    commands = (
        ["friction", "list", "--json"],
        [
            "friction",
            "add",
            "--source",
            "test",
            "--title",
            "Example",
            "--text",
            "evidence",
            "--json",
        ],
    )
    for arguments in commands:
        output = _io()

        assert cli_friction.run(arguments, output) == 2

        error = json.loads(output.stderr.getvalue())["data"]["error"]
        assert error["code"] == "store_config_error"
        assert error["message"].startswith(
            f"invalid global learn store configuration at {config / 'config.toml'}:"
        )


def test_show_human_output_includes_occurrence_and_history(tmp_path, monkeypatch):
    from varde_learn.loop.cli_friction_read import run_show

    _seed_store(tmp_path / "store", monkeypatch)
    output = _io()

    assert run_show({"id": 1, "limit": 1}, output) == 0
    assert "1 slow-tests [resolved] Slow tests (pytest)" in output.stdout.getvalue()
    assert (
        "- 1 at 2025-01-01T00:00:00.000Z: Test run took too long"
        in output.stdout.getvalue()
    )
    assert (
        "- 1 open -> promoted at 2025-01-01T00:00:01.000Z: Recorded adoption 1"
        in output.stdout.getvalue()
    )


def test_show_brief_accepts_multiple_ids_and_bounds_evidence(tmp_path, monkeypatch):
    from varde_learn.loop import cli_friction

    _seed_store(tmp_path / "store", monkeypatch)
    output = _io()
    assert cli_friction.run(["show", "1", "slow-tests", "--brief"], output) == 0
    lines = output.stdout.getvalue().splitlines()
    assert len(lines) == 2
    assert all("2 occurrences" in line for line in lines)
    assert all(len(line.rsplit(" | ", 1)[-1]) <= 200 for line in lines)


def test_list_text_without_match_is_success(tmp_path, monkeypatch):
    from varde_learn.loop import cli_friction

    _seed_store(tmp_path / "store", monkeypatch)
    output = _io()
    assert cli_friction.run(["list", "--text", "no such item"], output) == 0
    assert output.stdout.getvalue() == "No friction items found.\n"


def test_show_accepts_slug_and_pagination(tmp_path, monkeypatch):
    from varde_learn.loop import cli_friction

    _seed_store(tmp_path / "store", monkeypatch)
    output = _io()

    assert (
        cli_friction.run(
            ["show", "slow-tests", "--offset", "0", "--limit", "1", "--json"], output
        )
        == 0
    )
    payload = json.loads(output.stdout.getvalue())
    assert payload["data"]["item"]["slug"] == "slow-tests"
    assert payload["meta"]["limit"] == 1


def test_export_writes_markdown_without_overwriting(tmp_path, monkeypatch):
    from varde_learn.loop.cli_friction_read import run_export

    _seed_store(tmp_path / "store", monkeypatch)
    output = _io()
    destination = tmp_path / "export"

    assert run_export({"directory": destination, "json": False}, output) == 0
    markdown = (destination / "slow-tests.md").read_text()
    cwd = (tmp_path / "store" / "repo").as_posix()
    assert markdown == (
        '---\nformat: "varde-friction-item"\nversion: 1\nid: 1\n'
        'slug: "slow-tests"\ntitle: "Slow tests"\nsource: "pytest"\n'
        'repo_root: "/repo"\nstatus: "resolved"\ntarget: null\n'
        'tags: []\ncreated_at: "2025-01-01T00:00:00.000Z"\noccurrences:\n'
        '  - id: 1\n    item_id: 1\n    at: "2025-01-01T00:00:00.000Z"\n'
        f'    cwd: "{cwd}"\n    repo_root: "/repo"\n    head_sha: "abc"\n'
        '    evidence: "Test run took too long"\n    cost: null\n'
        '  - id: 2\n    item_id: 1\n    at: "2025-01-01T00:00:06.000Z"\n'
        f'    cwd: "{cwd}"\n    repo_root: "/repo"\n    head_sha: "abc"\n'
        '    evidence: "Test run took too long"\n    cost: null\n'
        "status_changes:\n  - id: 1\n    item_id: 1\n"
        '    at: "2025-01-01T00:00:01.000Z"\n    from_status: "open"\n'
        '    to_status: "promoted"\n    reason: "Recorded adoption 1"\n'
        '  - id: 2\n    item_id: 1\n    at: "2025-01-01T00:00:04.000Z"\n'
        '    from_status: "promoted"\n    to_status: "resolved"\n'
        '    reason: "fixed"\n---\n\n'
        "# Friction item 1\n\n## Title\n\n```text\nSlow tests\n```\n\n"
        "## Occurrences\n\n### Occurrence 1\n\n- Recorded: 2025-01-01T00:00:00.000Z\n"
        "- Repository: /repo\n- Evidence:\n\n```text\nTest run took too long\n```\n\n"
        "### Occurrence 2\n\n- Recorded: 2025-01-01T00:00:06.000Z\n"
        "- Repository: /repo\n- Evidence:\n\n```text\nTest run took too long\n```\n\n"
        "## Status history\n\n### Change 1: open → promoted\n\n"
        "- Recorded: 2025-01-01T00:00:01.000Z\n- Reason:\n\n"
        "```text\nRecorded adoption 1\n```\n\n### Change 2: promoted → resolved\n\n"
        "- Recorded: 2025-01-01T00:00:04.000Z\n- Reason:\n\n"
        "```text\nfixed\n```\n\n"
    )
    assert run_export({"directory": destination, "json": True}, output) == 2
    assert "refusing to overwrite existing export path" in output.stderr.getvalue()


def test_adoption_recurrence_lists_later_occurrence(tmp_path, monkeypatch):
    from varde_learn.loop.cli_friction_read import run_adopt_recurrence

    _seed_store(tmp_path / "store", monkeypatch)
    output = _io()

    assert run_adopt_recurrence({"json": True, "offset": 0, "limit": 10}, output) == 0
    payload = json.loads(output.stdout.getvalue())
    assert payload["data"]["items"][0]["adoption_id"] == 1
    assert payload["data"]["items"][0]["occurrence"]["id"] == 2
