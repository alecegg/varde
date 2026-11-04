"""Tests for building one-version items from seeded-judge samples."""

from pathlib import Path

import item_targets
import pytest
import sample_item

FIXTURES = Path(__file__).parent / "fixtures" / "sample_items"
EXTENSIONS = {
    "python": ".py",
    "typescript": ".ts",
    "go": ".go",
    "java": ".java",
    "csharp": ".cs",
}


@pytest.mark.parametrize("language,extension", EXTENSIONS.items())
def test_sample_build_creates_parseable_layered_item(tmp_path, language, extension):
    source = FIXTURES / language
    output = tmp_path / "item"

    sample_item.build_sample_item(source, output)

    assert (output / f"sensible{extension}").read_bytes() == (
        source / f"smoothed{extension}"
    ).read_bytes()
    assert (output / f"behaviour_test{extension}").is_file()
    assert (output / "spec-profile.toml").read_text() == 'profile = "layered"\n'
    report = item_targets.build_report(output)
    assert report["language"] == language
    assert report["profile"] == "layered"
    assert "error" not in report["variants"]["sensible"]


def test_sample_build_copies_language_metadata_and_is_repeatable(tmp_path):
    source = FIXTURES / "go"
    output = tmp_path / "go-item"

    sample_item.build_sample_item(source, output)
    first = {path.name: path.read_bytes() for path in output.iterdir()}
    sample_item.build_sample_item(source, output)

    assert {path.name: path.read_bytes() for path in output.iterdir()} == first
    assert (output / "go.mod").read_bytes() == (source / "go.mod").read_bytes()


@pytest.mark.parametrize(
    "language,filename", [("go", "go.mod"), ("csharp", "qssample.csproj")]
)
def test_sample_build_copies_optional_project_metadata(tmp_path, language, filename):
    source = FIXTURES / language
    output = tmp_path / "item"

    sample_item.build_sample_item(source, output)

    assert (output / filename).read_bytes() == (source / filename).read_bytes()


def test_unknown_sample_language_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="unsupported sample language"):
        sample_item.build_sample_item(tmp_path, tmp_path / "item")


def test_build_does_not_copy_judge_or_original_files(tmp_path):
    source = FIXTURES / "python"
    sample = tmp_path / "python"
    sample.mkdir()
    for name in ("smoothed.py", "behaviour_test.py"):
        (sample / name).write_bytes((source / name).read_bytes())
    (sample / "original.py").write_text("sentinel")
    (sample / "judge-original.py").write_text("sentinel")
    output = tmp_path / "item"

    sample_item.build_sample_item(sample, output)

    assert not (output / "original.py").exists()
    assert not list(output.glob("judge-*"))
