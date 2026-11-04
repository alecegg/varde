# ruff: noqa: S101
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import mined_pairs_curated as cur


def _pair(message, files=1, functions=2):
    return {
        "intent_evidence": {"message": message},
        "changed_files": ["a.py"] * files,
        "changed_functions": ["f"] * functions,
    }


def test_commit_filter_keeps_refactor_intent_and_drops_excluded_words():
    assert cur.commit_ok(_pair("Extract helper"), 5, cur.INCLUDE)
    assert not cur.commit_ok(_pair("Extract helper and fix crash"), 5, cur.INCLUDE)
    assert not cur.commit_ok(_pair("Extract helper", files=2), 5, cur.INCLUDE)
    assert not cur.commit_ok(_pair("Extract helper", functions=6), 5, cur.INCLUDE)
    assert not cur.commit_ok(_pair("Update docs"), 5, cur.INCLUDE)


def test_row_filter_checks_size_and_size_change():
    def row(before, after):
        return {"before": {"tokens": before}, "after": {"tokens": after}}

    assert cur.row_ok(row(1000, 1400), 1000, 0.4)
    assert not cur.row_ok(row(1000, 1401), 1000, 0.4)
    assert not cur.row_ok(row(999, 999), 1000, 0.4)
    assert not cur.row_ok({"skip": "x"}, 1000, 0.4)
