import json
import subprocess
import sys
from io import StringIO
from pathlib import Path

from varde_code.quality_score import samples_cli
from varde_code.quality_score.samples import load_sample
from varde_code.quality_score.samples_cli import run

FIXTURES = Path(__file__).parents[1] / "samples/fixtures"
CALIBRATION = (
    Path(__file__).parents[3] / "src/varde_code/quality_score/calibration/cal-1.toml"
)


class _IO:
    def __init__(self):
        self.stdout = StringIO()
        self.stderr = StringIO()


def test_sample_ids_skips_directories_without_sample_metadata(tmp_path, monkeypatch):
    (tmp_path / "tiny-python").mkdir()
    (tmp_path / "tiny-python" / "sample.toml").touch()
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "_internal").mkdir()
    (tmp_path / "_internal" / "sample.toml").touch()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / ".hidden" / "sample.toml").touch()
    monkeypatch.setattr(
        samples_cli.importlib.resources,
        "files",
        lambda package: tmp_path,
    )

    assert samples_cli._sample_ids() == ["tiny-python"]


def _invoke(monkeypatch, config, *argv):
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))
    monkeypatch.setattr(
        "varde_code.quality_score.samples_cli._sample_ids", lambda: ["tiny-python"]
    )
    monkeypatch.setattr(
        "varde_code.quality_score.samples_cli.load_sample",
        lambda sample_id: load_sample(sample_id, package_root=FIXTURES),
    )
    output = _IO()
    code = run(["samples", *argv], output)
    return code, output.stdout.getvalue(), output.stderr.getvalue()


def test_list_and_show_fixture_sample(tmp_path, monkeypatch):
    code, output, error = _invoke(monkeypatch, tmp_path, "list")
    assert code == 0, error
    assert "tiny-python\tpython" in output

    code, output, error = _invoke(
        monkeypatch, tmp_path, "show", "tiny-python", "--version", "original"
    )
    assert code == 0, error
    assert "def" in output

    code, output, error = _invoke(
        monkeypatch, tmp_path, "show", "tiny-python", "--diff", "original", "smoothed"
    )
    assert code == 0, error
    assert "--- original" in output


def test_empty_shipped_set_is_clear_and_json_is_empty(monkeypatch):
    monkeypatch.setattr("varde_code.quality_score.samples_cli._sample_ids", list)
    output = _IO()
    assert run(["samples", "list"], output) == 0
    assert "No quality samples are currently shipped" in output.stdout.getvalue()
    output = _IO()
    assert run(["samples", "list", "--json"], output) == 0
    assert json.loads(output.stdout.getvalue()) == []


def test_save_show_reset_and_unparseable_refusal(tmp_path, monkeypatch):
    config = tmp_path / "config"
    valid = tmp_path / "edited.py"
    valid.write_text("def useful_name():\n    return 4\n", encoding="utf-8")
    code, output, error = _invoke(
        monkeypatch, config, "save", "tiny-python", "--from", str(valid)
    )
    assert code == 0, error
    assert "behaviour test was not run" in output
    assert (
        config / "quality/samples/tiny-python/target.py"
    ).read_text() == valid.read_text()

    code, output, error = _invoke(
        monkeypatch, config, "show", "tiny-python", "--version", "mine"
    )
    assert code == 0, error
    assert "useful_name" in output
    code, _, error = _invoke(monkeypatch, config, "reset", "tiny-python")
    assert code == 0, error
    assert not (config / "quality/samples/tiny-python/target.py").exists()

    invalid = tmp_path / "invalid.py"
    invalid.write_text("def broken(:\n", encoding="utf-8")
    code, output, error = _invoke(
        monkeypatch, config, "save", "tiny-python", "--from", str(invalid)
    )
    assert code == 2
    assert output == ""
    assert "could not be parsed into facts" in error
    assert not (config / "quality/samples/tiny-python/target.py").exists()


def test_recalibrate_dry_run_then_write_loadable_profile(tmp_path, monkeypatch):
    config = tmp_path / "config"
    target = config / "quality/samples/tiny-python/target.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        (FIXTURES / "tiny-python/original.py").read_text(), encoding="utf-8"
    )

    code, output, error = _invoke(monkeypatch, config, "recalibrate", "--dry-run")
    assert code == 0, error
    assert "not validated" in output
    assert "gaming-unchecked" in output
    assert "Component diff" in output
    profile_path = config / "quality/profile.toml"
    assert not profile_path.exists()

    code, output, error = _invoke(monkeypatch, config, "recalibrate", "--json")
    assert code == 0, error
    payload = json.loads(output)
    assert payload["label"] == "user-edited, gaming-unchecked"
    assert payload["validation"] == "not validated"
    assert profile_path.exists()

    facts = tmp_path / "facts.jsonl"
    facts.write_text(
        json.dumps(
            {
                "contract": "facts-2",
                "path": "a.py",
                "language": "python",
                "module": "src",
                "tokens": 1,
                "functions": [],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = subprocess.run(  # noqa: S603 - Runs the samples CLI with controlled fixture paths.
        [
            sys.executable,
            "-c",
            (
                "from varde_code.quality_score.cli import run; "
                "raise SystemExit(run(['score','--facts',"
                f"{str(facts)!r},'--calibration',{str(CALIBRATION)!r},'--debug',"
                f"'--profile',{str(profile_path)!r}]))"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
