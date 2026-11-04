# ruff: noqa: S101
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import calibration_targets as targets  # noqa: E402, RUF100
from varde_code.quality_score.calibration import load_calibration  # noqa: E402, RUF100

PLACEHOLDER = (
    TOOLS.parents[3] / "code/src/varde_code/quality_score/calibration/placeholder.toml"
)
LENSES = ("lens-1", "lens-2", "lens-3")
POINT = 1_000_000


def _jsonl(path: Path, record_type: str, rows: list[dict]) -> None:
    lines = [{"record_type": record_type, "schema_version": 1}, *rows]
    path.write_text("".join(json.dumps(r) + "\n" for r in lines), encoding="utf-8")


def make_dataset(
    root: Path, pairs: list[dict], *, split: str = "dev"
) -> tuple[Path, dict]:
    """Each pair: id, task, category, variant, votes per lens, margin in points."""
    dataset = root / "dataset"
    (dataset / "labels").mkdir(parents=True)
    items, units, labels, scores = [], [], [], {}
    for pair in pairs:
        ids = [f"{pair['id']}:a", f"{pair['id']}:b"]
        meta = {"category": pair["category"], "variant": pair["variant"]}
        items += [
            {
                "id": i,
                "language": "python",
                "split": split,
                "schema_version": 1,
                "metadata": meta,
                "text": "",
            }
            for i in ids
        ]
        units.append(
            {
                "id": pair["id"],
                "item_ids": ids,
                "task_id": pair["task"],
                "split": split,
                "schema_version": 1,
            }
        )
        labels += [
            {
                "unit_id": pair["id"],
                "lens": lens,
                "rater_id": f"r-{lens}",
                "choice": vote,
                "order_shown": ids,
                "timestamp": "2026-10-31T00:00:00Z",
                "schema_version": 1,
            }
            for lens, vote in zip(LENSES, pair["votes"], strict=True)
        ]
        preferred, other = (
            (ids[0], ids[1]) if pair["votes"][0] == "A" else (ids[1], ids[0])
        )
        scores[preferred] = int(pair["margin"] * POINT) + 50 * POINT
        scores[other] = 50 * POINT
    _jsonl(dataset / "items.jsonl", "items", items)
    _jsonl(dataset / "units.jsonl", "units", units)
    _jsonl(dataset / "labels" / "batch-1.jsonl", "labels", labels)
    (dataset / "manifest.toml").write_text(
        'schema_version = 1\n[[label_batches]]\nid = "batch-1"\n',
        encoding="utf-8",
    )
    return dataset, scores


def pair(pair_id, task, variant, margin=20, category="b", votes=("A", "A", "A")):
    return {
        "id": pair_id,
        "task": task,
        "category": category,
        "variant": variant,
        "votes": votes,
        "margin": margin,
    }


def run(dataset, scores, calibration=None, anchors=(), mutation=()):
    calibration = calibration or load_calibration(PLACEHOLDER)
    return targets.evaluate(
        dataset, calibration, scores, list(mutation), list(anchors), ["python"]
    )


def test_test_restricted_item_raises(tmp_path):
    dataset, scores = make_dataset(tmp_path, [pair("p1", "t1", "tiny")], split="test")
    with pytest.raises(ValueError, match="not dev or regression"):
        run(dataset, scores)


def test_variant_under_sixty_percent_labelled_is_not_established(tmp_path):
    pairs = [pair("p1", "t1", "tiny"), pair("p2", "t2", "tiny", votes=("A", "B", "A"))]
    pairs += [
        pair(f"c{i}", f"c{i}", "tiny", votes=("A", "B", "split")) for i in range(3)
    ]
    pairs += [pair("p3", "t3", "padded"), pair("p4", "t4", "padded")]
    dataset, scores = make_dataset(tmp_path, pairs)
    q1 = run(dataset, scores)["languages"]["python"]["q1"]
    assert q1["variants"]["tiny"]["established"] is False
    assert q1["variants"]["tiny"]["labelled_rate"] == pytest.approx(2 / 5)
    assert q1["variants"]["padded"]["established"] is True
    assert q1["pooled"]["n"] == 2


def test_pooled_bound_is_informational_below_forty_pairs(tmp_path):
    pairs = [pair(f"p{i}", f"t{i}", "tiny", margin=20 if i else -5) for i in range(10)]
    dataset, scores = make_dataset(tmp_path, pairs)
    result = run(dataset, scores)
    assert result["pooled"]["decisive_b_pairs"] == 10
    assert result["pooled"]["gated"] is False
    assert result["pooled"]["pass"] is True
    assert result["pooled"]["q1"]["bootstrap_95"] is not None


def test_pooled_bound_gates_at_forty_pairs(tmp_path):
    pairs = [
        pair(f"p{i}", f"t{i}", "tiny", margin=20 if i % 4 else -5) for i in range(40)
    ]
    dataset, scores = make_dataset(tmp_path, pairs)
    pooled = run(dataset, scores)["pooled"]
    assert pooled["gated"] is True
    assert "q1" in pooled["failed_bounds"]
    assert pooled["pass"] is False


def test_labels_not_ready_when_there_are_no_votes(tmp_path):
    dataset, scores = make_dataset(tmp_path, [])
    report = run(dataset, scores)["languages"]["python"]
    assert report["labels"] == "labels not ready"
    assert report["pass"] is False
    assert "labels not ready" in report["unmet"]
    assert report["q1"]["pooled"]["rate"] is None


def test_q1_margin_share_and_q2_lens_pairs(tmp_path):
    pairs = [pair(f"p{i}", f"t{i}", "tiny", margin=20 if i else 5) for i in range(10)]
    pairs += [pair(f"m{i}", f"m{i}", "monolith", margin=20) for i in range(4)]
    pairs += [
        pair(f"a{i}", f"a{i}", "plain", category="a", margin=20, votes=("A", "A", "B"))
        for i in range(5)
    ]
    dataset, scores = make_dataset(tmp_path, pairs)
    report = run(dataset, scores)["languages"]["python"]
    assert report["q1"]["margin_10_share"] == {"n": 10, "share": 0.9}
    assert report["q1"]["pooled"]["rate"] == 1.0
    assert report["q1m"]["n"] == 4
    assert set(report["q2"]["lens_pairs"]) == {"lens-1+lens-2"}
    assert report["q2"]["lens_one_pair_meets"] is True
    assert report["q2"]["lens_pairs"]["lens-1+lens-2"]["n"] == 5


def test_q5_bands_and_inversion():
    base = load_calibration(PLACEHOLDER)
    validation = {"state": "panel-validated", "p65": 60.0, "p10": 30.0}
    scored = [
        {"couple": "c1", "role": "excellent", "points": 70.0},
        {"couple": "c1", "role": "poor", "points": 20.0},
        {"couple": "c2", "role": "excellent", "points": 50.0},
        {"couple": "c2", "role": "poor", "points": 55.0},
    ]
    q5 = targets.q5_block(scored, validation)
    assert (q5["n"], q5["in_band"], q5["rate"]) == (4, 2, 0.5)
    assert q5["excellent_below_poor"] is True
    assert targets.q5_block(scored, {})["rate"] is None
    assert base.languages["python"].state == "report-only"


def test_check_skips_report_only_languages(tmp_path):
    dataset, scores = make_dataset(tmp_path, [])
    result = run(dataset, scores)
    assert targets.check_exit(result) == 0
    entry = load_calibration(PLACEHOLDER).languages["python"]
    assert (
        dataclasses.replace(entry, validation={"state": "panel-validated"}).state
        == "panel-validated"
    )
    result["languages"]["python"]["state"] = "panel-validated"
    assert targets.check_exit(result) == 1


def test_cli_reports_labels_not_ready_without_fabricating(tmp_path, capsys):
    dataset, _ = make_dataset(tmp_path, [])
    scores_file = tmp_path / "scores.jsonl"
    scores_file.write_text("", encoding="utf-8")
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    argv = [
        "--calibration",
        str(PLACEHOLDER),
        "--dataset",
        str(dataset),
        "--scores",
        str(scores_file),
        "--mutation-pairs",
        str(empty),
        "--anchors",
        str(empty),
        "--languages",
        "python",
        "--check",
    ]
    assert targets.main(argv) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["languages"]["python"]["labels"] == "labels not ready"
