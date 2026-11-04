"""AST edit behavior checks."""

from __future__ import annotations

import json
from pathlib import Path

from varde_code.ast_edit import Options, run


def test_cli_preview_and_apply_rename_identifiers(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "main.ts"
    original = "const total = 1;\nconsole.log(total);\n"
    source.write_text(original, encoding="utf-8")
    monkeypatch.chdir(repo)
    options = Options(repo, tmp_path / "store")
    code = run(
        [
            "preview",
            "--language",
            "typescript",
            "--pattern",
            "total",
            "--replacement",
            "sum",
            "--path",
            "main.ts",
            "--json",
        ],
        None,
        options,
    )
    result = json.loads(capsys.readouterr().out)
    assert code == 0
    assert result["data"]["files"][0]["replacement_count"] == 2
    assert source.read_text(encoding="utf-8") == original
    proposal = tmp_path / "store" / f"{result['data']['proposal_id']}.json"
    assert run(["apply", "--proposal", str(proposal)], None, options) == 0
    changed = source.read_text(encoding="utf-8")
    assert "const sum = 1;" in changed
    assert "console.log(sum);" in changed
    assert "total" not in changed


def test_cli_preview_without_match_leaves_file_unchanged(
    tmp_path: Path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.ts").write_text("const value = 1;\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    run(
        [
            "preview",
            "--language",
            "typescript",
            "--pattern",
            "missing",
            "--replacement",
            "found",
            "--path",
            "main.ts",
        ],
        None,
        Options(repo, tmp_path / "store"),
    )
    # KNOWN OPEN BUG: the exit code for an unmatched pattern is 0, so callers cannot
    # tell "edited" from "nothing matched". Deliberately not asserted; see plan notes
    # (follow-ups.md) for the pending decision.
    assert (repo / "main.ts").read_text(encoding="utf-8") == "const value = 1;\n"


def test_apply_rejects_source_changed_since_preview(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    source = repo / "main.ts"
    source.write_text("const total = 1;\n", encoding="utf-8")
    monkeypatch.chdir(repo)
    options = Options(repo, tmp_path / "store")
    assert (
        run(
            [
                "preview",
                "--language",
                "typescript",
                "--pattern",
                "total",
                "--replacement",
                "sum",
                "--path",
                "main.ts",
                "--json",
            ],
            None,
            options,
        )
        == 0
    )
    preview = json.loads(capsys.readouterr().out)
    proposal = tmp_path / "store" / f"{preview['data']['proposal_id']}.json"

    source.write_text("const total = 2;\n", encoding="utf-8")
    assert run(["apply", "--proposal", str(proposal), "--json"], None, options) == 1
    applied = json.loads(capsys.readouterr().out)

    assert (
        applied["data"]["error"]["message"]
        == "original snapshot identity changed for main.ts"
    )
    assert source.read_text(encoding="utf-8") == "const total = 2;\n"
