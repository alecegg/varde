"""A warm pass after an edit must equal a no-cache recompute of the same tree.

Each test edits a different resolution or measurement input and asserts that the
dependent records recompute, differ from the stale ones, and that the warm store
matches a from-scratch pass.
"""

from __future__ import annotations

from pass_support import (
    build_index,
    measures_by_path,
    prepare_env,
    refresh_index,
    snapshot,
    write_repo,
)
from varde_code.quality_pass.pass_ import run_quality_pass


def _warm_after_edit(tmp_path, monkeypatch, files, edit):
    root = prepare_env(monkeypatch, tmp_path)
    write_repo(root, files)
    build_index(root)
    run_quality_pass(root, workers=1)
    before = measures_by_path(root)
    edit(root)
    refresh_index(root)
    warm = run_quality_pass(root, workers=1)
    after = measures_by_path(root)
    warm_snapshot = snapshot(root)
    run_quality_pass(root, workers=1, no_cache=True)
    return {
        "root": root,
        "warm": warm,
        "before": before,
        "after": after,
        "warm_snapshot": warm_snapshot,
        "cold_snapshot": snapshot(root),
    }


def test_new_callee_name_elsewhere_invalidates_the_caller(tmp_path, monkeypatch):
    files = {
        "pkg/__init__.py": "",
        "pkg/a.py": "def f():\n    return helper()\n",
        "pkg/z.py": "def other():\n    return 1\n",
    }

    def edit(root):
        (root / "pkg/z.py").write_text(
            "def other():\n    return 1\n\n\ndef helper():\n    return 2\n",
            encoding="utf-8",
        )

    result = _warm_after_edit(tmp_path, monkeypatch, files, edit)

    assert "pkg/a.py" in result["warm"].edges_recomputed
    assert "pkg/a.py" in result["warm"].measures_recomputed
    assert result["after"]["pkg/a.py"] != result["before"]["pkg/a.py"]
    assert result["warm_snapshot"] == result["cold_snapshot"]


def test_extra_same_name_sibling_in_an_import_target_invalidates_the_importer(
    tmp_path, monkeypatch
):
    files = {
        "pkg/__init__.py": "",
        "pkg/a.py": "def f():\n    return 1\n",
        "pkg/b.py": "import pkg.a\n\n\ndef g():\n    return pkg.a.f()\n",
    }

    def edit(root):
        (root / "pkg/a.py").write_text(
            "def f():\n    return 1\n\n\nclass A:\n    def f(self):\n        return 2\n"
            "\n\nclass B:\n    def f(self):\n        return 3\n",
            encoding="utf-8",
        )

    result = _warm_after_edit(tmp_path, monkeypatch, files, edit)

    assert "pkg/b.py" in result["warm"].edges_recomputed
    assert "pkg/b.py" in result["warm"].measures_recomputed
    assert result["after"]["pkg/b.py"] == result["before"]["pkg/b.py"]
    assert result["warm_snapshot"] == result["cold_snapshot"]


def test_new_caller_invalidates_the_unchanged_callee(tmp_path, monkeypatch):
    files = {
        "pkg/__init__.py": "",
        "pkg/a.py": "def f():\n    return 1\n",
        "pkg/b.py": "def g():\n    return 2\n",
    }

    def edit(root):
        (root / "pkg/b.py").write_text(
            "import pkg.a\n\n\ndef g():\n    return pkg.a.f()\n", encoding="utf-8"
        )

    result = _warm_after_edit(tmp_path, monkeypatch, files, edit)

    assert "pkg/a.py" in result["warm"].measures_recomputed
    assert result["after"]["pkg/a.py"] != result["before"]["pkg/a.py"]
    assert result["warm_snapshot"] == result["cold_snapshot"]


def test_module_level_call_in_a_function_less_file_invalidates_its_measures(
    tmp_path, monkeypatch
):
    files = {
        "pkg/__init__.py": "",
        "pkg/a.py": "print(1)\n",
        "pkg/z.py": "def foo():\n    return 1\n\n\ndef bar():\n    return 2\n",
    }

    def edit(root):
        (root / "pkg/a.py").write_text("print(1)\nfoo()\nbar()\n", encoding="utf-8")

    result = _warm_after_edit(tmp_path, monkeypatch, files, edit)

    assert "pkg/a.py" in result["warm"].edges_recomputed
    assert "pkg/a.py" in result["warm"].measures_recomputed
    assert result["after"]["pkg/a.py"] != result["before"]["pkg/a.py"]
    assert result["warm_snapshot"] == result["cold_snapshot"]


def test_new_package_marker_moves_module_membership_and_invalidates(
    tmp_path, monkeypatch
):
    files = {
        "pkg/__init__.py": "",
        "pkg/main.py": "def run():\n    return 1\n",
        "pkg/sub/x.py": "def helper():\n    return 2\n",
    }

    def edit(root):
        (root / "pkg/sub/__init__.py").write_text("", encoding="utf-8")

    result = _warm_after_edit(tmp_path, monkeypatch, files, edit)

    assert "pkg/sub/x.py" in result["warm"].measures_recomputed
    assert result["after"]["pkg/sub/x.py"] != result["before"]["pkg/sub/x.py"]
    assert result["warm_snapshot"] == result["cold_snapshot"]
