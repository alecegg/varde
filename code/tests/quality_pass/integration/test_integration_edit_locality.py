"""One-file edits recompute exactly the edited file and its declared inputs.

Three edit shapes are pinned with exact recomputed sets from the summary
counters, and every warm store is compared with a no-cache recompute:

* reverse closure: editing a helper body keeps its function ids, so its own
  edges recompute and only its caller's measures follow via the callee's Merkle
  fingerprint;
* leaf: editing a file with no dependents recomputes that file alone;
* id change: adding a same-named sibling moves the helper's function id set, so
  the importer's resolution digest changes and its edges recompute too.
"""

from __future__ import annotations

import pytest
from integration_support import (
    ID_CHANGE_EDIT,
    LEAF_EDIT,
    REVERSE_CLOSURE_CASES,
    REVERSE_CLOSURE_IDS,
    SEVEN_LANGUAGE_FILES,
    SEVEN_LANGUAGE_REPO,
    build_index,
    prepare_env,
    refresh_index,
    snapshot,
    write_repo,
)
from varde_code.quality_pass.pass_ import run_quality_pass

FILE_COUNT = len(SEVEN_LANGUAGE_FILES)


def _cold_then_edit(tmp_path, monkeypatch, target: str, text: str):
    root = prepare_env(monkeypatch, tmp_path)
    write_repo(root, SEVEN_LANGUAGE_REPO)
    build_index(root)
    cold = run_quality_pass(root, workers=1)
    assert cold.facts_recomputed == SEVEN_LANGUAGE_FILES
    assert cold.edges_recomputed == SEVEN_LANGUAGE_FILES
    assert cold.measures_recomputed == SEVEN_LANGUAGE_FILES
    assert cold.facts_reused == 0

    (root / target).write_text(text, encoding="utf-8")
    refresh_index(root)
    return root, run_quality_pass(root, workers=1)


@pytest.mark.parametrize(
    ("language", "helper", "caller", "edited_text"),
    REVERSE_CLOSURE_CASES,
    ids=REVERSE_CLOSURE_IDS,
)
def test_edit_with_reverse_closure_recomputes_the_caller(
    tmp_path, monkeypatch, language, helper, caller, edited_text
):
    del language
    root, warm = _cold_then_edit(tmp_path, monkeypatch, helper, edited_text)

    assert warm.facts_recomputed == (helper,)
    assert warm.edges_recomputed == (helper,)
    assert warm.measures_recomputed == tuple(sorted((caller, helper)))
    assert warm.facts_reused == FILE_COUNT - 1
    assert warm.measures_reused == FILE_COUNT - 2

    warm_snapshot = snapshot(root)
    run_quality_pass(root, workers=1, no_cache=True)
    assert snapshot(root) == warm_snapshot


def test_leaf_edit_without_dependents_recomputes_only_that_file(tmp_path, monkeypatch):
    target, text = LEAF_EDIT
    root, warm = _cold_then_edit(tmp_path, monkeypatch, target, text)

    assert warm.facts_recomputed == (target,)
    assert warm.edges_recomputed == (target,)
    assert warm.measures_recomputed == (target,)
    assert warm.facts_reused == FILE_COUNT - 1
    assert warm.measures_reused == FILE_COUNT - 1

    warm_snapshot = snapshot(root)
    run_quality_pass(root, workers=1, no_cache=True)
    assert snapshot(root) == warm_snapshot


def test_edit_that_changes_function_ids_recomputes_the_importer_edges(
    tmp_path, monkeypatch
):
    target, text = ID_CHANGE_EDIT
    root, warm = _cold_then_edit(tmp_path, monkeypatch, target, text)

    # The new same-named sibling moves the helper's id set (so the importer's
    # digest and edges change) and the module signature (so every file of the
    # module's measures change).
    assert warm.facts_recomputed == (target,)
    assert warm.edges_recomputed == ("pylib/app.py", target)
    assert warm.measures_recomputed == (
        "pylib/__init__.py",
        "pylib/app.py",
        "pylib/helper.py",
    )
    assert warm.facts_reused == FILE_COUNT - 1

    warm_snapshot = snapshot(root)
    run_quality_pass(root, workers=1, no_cache=True)
    assert snapshot(root) == warm_snapshot
