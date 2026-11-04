from __future__ import annotations

import sys
from pathlib import Path

import pytest
from varde.setup.hooks_install import codex_trust, run
from varde.setup.hooks_install import doctor as doctor_module
from varde.setup.hooks_install.codex_trust import untrusted_varde_hooks
from varde.setup.hooks_install.doctor import doctor_section


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("sys.argv", [str(tmp_path / "bin" / "varde")])
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("PI_CODING_AGENT_DIR", raising=False)
    monkeypatch.setattr(doctor_module, "query_hooks", lambda _: {})
    return tmp_path


def values(section):
    return [entry.json for entry in section.entries]


def test_missing_hooks_report_install_fixes(home):
    section = doctor_section()
    assert section.key == "hooks"
    entries = values(section)
    assert {entry["target"] for entry in entries} >= {
        "SessionStart",
        "PreToolUse",
        "PostToolUse",
        "UserPromptSubmit",
        "Stop",
        "plugin",
    }
    assert all(entry["state"] for entry in entries)
    assert all(
        entry["state"] == "missing"
        for entry in entries
        if entry["state"] != "unsupported"
    )
    stop = next(entry for entry in entries if entry["target"] == "Stop")
    assert stop["state"] == "missing"
    assert "setup hooks install" in stop["fix"]
    assert all(
        "setup hooks install" in entry.get("fix", "")
        for entry in entries
        if entry["state"] == "missing"
    )


def test_installed_plugins_are_current(home):
    run(["install", "--harness", "opencode", "--harness", "pi"])
    items = [entry for entry in values(doctor_section()) if entry["target"] == "plugin"]
    assert [(entry["harness"], entry["state"]) for entry in items] == [
        ("opencode", "current"),
        ("pi", "current"),
    ]


def test_edited_plugin_and_json_hook_are_reported(home):
    run(["install", "--harness", "pi", "--harness", "claude"])
    plugin = home / ".pi/agent/extensions/varde.ts"
    plugin.write_text(plugin.read_text() + "\n// edited\n")
    config = home / ".claude/settings.json"
    config.write_text(config.read_text().replace('"timeout": 30', '"timeout": 31'))
    found = values(doctor_section())
    assert next(e for e in found if e["harness"] == "pi")["state"] == "edited"
    assert (
        next(
            e
            for e in found
            if e["harness"] == "claude" and e["target"] == "PostToolUse"
        )["state"]
        == "edited"
    )


def test_pre_tool_use_doctor_state(home):
    run(["install", "--harness", "codex"])
    entry = next(
        item
        for item in values(doctor_section())
        if item["harness"] == "codex" and item["target"] == "PreToolUse"
    )
    assert entry["state"] == "current"


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("trusted", []),
        ("untrusted", ["untrusted"]),
        ("modified", ["modified"]),
        ("managed", []),
    ],
)
def test_codex_trust_parser(status, expected):
    response = {
        "result": {
            "data": [
                {
                    "cwd": "/repo",
                    "hooks": [
                        {
                            "key": "pre_tool_use:0:0",
                            "command": "varde hook",
                            "trustStatus": status,
                        }
                    ],
                }
            ]
        }
    }
    assert [
        hook["state"] for hook in untrusted_varde_hooks(response, Path("/repo"))
    ] == expected


def test_codex_trust_parser_ignores_other_and_malformed_hooks():
    response = {
        "result": {
            "data": [
                {
                    "cwd": "/repo",
                    "hooks": [
                        {"command": "other", "trustStatus": "untrusted"},
                        {"command": 42, "trustStatus": "untrusted"},
                        None,
                    ],
                }
            ]
        }
    }
    assert untrusted_varde_hooks(response, Path("/repo")) == []
    assert untrusted_varde_hooks({"result": None}) == []


def test_codex_trust_parser_uses_matching_cwd_or_all_entries():
    response = {
        "result": {
            "data": [
                {
                    "cwd": "/repo",
                    "hooks": [
                        {
                            "key": "pre_tool_use:0:0",
                            "command": "varde hook",
                            "trustStatus": "untrusted",
                        }
                    ],
                },
                {
                    "cwd": "/other",
                    "hooks": [
                        {
                            "key": "stop:0:0",
                            "command": "varde hook",
                            "trustStatus": "modified",
                        }
                    ],
                },
            ]
        }
    }
    assert [
        hook["state"] for hook in untrusted_varde_hooks(response, Path("/repo"))
    ] == ["untrusted"]
    assert [hook["state"] for hook in untrusted_varde_hooks(response)] == [
        "untrusted",
        "modified",
    ]
    assert [
        hook["state"]
        for hook in untrusted_varde_hooks(response, Path("/no/matching/entry"))
    ] == ["untrusted", "modified"]


def test_doctor_reports_codex_untrusted_hook(home, monkeypatch):
    monkeypatch.setattr(
        doctor_module,
        "query_hooks",
        lambda _: {
            "result": {
                "data": [
                    {
                        "cwd": str(Path.cwd()),
                        "hooks": [
                            {
                                "key": "pre_tool_use:0:0",
                                "command": "varde hook",
                                "trustStatus": "Untrusted",
                            }
                        ],
                    }
                ]
            }
        },
    )
    entry = next(
        item
        for item in values(doctor_section())
        if item["harness"] == "codex" and item["target"] == "pre-tool-use"
    )
    assert entry["state"] == "untrusted"
    assert entry["fix"] == "open codex and approve the hooks in /hooks"


def test_doctor_reports_unknown_when_codex_query_fails(home, monkeypatch):
    monkeypatch.setattr(doctor_module, "query_hooks", lambda _: None)
    monkeypatch.setattr(doctor_module.shutil, "which", lambda _: "/bin/codex")

    entry = next(
        item
        for item in values(doctor_section())
        if item["harness"] == "codex" and item["target"] == "trust-status"
    )
    assert entry["state"] == "unknown"


def test_doctor_skips_trust_entry_when_codex_is_absent(home, monkeypatch):
    monkeypatch.setattr(doctor_module, "query_hooks", lambda _: None)
    monkeypatch.setattr(doctor_module.shutil, "which", lambda _: None)

    assert not any(
        item["harness"] == "codex" and item["target"] == "trust-status"
        for item in values(doctor_section())
    )


def test_doctor_handles_deleted_cwd(home, monkeypatch):
    monkeypatch.setattr(
        doctor_module.Path, "cwd", lambda: (_ for _ in ()).throw(OSError())
    )
    monkeypatch.setattr(doctor_module.shutil, "which", lambda _: "/bin/codex")

    entry = next(
        item
        for item in values(doctor_section())
        if item["harness"] == "codex" and item["target"] == "trust-status"
    )
    assert entry["state"] == "unknown"


def test_query_hooks_uses_fake_codex_on_path(tmp_path, monkeypatch):
    executable_dir = tmp_path / "bin"
    executable_dir.mkdir()
    executable = executable_dir / "codex"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import json\n"
        "print(json.dumps({'id': 1, 'result': {}}), flush=True)\n"
        "print(json.dumps({'method': 'notice'}), flush=True)\n"
        "print(json.dumps({'id': 2, 'result': {'data': []}}), flush=True)\n"
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(executable_dir))

    assert codex_trust.query_hooks(tmp_path) == {"id": 2, "result": {"data": []}}


def test_opencode_user_prompt_event_is_unsupported(home):
    entry = next(
        e for e in values(doctor_section()) if e["target"] == "user-prompt-submit"
    )
    assert entry["state"] == "unsupported"
    assert "every model call" in entry["reason"]
