from pathlib import Path

import pytest
from varde_data.sweep_config import load_summary_config, load_sweep_repos


def test_defaults(tmp_path: Path) -> None:
    assert load_sweep_repos(tmp_path) is None
    assert load_summary_config(tmp_path) == (False, 2000)


def test_valid_config(tmp_path: Path) -> None:
    (tmp_path / "sweep.toml").write_text(
        'repos = ["~/source/a"]\n[summary]\nenabled = true\ntoken_cap = 40\n'
    )
    assert load_sweep_repos(tmp_path) == ("~/source/a",)
    assert load_summary_config(tmp_path) == (True, 40)


@pytest.mark.parametrize(
    ("contents", "error", "message"),
    [
        ('repos = "bad"', ValueError, "sweep config repos must be a list of paths"),
        (
            '[summary]\nenabled = "yes"',
            TypeError,
            "sweep summary enabled must be true or false",
        ),
        (
            "[summary]\ntoken_cap = 0",
            ValueError,
            "sweep summary token_cap must be a positive integer",
        ),
        ("summary = []", TypeError, "sweep summary config must be a table"),
    ],
)
def test_invalid_config(
    tmp_path: Path, contents: str, error: type[Exception], message: str
) -> None:
    (tmp_path / "sweep.toml").write_text(contents)
    with pytest.raises(error, match=message):
        if contents.startswith("repos"):
            load_sweep_repos(tmp_path)
        else:
            load_summary_config(tmp_path)


def test_bad_summary_does_not_break_repo_loading(tmp_path: Path) -> None:
    (tmp_path / "sweep.toml").write_text('repos = ["/repo"]\nsummary = []\n')
    assert load_sweep_repos(tmp_path) == ("/repo",)


def test_bad_repos_does_not_break_summary_loading(tmp_path: Path) -> None:
    (tmp_path / "sweep.toml").write_text('repos = "bad"\n[summary]\nenabled = true\n')
    assert load_summary_config(tmp_path) == (True, 2000)
