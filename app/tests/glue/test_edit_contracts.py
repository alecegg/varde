import json
import subprocess
from pathlib import Path

from varde.glue import contracts, edit


def test_error_envelope_code_only_reads_failed_envelopes():
    assert (
        contracts.error_envelope_code(
            '{"ok":false,"data":{"error":{"code":"index_missing"}}}'
        )
        == "index_missing"
    )
    assert contracts.error_envelope_code('{"ok":false}') == "error"
    assert contracts.error_envelope_code('{"ok":true}') is None
    assert contracts.error_envelope_code("plain text") is None


def test_dependents_require_complete_string_list():
    assert contracts.dependents_from_envelope('{"ok":true,"data":["src/a.rs"]}') == [
        Path("src/a.rs")
    ]
    for text in (
        "broken",
        '{"ok":false,"data":[]}',
        '{"ok":true,"data":{"error":{}}}',
        '{"ok":true,"data":[1]}',
        '{"ok":true,"data":["src/a"],"meta":{"truncated":true}}',
    ):
        assert contracts.dependents_from_envelope(text) is None


def test_capture_defers_only_find_pattern_indexing():
    assert contracts.defers_index("find_pattern")
    assert not contracts.defers_index("blast_radius")


def _preview_edit(capsys) -> Path:
    data = json.loads(capsys.readouterr().out)["data"]
    return Path(data["proposal_path"])


def test_proposal_store_follows_builtin_and_configured_paths(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)  # noqa: S603,S607,RUF100 - Initializes a temporary Git fixture for this test.
    (repo / "sample.py").write_text("total = 1\n")
    config_dir = tmp_path / "config"
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config_dir))
    monkeypatch.delenv("VARDE_WORKING_DIR", raising=False)
    monkeypatch.chdir(repo)
    argv = [
        "preview",
        "--language",
        "python",
        "--pattern",
        "total",
        "--replacement",
        "sum",
        "--path",
        "sample.py",
        "--json",
    ]

    assert edit.run(argv) == 0
    assert _preview_edit(capsys).is_relative_to(config_dir / "ast-edit")

    monkeypatch.setenv("VARDE_WORKING_DIR", str(tmp_path / "work"))
    assert edit.run(argv) == 0
    assert _preview_edit(capsys).is_relative_to(tmp_path / "work" / "ast-edit")
