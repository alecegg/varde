import hashlib
from dataclasses import replace
import json
import tomllib
from pathlib import Path

import pytest

from varde_code.quality_score.calibration import load_calibration
from varde_code.quality_score.scoring import score_scope

LABELS = Path(__file__).parent / "fixtures/vq1.toml"
CALIBRATION = (
    Path(__file__).parents[3]
    / "src/varde_code/quality_score/calibration/placeholder.toml"
)


def _legacy_calibration():
    """Placeholder pinned to the pre-v7 strengths and limits."""
    calibration = load_calibration(CALIBRATION)
    strengths = {
        **calibration.global_strengths,
        "A": 2_000_000,
        "wL": 600_000,
        "w": 1_000_000,
    }
    limits = {name: dict(values) for name, values in calibration.limits.items()}
    limits["strength"] = {name: (500_000, 2_000_000) for name in limits["strength"]}
    return replace(calibration, global_strengths=strengths, limits=limits)


def _record(path: str, cognitive: int) -> dict[str, object]:
    return {
        "contract": "facts-2",
        "path": path,
        "language": "python",
        "module": "golden",
        "tokens": 1000,
        "structure_confidence": "normal",
        "functions": [
            {
                "id": f"{path}::work",
                "line": 1,
                "tokens": 50,
                "cognitive": cognitive,
                "params": 1,
                "depth": 1,
                "fan_out": 1,
                "tree_size": 1,
                "name_issues": [],
                "fragment_scope": None,
            }
        ],
    }


def _score(cognitive: int) -> int:
    scored = score_scope(
        [_record("golden/sample.py", cognitive)], _legacy_calibration()
    )
    return scored.files[0].score


def _read_labels(path: Path) -> dict:
    labels = tomllib.loads(path.read_text(encoding="utf-8"))
    entries = {key: labels.get(key, []) for key in ("pairs", "anchors")}
    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()
    assert labels["labels"]["sha256"] == hashlib.sha256(canonical).hexdigest()
    return entries


def _assert_golden_labels(labels: dict, scores: dict[str, int]) -> None:
    for pair in labels["pairs"]:
        preferred = scores[pair["preferred"]]
        other = scores[pair["other"]]
        assert preferred > other
        assert preferred - other >= pair.get("minimum_margin", 0)
    for anchor in labels["anchors"]:
        assert anchor["minimum_score"] <= scores[anchor["id"]]
        assert scores[anchor["id"]] <= anchor["maximum_score"]


def test_empty_labels_are_a_valid_skeleton_input(tmp_path):
    empty = tmp_path / "empty.toml"
    empty.write_text(
        '[labels]\nsha256 = "'
        + hashlib.sha256(b'{"anchors":[],"pairs":[]}').hexdigest()
        + '"\n',
        encoding="utf-8",
    )

    _assert_golden_labels(_read_labels(empty), {})


def test_stored_labels_assert_ordering_margin_and_anchor_bands():
    labels = _read_labels(LABELS)
    scores = {
        "preferred": _score(5),
        "other": _score(90),
        "excellent": _score(5),
        "poor": _score(90),
    }

    _assert_golden_labels(labels, scores)


def test_inverted_label_fails_the_golden_assertion():
    labels = {"pairs": [{"preferred": "other", "other": "preferred"}], "anchors": []}
    scores = {"preferred": _score(5), "other": _score(90)}

    with pytest.raises(AssertionError):
        _assert_golden_labels(labels, scores)
