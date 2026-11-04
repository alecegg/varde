import json

from varde_code.cli_extract import run


def test_extract_file_reports_symbol_and_success(tmp_path, capsys):
    source = tmp_path / "a.py"
    source.write_text("def f(): pass\n")
    assert run(["extract", str(source)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["ok"] is True
    assert any(symbol["name"] == "f" for symbol in result["data"]["symbols"])


def test_missing_extract_path_fails(tmp_path, capsys):
    assert run(["extract", str(tmp_path / "missing.py")]) != 0
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_extract_directory_sorts_files_and_skips_git_metadata(tmp_path, capsys):
    root = tmp_path / "src"
    (root / ".git").mkdir(parents=True)
    (root / "z.py").write_text("def zed(): pass\n")
    (root / "a.py").write_text("def alpha(): pass\n")
    (root / ".git" / "ignored.py").write_text("def ignored(): pass\n")

    assert run(["extract", str(root)]) == 0
    result = json.loads(capsys.readouterr().out)

    assert result["data"]["files"] == ["src/a.py", "src/z.py"]


def test_extract_reports_kept_symbols_after_syntax_error(tmp_path, capsys):
    source = tmp_path / "broken.py"
    source.write_text("def kept():\n    pass\n\ndef broken(:\n    pass\n")

    assert run(["extract", str(source)]) == 0
    result = json.loads(capsys.readouterr().out)

    assert any(symbol["name"] == "kept" for symbol in result["data"]["symbols"])
    assert (
        result["data"]["diagnostics"][0]["message"]
        == "syntax error — partial extract kept"
    )
