import importlib.util
import shutil
from pathlib import Path

import pytest

TOOL = Path(__file__).with_name("land_sample.py")
FIXTURE = Path(__file__).parent / "tests/fixtures/sample"
SPEC = importlib.util.spec_from_file_location("land_sample", TOOL)
assert SPEC is not None and SPEC.loader is not None  # noqa: S101 - validates the test module loader.
land_sample_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(land_sample_module)


def test_landing_is_deterministic_and_writes_loadable_manifest(tmp_path):
    from varde_code.quality_score.samples import load_sample

    source = tmp_path / "source"
    shutil.copytree(FIXTURE, source, ignore=shutil.ignore_patterns("__pycache__"))
    sample_id = land_sample_module.land_sample(source, tmp_path)
    sample = load_sample(sample_id, package_root=tmp_path, config_dir=tmp_path)
    assert sample_id.startswith("s") and len(sample_id) == 9  # noqa: S101 - pytest assertion.
    assert sample.language == "python"  # noqa: S101 - pytest assertion.
    assert sample.task == "Keep the returned value stable."  # noqa: S101 - pytest assertion.
    assert sample.authored_by == land_sample_module.AUTHORED_BY  # noqa: S101 - pytest assertion.
    assert sample.biases == tuple(land_sample_module.JUDGES.values())  # noqa: S101 - pytest assertion.
    assert set(sample.versions) == {  # noqa: S101 - pytest assertion.
        "original",
        "smoothed",
        "judge-extract",
        "judge-inline",
        "judge-names",
        "judge-defensive",
        "judge-classes",
    }
    assert (  # noqa: S101 - pytest assertion.
        land_sample_module._metadata(
            sample.language,
            sample.task,
            {path.name: path.read_bytes() for path in sample.versions.values()}
            | {
                "behaviour_test.py": (
                    tmp_path / sample_id / "behaviour_test.py"
                ).read_bytes(),
                "task.md": (tmp_path / sample_id / "task.md").read_bytes(),
                "smoothing.md": (tmp_path / sample_id / "smoothing.md").read_bytes(),
            },
        )
        == (tmp_path / sample_id / "sample.toml").read_text()
    )


@pytest.mark.parametrize("name", ["bin", "obj", "__pycache__"])
def test_landing_refuses_generated_directories(tmp_path, name):
    source = tmp_path / "source"
    source.mkdir()
    (source / name).mkdir()
    with pytest.raises(ValueError, match="generated directories"):
        land_sample_module.land_sample(source, tmp_path / "out")
