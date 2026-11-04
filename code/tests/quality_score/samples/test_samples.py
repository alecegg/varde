from pathlib import Path

import pytest
from varde_code.quality_score.calibration import load_calibration
from varde_code.quality_score.samples import (
    component_diff,
    component_vector,
    load_sample,
)

FIXTURES = Path(__file__).parent / "fixtures"
CALIBRATION = (
    Path(__file__).parents[3]
    / "src/varde_code/quality_score/calibration/placeholder.toml"
)


def test_shipped_sample_and_user_target_override(tmp_path, monkeypatch):
    sample = load_sample("tiny-python", package_root=FIXTURES, config_dir=tmp_path)
    assert sample.target.read_text() == sample.versions["smoothed"].read_text()

    user_target = tmp_path / "quality/samples/tiny-python/target.py"
    user_target.parent.mkdir(parents=True)
    user_target.write_text("def useful_name():\n    return 2\n")
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(tmp_path))
    edited = load_sample("tiny-python", package_root=FIXTURES)
    assert edited.target == user_target
    assert edited.user_target
    assert edited.versions["smoothed"].read_text() != edited.target.read_text()


def test_tampered_sample_file_fails_hash_verification(tmp_path):
    sample_dir = tmp_path / "tiny-python"
    sample_dir.mkdir()
    source_dir = FIXTURES / "tiny-python"
    for path in source_dir.iterdir():
        (sample_dir / path.name).write_bytes(path.read_bytes())
    (sample_dir / "original.py").write_text("tampered\n")
    with pytest.raises(ValueError, match="hash"):
        load_sample(
            "tiny-python", package_root=tmp_path, config_dir=tmp_path / "config"
        )


def test_var_config_dir_redirects_user_layer(tmp_path, monkeypatch):
    config = tmp_path / "custom-config"
    monkeypatch.setenv("VARDE_CONFIG_DIR", str(config))
    sample = load_sample("tiny-python", package_root=FIXTURES)
    assert sample.target == sample.versions["smoothed"]
    target = config / "quality/samples/tiny-python/target.py"
    target.parent.mkdir(parents=True)
    target.write_text("def redirected():\n    return 3\n")
    assert load_sample("tiny-python", package_root=FIXTURES).target == target


def test_component_vectors_are_deterministic_and_diff_self_is_zero():
    calibration = load_calibration(CALIBRATION)
    source = FIXTURES / "tiny-python/original.py"
    first = component_vector(source, calibration)
    second = component_vector(source, calibration)
    assert first == second
    assert set(component_diff(first, second)) == set(first)
    assert set(component_diff(first, second).values()) == {0}


def test_module_startup_does_not_import_sample_loader():
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import varde_code.module; "
                "assert not any(name.startswith('varde_code.quality_score.samples') "
                "for name in sys.modules)"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
