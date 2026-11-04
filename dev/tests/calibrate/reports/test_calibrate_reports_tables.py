import json
import sys
import tomllib

from varde_dev.calibrate.reports.commands import main
from varde_dev.calibrate.reports.dataset import read_dataset_files
from varde_dev.calibrate.reports.tables import build_report
from varde_dev.calibrate.reports.validation import validation_record
from varde_dev.calibrate.store import append_label_batch, import_dataset, init_dataset


def _dataset(tmp_path):
    root = init_dataset(tmp_path / "dataset", dataset_id="dataset")
    items = [
        {
            "id": f"p{n}:{side}",
            "language": "xlang",
            "task_id": f"t{n}",
            "pair_group_id": f"t{n}",
            "text": f"sample {n} {side}",
            "license": "MIT",
            "split": "test",
            "metadata": {"category": "b", "variant": "tree"},
        }
        for n in range(2)
        for side in ("a", "b")
    ]
    units = [
        {
            "id": f"p{n}",
            "kind": "pair",
            "item_ids": [f"p{n}:a", f"p{n}:b"],
            "pair_group_id": f"t{n}",
            "task_id": f"t{n}",
            "split": "test",
        }
        for n in range(2)
    ]
    tasks = [{"id": f"t{n}", "description": "compare"} for n in range(2)]
    import_dataset(root, items=items, units=units, tasks=tasks)
    labels = []
    for unit_id, _preferred, votes in (
        (
            "p0",
            "p0:a",
            [
                ("lens-one", ["p0:a", "p0:b"], "A"),
                ("lens-two", ["p0:b", "p0:a"], "B"),
                ("lens-three", ["p0:a", "p0:b"], "A"),
            ],
        ),
        (
            "p1",
            "p1:b",
            [
                ("lens-one", ["p1:a", "p1:b"], "B"),
                ("lens-two", ["p1:b", "p1:a"], "A"),
                ("lens-three", ["p1:a", "p1:b"], "A"),
            ],
        ),
    ):
        for rater_id, order, choice in votes:
            labels.append(
                {
                    "unit_id": unit_id,
                    "a_item_id": order[0],
                    "b_item_id": order[1],
                    "order_shown": order,
                    "choice": choice,
                    "confidence": "high",
                    "session_id": "s1",
                    "rater_id": rater_id,
                    "rater_kind": "llm-lens",
                    "label_source": "panel",
                    "timestamp": "2026-10-17T00:00:00Z",
                    "duration_ms": 0,
                    "lens": rater_id,
                }
            )
    append_label_batch(root, labels)
    return root


def _scores(calibration_id="cal-1"):
    return [
        {
            "unit_id": "p0",
            "scores": {"p0:a": 2, "p0:b": 1},
            "calibration_id": calibration_id,
            "formula": "vq1",
            "split": "test",
            "task_id": "t0",
        },
        {
            "unit_id": "p1",
            "scores": {"p1:a": 1, "p1:b": 2},
            "calibration_id": calibration_id,
            "formula": "vq1",
            "split": "test",
            "task_id": "t1",
        },
    ]


def _write_scores(path, calibration_id="cal-1"):
    path.write_text("".join(json.dumps(row) + "\n" for row in _scores(calibration_id)))


def test_opposite_display_orders_compare_the_same_underlying_item(
    tmp_path, capsys
) -> None:
    root = _dataset(tmp_path)
    report = build_report(
        **{key: read_dataset_files(root)[key] for key in ("labels", "units", "items")}
    )
    assert report["agreement"]["accuracy"] == 2 / 3
    stored = read_dataset_files(root)
    pair_only = build_report(
        labels=[
            label
            for label in stored["labels"]
            if label["unit_id"] == "p0" and label["lens"] != "lens-three"
        ],
        units=[unit for unit in stored["units"] if unit["id"] == "p0"],
        items=[item for item in stored["items"] if item["id"].startswith("p0:")],
    )
    assert pair_only["agreement"]["accuracy"] == 1.0
    assert report["panel"][0]["vote_vector"] == [
        {"lens": "lens-one", "vote": "A", "item_id": "p0:a"},
        {"lens": "lens-three", "vote": "A", "item_id": "p0:a"},
        {"lens": "lens-two", "vote": "A", "item_id": "p0:a"},
    ]
    assert report["panel"][0]["panel_class"] == "unanimous"
    assert report["panel"][1]["panel_class"] == "decisive"
    assert report["panel"][1]["dissent"] == [
        {"lens": "lens-three", "vote": "A", "confidence": "high"}
    ]
    assert report["panel"][1]["margin"] == {"A": 1, "B": 2, "difference": 1}
    assert report["labelled_rates"]["variant"] == [
        {
            "variant": "tree",
            "total": 2,
            "labelled": 2,
            "labelled_rate": 1.0,
            "panel_tie": 0,
            "contested": 0,
            "unlabelled": 0,
        }
    ]
    assert report["dissent_rates"] == [
        {
            "variant": "tree",
            "lens": "lens-one",
            "dissent": 0,
            "decisive": 1,
            "dissent_rate": 0.0,
        },
        {
            "variant": "tree",
            "lens": "lens-three",
            "dissent": 1,
            "decisive": 1,
            "dissent_rate": 1.0,
        },
        {
            "variant": "tree",
            "lens": "lens-two",
            "dissent": 0,
            "decisive": 1,
            "dissent_rate": 0.0,
        },
    ]
    assert len(report["over_split"]) == 6
    assert all(
        "cluster_bootstrap_95" in row and "wilson_95" in row
        for row in report["accuracy_tables"]["variant"]
    )
    assert main("report", [str(root)]) == 0
    output_a = capsys.readouterr().out
    assert main("report", [str(root)]) == 0
    assert capsys.readouterr().out == output_a


def test_validation_uses_item_keyed_scores_and_staleness_compares_stored_id(
    tmp_path,
) -> None:
    root = _dataset(tmp_path)
    dataset = read_dataset_files(root)
    scores = _scores()
    prior = {"validated_against": {"calibration": "cal-1"}}
    unchanged = validation_record(
        dataset=dataset,
        language="xlang",
        rater_id="lens-two",
        scores=scores,
        previous=prior,
    )
    changed = validation_record(
        dataset=dataset,
        language="xlang",
        rater_id="lens-two",
        scores=_scores("cal-2"),
        previous=prior,
    )
    assert unchanged["stale"] is False
    assert changed["stale"] is True
    assert unchanged["n_units"] == 2
    assert unchanged["n_non_tie"] == 2
    assert unchanged["agreement"]["accuracy"] == 1.0
    assert unchanged["agreement"]["cluster_bootstrap_95"] == [1.0, 1.0]


def test_validate_command_scores_file_and_score_command(tmp_path, capsys) -> None:
    root = _dataset(tmp_path)
    scores = tmp_path / "scores.jsonl"
    _write_scores(scores)
    args = [
        str(root),
        "--language",
        "xlang",
        "--rater",
        "lens-two",
        "--scores",
        str(scores),
        "--json",
    ]
    assert main("validate", args) == 0
    record = json.loads(capsys.readouterr().out)
    assert record["stale"] is False
    score_script = tmp_path / "emit_scores.py"
    score_script.write_text(
        "import json\nfor row in "
        + repr(_scores("cal-2"))
        + ": print(json.dumps(row))\n"
    )
    cmd_args = [
        str(root),
        "--language",
        "xlang",
        "--rater",
        "lens-two",
        "--score-cmd",
        f"{sys.executable} {score_script}",
        "--json",
    ]
    assert main("validate", cmd_args) == 0
    changed = json.loads(capsys.readouterr().out)
    assert changed["stale"] is True
    stored = tomllib.loads((root / "validation" / "xlang.toml").read_text())
    assert stored["validated_against"]["calibration"] == "cal-2"


def test_validate_command_category_and_held_out_overrides_change_record(
    tmp_path, capsys
) -> None:
    root = _dataset(tmp_path)
    scores = tmp_path / "scores.jsonl"
    _write_scores(scores)
    args = [
        str(root),
        "--language",
        "xlang",
        "--rater",
        "lens-two",
        "--scores",
        str(scores),
        "--json",
    ]
    assert main("validate", args) == 0
    default_record = json.loads(capsys.readouterr().out)
    assert default_record["n_category_b"] == 2
    assert default_record["n_held_out"] == 2

    override_args = [
        *args,
        "--category-b",
        "category-a",
        "--held-out-splits",
        "validation",
    ]
    assert main("validate", override_args) == 0
    override_record = json.loads(capsys.readouterr().out)
    assert override_record["n_category_b"] == 0
    assert override_record["n_held_out"] == 0
    assert override_record["thresholds"]["category_b_accuracy"] is False
