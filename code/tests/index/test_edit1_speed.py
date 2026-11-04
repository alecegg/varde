from __future__ import annotations

from pathlib import Path

from varde_code.index import churn


def test_batch_churn_skips_git_when_no_repository_context(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "src/main.py"
    source.parent.mkdir()
    source.write_text("print('hello')\n", encoding="utf-8")

    def unexpected_git_call(*args, **kwargs):
        raise AssertionError("Git should not be invoked outside a repository")

    monkeypatch.setattr(churn, "run_git", unexpected_git_call)

    assert churn.commit_counts_batch([str(source)], tmp_path) == {str(source): 0}
