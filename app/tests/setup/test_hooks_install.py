from __future__ import annotations

import json
from pathlib import Path

import pytest
from varde.setup.hooks_install import run
from varde.setup.hooks_install.common import shell_quote, shell_words
from varde.setup.hooks_install.json_hooks import (
    EVENTS,
    disabled_events,
    varde_words,
)


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("sys.argv", [str(tmp_path / "bin" / "varde")])
    return tmp_path


def config(home: Path, harness: str = "claude") -> Path:
    return home / (
        ".claude/settings.json" if harness == "claude" else ".codex/hooks.json"
    )


def invoke(args: list[str], capsys) -> str:
    assert run(args) == 0
    return capsys.readouterr().out


def document(path: Path) -> dict:
    return json.loads(path.read_text())


def varde_commands(doc: dict, event: str) -> list[str]:
    found = []
    for group in doc.get("hooks", {}).get(event, []):
        hooks = group.get("hooks", []) if isinstance(group, dict) else []
        for hook in hooks:
            command = hook.get("command", "")
            if "varde hook" in command:
                found.append(command)
    return found


def foreign() -> dict:
    return {
        "hooks": {
            "SessionStart": [
                {"hooks": [{"type": "command", "command": "echo foreign"}]}
            ],
            "PostToolUse": [
                {
                    "matcher": "*",
                    "hooks": [{"type": "command", "command": "echo foreign-tool"}],
                }
            ],
            "UserPromptSubmit": [
                {"hooks": [{"type": "command", "command": "echo foreign-prompt"}]}
            ],
        }
    }


def test_claude_and_codex_install_one_entry_and_preserve_foreign(home, capsys):
    for harness in ("claude", "codex"):
        path = config(home, harness)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(foreign()))
        invoke(["install", "--harness", harness], capsys)
        doc = document(path)
        for event in ("PreToolUse", "SessionStart", "PostToolUse", "UserPromptSubmit"):
            assert len(varde_commands(doc, event)) == 1
        pre_tool = doc["hooks"]["PreToolUse"][0]
        assert pre_tool["matcher"] == "Bash"
        assert "echo foreign" in path.read_text()


def test_install_creates_missing_file_and_is_idempotent(home, capsys):
    invoke(["install", "--harness", "claude"], capsys)
    path = config(home)
    before = path.read_text()
    out = invoke(["install", "--harness", "claude"], capsys)
    assert path.read_text() == before
    assert "up to date" in out


def test_install_uses_stable_link_and_rewrites_resolved_path_once(home, capsys):
    executable = home / "tools/varde"
    executable.parent.mkdir()
    executable.touch()
    link = home / ".local/bin/varde"
    link.parent.mkdir(parents=True)
    link.symlink_to(executable)
    path = config(home)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        f"{executable.resolve()} hook session-start "
                                        "--harness claude"
                                    ),
                                    "timeout": 20,
                                }
                            ]
                        }
                    ]
                }
            }
        )
    )

    invoke(["install", "--harness", "claude"], capsys)
    commands = varde_commands(document(path), "SessionStart")
    assert len(commands) == 1 and str(link) in commands[0]
    before = path.read_text()
    invoke(["install", "--harness", "claude"], capsys)
    assert path.read_text() == before


def test_install_falls_back_to_resolved_path_without_stable_link(home, capsys):
    invoke(["install", "--harness", "claude"], capsys)
    command = varde_commands(document(config(home)), "SessionStart")[0]
    assert str((home / "bin/varde").resolve()) in command


def test_stop_is_installed_removed_and_change_gated(home, capsys):
    invoke(["install", "--harness", "claude"], capsys)
    path = config(home)
    assert len(varde_commands(document(path), "Stop")) == 1
    invoke(["remove", "--harness", "claude"], capsys)
    assert not varde_commands(document(path), "Stop")
    assert "Stop" in disabled_events(("code",))
    assert "Stop" not in disabled_events(("change",))


def test_pre_tool_use_is_change_gated_and_removed(home, capsys):
    invoke(["install", "--harness", "claude"], capsys)
    path = config(home)
    assert len(varde_commands(document(path), "PreToolUse")) == 1
    assert "PreToolUse" in disabled_events(("code",))
    assert "PreToolUse" not in disabled_events(("change",))
    invoke(["install", "--harness", "claude", "--features", "code"], capsys)
    assert not varde_commands(document(path), "PreToolUse")
    invoke(["remove", "--harness", "claude"], capsys)
    assert not varde_commands(document(path), "PreToolUse")


@pytest.mark.parametrize("event", ["SessionStart", "PostToolUse"])
def test_edited_entry_is_kept_until_force(home, capsys, event):
    path = config(home)
    invoke(["install", "--harness", "claude"], capsys)
    doc = document(path)
    doc["hooks"][event][0]["hooks"][0]["timeout"] = 1
    path.write_text(json.dumps(doc))
    before = path.read_text()
    out = invoke(["install", "--harness", "claude"], capsys)
    assert "blocked" in out and event in out
    assert path.read_text() == before
    invoke(["install", "--harness", "claude", "--force"], capsys)
    assert document(path)["hooks"][event][0]["hooks"][0]["timeout"] != 1


def test_group_with_extra_key_is_edited(home, capsys):
    path = config(home)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "extra": True,
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        "/old/varde hook session-start --harness claude"
                                    ),
                                    "timeout": 20,
                                }
                            ],
                        }
                    ]
                }
            }
        )
    )
    out = invoke(["install", "--harness", "claude"], capsys)
    assert "blocked" in out


def test_group_with_second_hook_is_kept_and_reported(home, capsys):
    path = config(home)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        "/old/varde hook session-start --harness claude"
                                    ),
                                    "timeout": 20,
                                },
                                {"type": "command", "command": "echo other"},
                            ]
                        }
                    ]
                }
            }
        )
    )
    out = invoke(["install", "--harness", "claude"], capsys)
    assert "blocked" in out


def test_env_wrapped_varde_is_updated_not_duplicated(home, capsys):
    path = config(home)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        "env X=1 /old/varde hook session-start "
                                        "--harness claude"
                                    ),
                                    "timeout": 20,
                                }
                            ]
                        }
                    ]
                }
            }
        )
    )
    out = invoke(["install", "--harness", "claude"], capsys)
    doc = document(path)
    assert len(varde_commands(doc, "SessionStart")) == 1
    assert "blocked" in out and "X=1" in path.read_text()


def test_edit_blocks_only_its_event(home, capsys):
    path = config(home)
    invoke(["install", "--harness", "claude"], capsys)
    doc = document(path)
    doc["hooks"]["SessionStart"][0]["hooks"][0]["timeout"] = 1
    path.write_text(json.dumps(doc))
    invoke(["install", "--harness", "claude"], capsys)
    result = document(path)
    assert len(varde_commands(result, "SessionStart")) == 1
    assert len(varde_commands(result, "PostToolUse")) == 1


def test_remove_deletes_only_unified_entries(home, capsys):
    path = config(home)
    path.parent.mkdir(parents=True)
    original = foreign()
    path.write_text(json.dumps(original))
    invoke(["install", "--harness", "claude"], capsys)
    invoke(["remove", "--harness", "claude"], capsys)
    assert document(path) == original


def test_moved_varde_path_is_updated_not_blocked(home, capsys):
    path = config(home)
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": (
                                        "/old/varde hook session-start --harness claude"
                                    ),
                                    "timeout": 20,
                                }
                            ]
                        }
                    ]
                }
            }
        )
    )
    out = invoke(["install", "--harness", "claude"], capsys)
    assert "blocked" not in out and "/old/varde" not in path.read_text()


def test_skip_event_leaves_event_untouched(home, capsys):
    invoke(
        ["install", "--harness", "claude", "--skip-event", "UserPromptSubmit"], capsys
    )
    doc = document(config(home))
    assert "UserPromptSubmit" not in doc["hooks"]
    assert len(varde_commands(doc, "SessionStart")) == 1


def test_selected_features_remove_disabled_events_and_preserve_foreign(home, capsys):
    path = config(home)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(foreign()))
    invoke(["install", "--harness", "claude"], capsys)
    out = invoke(["install", "--harness", "claude", "--features", "toz,code"], capsys)
    doc = document(path)
    assert "removed UserPromptSubmit" in out
    assert not varde_commands(doc, "UserPromptSubmit")
    assert "echo foreign-prompt" in path.read_text()


def test_install_defaults_to_all_features_and_validates_custom_features(home, capsys):
    invoke(["install", "--harness", "claude"], capsys)
    assert len(varde_commands(document(config(home)), "UserPromptSubmit")) == 1
    with pytest.raises(SystemExit):
        run(["install", "--harness", "claude", "--features", "nope"])


@pytest.mark.parametrize(
    ("feature", "session", "post", "prompt"),
    [
        ("code", True, False, False),
        ("knowledge", False, True, False),
        ("change", False, True, True),
        ("learn", False, False, False),
    ],
)
def test_feature_event_matrix(home, capsys, feature, session, post, prompt):
    invoke(["install", "--harness", "claude", "--features", feature], capsys)
    path = config(home)
    if not (session or post or prompt):
        assert not path.exists()
        return
    doc = document(path)
    for event, expected in (
        ("SessionStart", session),
        ("PostToolUse", post),
        ("UserPromptSubmit", prompt),
    ):
        assert bool(varde_commands(doc, event)) is expected


def test_missing_config_remove_reports_noop(home, capsys):
    out = invoke(["remove", "--harness", "claude"], capsys)
    assert "nothing to remove" in out


def test_duplicate_harness_is_applied_once(home, capsys):
    out = invoke(["install", "--harness", "claude", "--harness", "claude"], capsys)
    assert out.count("installed SessionStart") == 1


def test_shell_quote_round_trips():
    quoted = shell_quote("/x/it's here/varde")
    command = f"{quoted} hook session-start"
    assert shell_words(command) == [
        "/x/it's here/varde",
        "hook",
        "session-start",
    ]
    assert varde_words(command, EVENTS[0]) == [
        "/x/it's here/varde",
        "hook",
        "session-start",
    ]
