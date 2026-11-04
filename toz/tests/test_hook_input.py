import io
import json
import stat
import sys
from types import SimpleNamespace

from varde_toz import hook
from varde_toz.commands import event_note
from varde_toz.hook_input.compound import heading
from varde_toz.hook_input.cwd_noise import strip
from varde_toz.hook_input.readonly import is_readonly
from varde_toz.hook_input.scoped import is_scoped
from varde_toz.project import project_root, store_db_path
from varde_toz.store import Store


def _hook_config(tmp_path, monkeypatch, text):
    config = tmp_path / "config"
    store = tmp_path / "toz"
    for directory in (config, store):
        directory.mkdir(exist_ok=True)
        (directory / "config.toml").write_text(text)
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(store))


def _run_post_tool_use(
    tmp_path,
    monkeypatch,
    capsysbinary,
    payload,
    harness="claude",
    threshold: int | None = 4096,
):
    threshold_config = (
        f"threshold={threshold}\n[thresholds]\nread={threshold}\n"
        if threshold is not None
        else "[thresholds]\nread=4096\n"
    )
    _hook_config(
        tmp_path,
        monkeypatch,
        threshold_config + '[hooks.post_tool_use]\nproviders=["capture"]\n',
    )
    raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(buffer=io.BytesIO(raw)))
    assert hook.main(["post-tool-use", "--harness", harness]) == 0
    return capsysbinary.readouterr().out


def test_read_threshold_defaults_to_inline_cap_and_honors_override(monkeypatch):
    monkeypatch.delenv("TOZ_THRESHOLD", raising=False)
    assert hook._threshold_for("Read", {}, {"threshold": 4096}) == 64 * 1024
    assert (
        hook._threshold_for("Bash", {"command": "cat f"}, {"threshold": 4096})
        == 64 * 1024
    )
    assert hook.effective_thresholds({"threshold": 4096}) == (4096, 64 * 1024, 4096)
    assert hook.effective_thresholds({}) == (8 * 1024, 64 * 1024, 4096)
    assert (
        hook._threshold_for("Bash", {"command": "pytest -q"}, {"threshold": 5000})
        == 5000
    )
    overridden = {"threshold": 5000, "thresholds": {"bash": 100}}
    assert hook.effective_thresholds(overridden)[0] == 100
    assert hook._threshold_for("bash", {"command": "make | tee x"}, overridden) == 100
    assert (
        hook._threshold_for(
            "Read", {}, {"threshold": 4096, "thresholds": {"read": 123}}
        )
        == 123
    )


def test_query_output_is_not_recaptured_even_when_large(
    tmp_path, monkeypatch, capsysbinary
):
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "varde run query --handle H --chunk 1"},
        "tool_response": {"stdout": "x" * (70 * 1024), "stderr": ""},
    }
    assert (
        _run_post_tool_use(tmp_path, monkeypatch, capsysbinary, payload, threshold=4)
        == b""
    )


def test_plain_pytest_output_under_shell_default_is_not_captured(
    tmp_path, monkeypatch, capsysbinary
):
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "pytest -q"},
        "tool_response": {"stdout": "x" * (6 * 1024), "stderr": ""},
    }
    assert (
        _run_post_tool_use(tmp_path, monkeypatch, capsysbinary, payload, threshold=None)
        == b""
    )


def test_cwd_noise_removes_only_reset_lines_and_preserves_carriers():
    assert strip("\nShell cwd was reset to /tmp/project") == ""
    assert strip("Shell cwd was reset to /tmp/reset-dir") == ""
    source = "build output ok\nShell cwd was reset to /tmp\nwarning: unused x\n"
    assert strip(source) == "build output ok\nwarning: unused x\n"
    assert strip("first\r\nShell cwd was reset to /tmp\r\nsecond") == "first\r\nsecond"
    assert (
        strip("echo Shell cwd was reset to /tmp") == "echo Shell cwd was reset to /tmp"
    )
    assert strip("no noise here\n\n") == "no noise here\n\n"
    assert strip("\n\n") == "\n\n"


def test_compound_headings_split_top_level_shell_operators_only():
    assert heading("git status") is None
    assert heading("a && b || c ; d\ne") == "commands: 1) a 2) b 3) c 4) d 5) e"
    assert (
        heading("echo 'a && b' && echo \"c; d\"")
        == "commands: 1) echo 'a && b' 2) echo \"c; d\""
    )
    assert (
        heading("echo $(a; b) && echo `c; d` && (e; f)")
        == "commands: 1) echo $(a; b) 2) echo `c; d` 3) (e; f)"
    )
    assert (
        heading("echo \"$(grep 'x; y' f)\" && b")
        == "commands: 1) echo \"$(grep 'x; y' f)\" 2) b"
    )
    assert (
        heading("a; b; c; d; e; f; g") == "commands: 1) a 2) b 3) c 4) d 5) e +2 more"
    )
    assert heading("echo a\\;b && c") == "commands: 1) echo a\\;b 2) c"
    assert heading("a;;b;\n") == "commands: 1) a 2) b"
    assert heading('echo "a\nb" && c') == 'commands: 1) echo "a b" 2) c'
    assert heading("x" * 80 + " && b") == "commands: 1) " + "x" * 59 + "… 2) b"


def test_scoped_commands_are_conservative_and_use_the_final_stage():
    for command in (
        "head -40",
        "tail -5",
        "grep x f",
        "rg pattern",
        "wc -l",
        "cut -d: -f1",
        "awk '{print $1}'",
        "/usr/bin/head -40",
        "cat f | head -40",
        "cat f | grep x",
        "git log -n 5",
        "git log -5",
        "git log --max-count=5",
        "cat f | sed -n '1,40p'",
        "echo start; cat f | head",
        "grep 'a|b' f",
        'grep "a;b" f | head',
    ):
        assert is_scoped(command), command
    for command in (
        "cat f",
        "cargo build",
        "echo hi",
        "sed 's/a/b/' f",
        "ls -l",
        "head -40 | cat",
        "",
        "   ",
        "cat -n bigfile",
        "ls -n",
        "journalctl -n 50",
        "mkdir -m 755 d",
        "echo $(date) | head",
        "echo `date` | head",
        "cat f > out | head",
        "head < f",
        "grep 'unclosed | head",
        "head -40 &",
    ):
        assert not is_scoped(command), command


def test_readonly_classifier_accepts_reads_and_fails_open_on_writes():
    for command in (
        "grep -n x f | sed -n '1,40p'",
        "for f in a b; do sed -n '1,40p' \"$f\"; done",
        "git diff --stat; cat f",
        "cat a b",
        "cat f 2>&1",
        "cd /tmp && cat f",
        "git -C /tmp show HEAD",
        "cat a",
        "head -5 a",
        "tail -5 a",
        "nl a",
        "sed -n '1p' a",
        "sed -n 's/a/b/p' a",
        "grep x a",
        "rg x",
        "ls -la",
        "wc -l a",
        "find . -name '*.rs'",
        "git show HEAD",
        "git diff",
        "git log --oneline",
        "git status",
    ):
        assert is_readonly(command), command
    for command in (
        "rm x",
        "cargo build",
        "cat f > out",
        "cat f >> out",
        "cat $(ls)",
        "cat `ls`",
        "cat f &",
        'for f in *; do rm "$f"; done',
        "cat f | tee out",
        "git diff --output=out",
        "sed -i 's/a/b/' f",
        "sed -n --in-place 's/a/b/p' f",
        "sed -n 'w out' f",
        "sed -n '1,5w out' f",
        "sed -n 's/a/b/w out' f",
        "find . -exec rm {} ;",
        "find . -delete",
        "while rm x; do cat y; done",
    ):
        assert not is_readonly(command), command


def test_scoped_small_output_passes_through_unless_redaction_changes_it(
    tmp_path, monkeypatch, capsysbinary
):
    command = "cat f | head -5"
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": {"stdout": "plain output\n", "stderr": ""},
    }
    assert _run_post_tool_use(tmp_path, monkeypatch, capsysbinary, payload) == b""

    token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"  # noqa: S105 - Fake credential exercises secret redaction.
    payload["tool_response"]["stdout"] = token + "\n"
    result = json.loads(
        _run_post_tool_use(tmp_path, monkeypatch, capsysbinary, payload)
    )
    rendered = result["hookSpecificOutput"]["updatedToolOutput"]["stdout"]
    assert token not in rendered
    assert "[redacted:github]" in rendered
    assert (
        "redacted 1 pattern: github"
        in result["hookSpecificOutput"]["additionalContext"]
    )


def test_small_shell_rewrite_removes_cwd_noise_and_redacts_both_streams(
    tmp_path, monkeypatch, capsysbinary
):
    token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"  # noqa: S105 - Fake credential exercises secret redaction.
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "cat f"},
        "tool_response": {
            "stdout": "ok\n",
            "stderr": f"warning: {token}\nShell cwd was reset to /tmp/w",
        },
    }
    result = json.loads(
        _run_post_tool_use(tmp_path, monkeypatch, capsysbinary, payload)
    )
    replacement = result["hookSpecificOutput"]["updatedToolOutput"]
    assert replacement["stdout"] == "ok\n"
    assert replacement["stderr"] == "warning: [redacted:github]\n"
    assert "Shell cwd was reset" not in replacement["stderr"]


def test_content_block_replacement_redacts_without_shell_noise_or_heading(
    tmp_path, monkeypatch, capsysbinary
):
    token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"  # noqa: S105 - Fake credential exercises secret redaction.
    payload = {
        "tool_name": "WebFetch",
        "tool_input": {"url": "https://x.test/a?b=1;c=2"},
        "tool_response": [
            {"type": "text", "text": f"{token}\nShell cwd was reset to /tmp/w\n"}
        ],
    }
    result = json.loads(
        _run_post_tool_use(tmp_path, monkeypatch, capsysbinary, payload)
    )
    text = result["hookSpecificOutput"]["updatedMCPToolOutput"][0]["text"]
    assert "[redacted:github]" in text
    assert "Shell cwd was reset" in text
    assert "commands:" not in text


def test_structured_content_replacement_redacts_the_content_and_value(
    tmp_path, monkeypatch, capsysbinary
):
    token = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"  # noqa: S105 - Fake credential exercises secret redaction.
    payload = {
        "tool_name": "StructuredTool",
        "tool_input": {},
        "tool_response": {
            "content": [{"type": "text", "text": f"see {token}"}],
            "structuredContent": {"tok": token},
        },
    }
    result = json.loads(
        _run_post_tool_use(tmp_path, monkeypatch, capsysbinary, payload)
    )
    updated = result["hookSpecificOutput"]["updatedToolOutput"]
    assert token not in json.dumps(updated)
    assert updated["structuredContent"]["tok"] == "[redacted:github]"
    assert "[redacted:github]" in updated["content"][0]["text"]


def test_toz_only_shell_commands_are_not_captured(tmp_path, monkeypatch, capsysbinary):
    accepted = (
        "varde run run --script -",
        "varde capture --hook",
        "varde note --harness pi",
        "varde event --tool shell",
        "env MODE=1 varde run query",
        "command -p varde note",
        "toz capture",
        "varde run query && toz capture",
        "toz capture && " * 1000 + "toz note",
    )
    rejected = (
        "",
        "varde run query | cat",
        "varde run query >out",
        "echo $HOME",
        "echo $(pwd)",
        "echo hi # comment",
        "varde run query &&",
        "env -i varde run query",
        "cd relative && varde run query",
        "cd /tmp && make",
        "'NAME'=value varde run query",
        "varde run query && make",
        "echo varde run query",
    )

    def captured(command):
        payload = {
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "tool_response": {"stdout": "x" * 100, "stderr": ""},
        }
        output = _run_post_tool_use(
            tmp_path, monkeypatch, capsysbinary, payload, threshold=4
        )
        return output != b""

    for command in accepted:
        assert not captured(command), command
    for command in rejected:
        assert captured(command), command


def test_hook_records_outcomes_best_effort(tmp_path, monkeypatch, capsysbinary):
    assert (
        _run_post_tool_use(tmp_path, monkeypatch, capsysbinary, b"not json", "claude")
        == b""
    )
    assert (
        _run_post_tool_use(
            tmp_path,
            monkeypatch,
            capsysbinary,
            {"tool_name": "Read", "tool_response": {}},
            "codex",
        )
        == b""
    )
    assert _run_post_tool_use(tmp_path, monkeypatch, capsysbinary, [], "pi") == b""
    events = [
        json.loads(line)
        for line in (tmp_path / "toz" / "diagnostics.jsonl").read_text().splitlines()
    ]
    assert [(row["harness"], row["outcome"], row["reason"]) for row in events] == [
        ("claude-code", "failed", "invalid-payload"),
        ("codex", "skipped", "unsupported-shape"),
        ("pi", "skipped", "unsupported-shape"),
    ]
    assert all("stdout" not in row and "payload" not in row for row in events)


def test_hook_diagnostics_failure_does_not_break_hook(
    tmp_path, monkeypatch, capsysbinary
):
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")
    _hook_config(
        tmp_path,
        monkeypatch,
        'threshold=1\n[hooks.post_tool_use]\nproviders=["capture"]\n',
    )
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(blocked))
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": "make"},
        "tool_response": {"stdout": "x" * 100, "stderr": ""},
    }
    monkeypatch.setattr(
        sys, "stdin", SimpleNamespace(buffer=io.BytesIO(json.dumps(payload).encode()))
    )
    assert hook.main(["post-tool-use", "--harness", "claude"]) == 0
    assert capsysbinary.readouterr().out == b""


def test_capture_session_namespaces_harnesses_and_honors_override(
    tmp_path, monkeypatch, capsysbinary
):
    def session(harness, session_id):
        payload = {
            "session_id": session_id,
            "tool_name": "Bash",
            "tool_input": {"command": "make"},
            "tool_response": {"stdout": "x" * 100, "stderr": ""},
        }
        _run_post_tool_use(
            tmp_path, monkeypatch, capsysbinary, payload, harness, threshold=4
        )
        store_path = store_db_path(project_root(), tmp_path / "toz")
        with Store.open_readonly(store_path) as store:
            return store.list(1, False)[0]["session"]

    monkeypatch.delenv("VARDE_TOZ_SESSION", raising=False)
    monkeypatch.delenv("TOZ_SESSION", raising=False)
    assert session("claude", "same-session") == "claude-code-same-session"
    assert session("codex", "same-session") == "codex-same-session"
    monkeypatch.setenv("TOZ_SESSION", "legacy-session")
    assert session("claude", "same-session") == "legacy-session"
    monkeypatch.setenv("VARDE_TOZ_SESSION", "canonical-session")
    assert session("claude", "same-session") == "canonical-session"


def test_reversed_managed_markers_do_not_suppress_session_note(
    tmp_path, monkeypatch, capsys
):
    start, end = "<!-- varde-toz:start -->", "<!-- varde-toz:end -->"
    reversed_target = tmp_path / "instructions.md"
    reversed_target.write_text(f"{end}\n{start}\n")
    _hook_config(
        tmp_path,
        monkeypatch,
        f'[hooks.session_start]\nproviders=["toz_note"]\n'
        f'[instructions]\ntargets=["{reversed_target}"]\n',
    )
    assert hook.main(["session-start", "--harness", "codex"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["hookSpecificOutput"]["additionalContext"]

    managed_target = tmp_path / "managed.md"
    managed_target.write_text(f"{start}\nmanaged\n{end}\n")
    _hook_config(
        tmp_path,
        monkeypatch,
        f'[hooks.session_start]\nproviders=["toz_note"]\n'
        f'[instructions]\ntargets=["{managed_target}"]\n',
    )
    assert hook.main(["session-start", "--harness", "codex"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["hookSpecificOutput"]["additionalContext"] == ""


def test_diagnostics_fall_back_and_note_reads_fallback(tmp_path, monkeypatch, capsys):
    primary = tmp_path / "primary"
    primary.write_text("not a directory")
    fallback = tmp_path / "fallback"
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(primary))
    monkeypatch.setenv("TOZ_FALLBACK_DIR", str(fallback))
    assert (
        event_note.main(
            [
                "event",
                "--harness",
                "codex",
                "--outcome",
                "failed",
                "--reason",
                "timeout",
                "--tool",
                "Bash",
                "--bytes",
                "42",
            ]
        )
        == 0
    )
    events = [
        json.loads(line)
        for line in (fallback / "diagnostics.jsonl").read_text().splitlines()
    ]
    assert [(row["outcome"], row["reason"]) for row in events] == [
        ("failed", "timeout")
    ]
    assert event_note.main(["note", "--harness", "codex"]) == 0
    note = json.loads(capsys.readouterr().out)["hookSpecificOutput"][
        "additionalContext"
    ]
    assert "Toz recorded 1 hook failure(s)" in note


def test_diagnostics_files_are_private(tmp_path, monkeypatch):
    monkeypatch.setenv("VARDE_TOZ_CONFIG_DIR", str(tmp_path))
    assert (
        event_note.main(
            [
                "event",
                "--harness",
                "codex",
                "--outcome",
                "captured",
                "--reason",
                "stored",
                "--tool",
                "Bash",
                "--bytes",
                "42",
            ]
        )
        == 0
    )
    for name in ("diagnostics.lock", "diagnostics.jsonl"):
        assert stat.S_IMODE((tmp_path / name).stat().st_mode) == 0o600


def _media_payload(tool, response):
    return {"tool_name": tool, "tool_input": {}, "tool_response": response}


def _media_responses(size):
    data = "A" * size
    return {
        "read-image": {
            "type": "image",
            "file": {"base64": data, "type": "image/jpeg", "originalSize": size},
        },
        "mcp-list": [{"type": "image", "data": data, "mimeType": "image/png"}],
        "mcp-mixed": [
            {"type": "text", "text": "t" * size},
            {"type": "image", "data": data, "mimeType": "image/png"},
        ],
        "mcp-content-field": {
            "content": [{"type": "image", "data": data, "mimeType": "image/png"}]
        },
        "base64-source": {
            "content": [{"type": "x", "source": {"type": "base64", "data": data}}]
        },
        "pdf": {"file": {"type": "application/pdf", "data": data}},
    }


def test_hook_never_rewrites_binary_media(tmp_path, monkeypatch, capsysbinary):
    for size in (1024, 100 * 1024):
        for name, response in _media_responses(size).items():
            tool = "Read" if name == "read-image" else "mcp__x__shot"
            out = _run_post_tool_use(
                tmp_path,
                monkeypatch,
                capsysbinary,
                _media_payload(tool, response),
            )
            assert out == b"", (name, size)
    events = [
        json.loads(line)
        for line in (tmp_path / "toz" / "diagnostics.jsonl").read_text().splitlines()
    ]
    assert len(events) == 12
    assert {(e["outcome"], e["reason"]) for e in events} == {
        ("skipped", "binary-media")
    }


def test_hook_still_captures_large_text(tmp_path, monkeypatch, capsysbinary):
    out = _run_post_tool_use(
        tmp_path,
        monkeypatch,
        capsysbinary,
        _media_payload("Read", {"type": "text", "file": {"content": "x\n" * 50000}}),
    )
    assert b"captured" in out
