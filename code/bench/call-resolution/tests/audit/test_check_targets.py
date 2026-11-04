"""Behavior tests for the dev-target check."""

import json

import pytest
from audit.check_targets import check_targets, main


def _entry(precision, recall):
    return {"precision": precision, "natural_frequency_recall": recall}


def _passing():
    return {lang: _entry(0.97, 0.85) for lang in ("python", "typescript", "csharp")}


def test_all_languages_pass():
    assert check_targets(_passing()) == []


def test_boundary_values_pass():
    metrics = {lang: _entry(0.95, 0.80) for lang in ("python", "typescript", "csharp")}
    assert check_targets(metrics) == []


@pytest.mark.parametrize(
    ("language", "entry", "needle"),
    [
        ("python", _entry(0.94, 0.9), "python: precision"),
        ("typescript", _entry(0.99, 0.79), "typescript: recall"),
        ("csharp", _entry(None, 0.9), "csharp: precision"),
        ("csharp", _entry(0.99, None), "csharp: recall"),
    ],
)
def test_single_miss_is_reported(language, entry, needle):
    metrics = _passing()
    metrics[language] = entry
    failures = check_targets(metrics)
    assert len(failures) == 1 and needle in failures[0]


def test_missing_language_fails_and_out_of_scope_is_ignored():
    metrics = _passing()
    del metrics["csharp"]
    metrics["go"] = _entry(0.1, 0.1)
    assert check_targets(metrics) == ["csharp: missing from metrics"]


def test_main_exit_codes(tmp_path, capsys):
    good = tmp_path / "good.json"
    good.write_text(json.dumps(_passing()))
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"python": _entry(0.5, 0.5)}))
    assert main(["x", str(good)]) == 0
    assert main(["x", str(bad)]) == 1
    assert main(["x"]) == 2
