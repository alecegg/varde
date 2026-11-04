import json
from pathlib import Path

from varde_dev.calibrate.cli import main as calibrate_main
from varde_dev.calibrate.ranking.commands import main
from varde_dev.calibrate.ranking.core import compare_raters, rank_labels


def _dataset(root: Path, *, reverse: bool = False) -> tuple[list, list, list]:
    items = [{"id": item, "pair_group_id": "group"} for item in ("a", "b", "c")]
    units = [
        {"id": "ab", "item_ids": ["a", "b"], "pair_group_id": "group"},
        {"id": "ac", "item_ids": ["a", "c"], "pair_group_id": "group"},
        {"id": "bc", "item_ids": ["b", "c"], "pair_group_id": "group"},
    ]
    preferences = [("ab", "a", "b"), ("ac", "a", "c"), ("bc", "b", "c")]
    labels = []
    for rater, flip in (("user", reverse), ("other", False)):
        for unit, iter_chosen, iter_other in preferences:
            chosen, other = iter_chosen, iter_other
            if flip and rater == "user":
                chosen, other = iter_other, iter_chosen
            shown = [chosen, other]
            choice = "A"
            a_item, b_item = chosen, other
            if unit == "ab" and rater == "user" and not flip:
                shown = [other, chosen]
                a_item, b_item = shown
                choice = "B"
            labels.append(
                {
                    "unit_id": unit,
                    "rater_id": rater,
                    "choice": choice,
                    "a_item_id": a_item,
                    "b_item_id": b_item,
                    "order_shown": shown,
                }
            )
    return labels, units, items


def _write_dataset(root: Path, labels: list, units: list, items: list) -> None:
    root.mkdir()
    (root / "manifest.toml").write_text('dataset_id="test"\n', encoding="utf-8")
    for name, records, kind in (
        ("labels", labels, "labels"),
        ("units", units, "units"),
        ("items", items, "items"),
    ):
        rows = [
            {"record_type": kind, "schema_version": 1},
            *[{**row, "schema_version": 1} for row in records],
        ]
        (root / (name + ".jsonl")).write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
        )
    (root / "labels").mkdir()
    (root / "labels" / "batch.jsonl").write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {"record_type": "labels", "schema_version": 1},
                *[{**row, "schema_version": 1} for row in labels],
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "manifest.toml").write_text(
        'dataset_id="test"\n[[label_batches]]\nid="batch"\n', encoding="utf-8"
    )


def test_rank_cli_excludes_contested_keeps_ties_and_is_order_independent(
    tmp_path: Path, capsys
) -> None:
    labels, units, items = _dataset(tmp_path)
    labels = [
        *labels[:3],
        {
            "unit_id": "ab",
            "rater_id": "user",
            "choice": "contested",
            "timestamp": "2026-10-18T00:00:00Z",
        },
        {
            "unit_id": "ac",
            "rater_id": "user",
            "choice": "tie",
            "timestamp": "2026-10-18T00:00:00Z",
        },
    ]
    left = rank_labels(labels, units, items, "user")
    right = rank_labels(list(reversed(labels)), units, items, "user")
    assert left == right
    assert [row["item_id"] for row in left["items"]] == ["b", "a", "c"]
    assert left["excluded_count"] == 1
    assert any(match[3] == "tie" for match in left["matches"])
    dataset = tmp_path / "cli"
    _write_dataset(dataset, labels, units, items)
    assert main([str(dataset), "--rater", "user", "--json"]) == 0
    output = capsys.readouterr().out
    assert json.loads(output)["excluded_count"] == 1
    first_output = output
    batch = dataset / "labels" / "batch.jsonl"
    rows = batch.read_text(encoding="utf-8").splitlines()
    batch.write_text("\n".join([rows[0], *reversed(rows[1:])]) + "\n", encoding="utf-8")
    assert main([str(dataset), "--rater", "user", "--json"]) == 0
    assert capsys.readouterr().out == first_output
    assert main([str(dataset), "--rater", "user"]) == 0
    assert "rating" in capsys.readouterr().out
    assert calibrate_main(["rank", str(dataset), "--rater", "user", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["rater_id"] == "user"


def test_compare_reports_identical_and_reversed_rankings(
    tmp_path: Path, capsys
) -> None:
    labels, units, items = _dataset(Path("unused"))
    left = rank_labels(labels, units, items, "user")
    same = rank_labels(labels, units, items, "other")
    reversed_labels = []
    for label in labels:
        if label["rater_id"] != "user":
            continue
        reversed_labels.append(
            {
                **label,
                "a_item_id": label["b_item_id"],
                "b_item_id": label["a_item_id"],
                "order_shown": list(reversed(label["order_shown"])),
            }
        )
    reversed_rank = rank_labels(reversed_labels, units, items, "user")
    assert compare_raters(left, same)["groups"][0]["kendall_tau"] == 1.0
    comparison = compare_raters(left, reversed_rank)
    assert comparison["groups"][0]["kendall_tau"] == -1.0
    assert comparison["groups"][0]["disagreements"]
    assert compare_raters(left, same)["groups"][0]["top_agreement"] is True
    dataset = tmp_path / "compare"
    _write_dataset(dataset, labels, units, items)
    assert main([str(dataset), "--compare", "user", "other", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["groups"][0]["kendall_tau"] == 1.0
