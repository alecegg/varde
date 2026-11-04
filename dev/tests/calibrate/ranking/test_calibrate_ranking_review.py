import datetime as dt
import hashlib
import json
from itertools import combinations
from pathlib import Path

from varde_dev.calibrate.panel.commands import main as panel_main
from varde_dev.calibrate.ranking.adaptive import run_adaptive_loop
from varde_dev.calibrate.ranking.commands import main as rank_main
from varde_dev.calibrate.ranking.core import rank_labels
from varde_dev.calibrate.reports import panel_label
from varde_dev.calibrate.store import import_dataset, init_dataset

NOW = dt.datetime(2026, 10, 19, 9, 30, tzinfo=dt.UTC)


def _pair_data(count: int = 2):
    items = [
        {
            "id": chr(97 + index),
            "pair_group_id": "g",
            "content_sha256": hashlib.sha256(chr(97 + index).encode()).hexdigest(),
        }
        for index in range(count)
    ]
    units = [
        {
            "id": f"u{left}{right}",
            "item_ids": [items[left]["id"], items[right]["id"]],
            "pair_group_id": "g",
        }
        for left, right in combinations(range(count), 2)
    ]
    return items, units


def _label(
    unit: str,
    a: str,
    b: str,
    choice: str,
    rater: str = "judge",
    timestamp: str = "2026-10-17T00:00:00Z",
):
    return {
        "unit_id": unit,
        "rater_id": rater,
        "a_item_id": a,
        "b_item_id": b,
        "order_shown": [a, b],
        "choice": choice,
        "timestamp": timestamp,
    }


def test_votes_only_uses_canonical_item_order_and_public_panel_rule() -> None:
    items, units = _pair_data()
    cases = [
        ("A", ["A", "A", "A"], 0),
        ("decisive", ["A", "A", "B"], 0),
        ("tie", ["tie", "tie", "A"], 0),
        ("contested", ["A", "B", "tie"], 1),
    ]
    for _name, votes, excluded in cases:
        result = rank_labels(
            [{"unit_id": "u01", "rater_id": "judge", "votes": votes}],
            units,
            items,
            "judge",
        )
        label_class, _ = panel_label(votes)
        assert result["contested_count"] == excluded
        assert result["unresolved_count"] == 0
        if label_class in {"unanimous", "decisive"}:
            assert result["matches"] == [("g", "a", "b", "x")]
        elif label_class == "panel-tie":
            assert result["matches"] == [("g", "a", "b", "tie")]
        else:
            assert result["matches"] == []


def test_digest_resolution_latest_label_and_unresolved_count() -> None:
    items, units = _pair_data()
    old = _label("u01", "a", "b", "A", timestamp="2026-10-17T00:00:00Z")
    latest = {
        "unit_id": "u01",
        "rater_id": "judge",
        "choice": "B",
        "a_sha256": items[0]["content_sha256"],
        "b_sha256": items[1]["content_sha256"],
        "timestamp": "2026-10-18T00:00:00Z",
    }
    result = rank_labels([latest, old], units, items, "judge")
    assert result["matches"] == [("g", "b", "a", "x")]
    unresolved = rank_labels(
        [{"unit_id": "u01", "rater_id": "judge", "choice": "A", "a_sha256": "missing"}],
        units,
        items,
        "judge",
    )
    assert unresolved["unresolved_count"] == 1
    assert unresolved["contested_count"] == 0


def test_two_raters_opposite_orders_choose_same_item_and_empty_rater_errors(
    tmp_path: Path, capsys
) -> None:
    items, units = _pair_data()
    labels = [
        _label("u01", "a", "b", "A", "first"),
        _label("u01", "b", "a", "B", "second"),
    ]
    first = rank_labels(labels, units, items, "first")
    second = rank_labels(labels, units, items, "second")
    assert first["matches"] == second["matches"] == [("g", "a", "b", "x")]

    dataset = tmp_path / "empty"
    _write_dataset(dataset, items, units, labels)
    assert rank_main([str(dataset), "--rater", "unknown"]) == 1
    assert "no labels" in capsys.readouterr().err
    assert rank_main([str(dataset), "--compare", "first", "unknown"]) == 1
    assert "no labels" in capsys.readouterr().err


def test_hand_computed_rating_error_and_rank_intervals() -> None:
    items, units = _pair_data()
    result = rank_labels([_label("u01", "a", "b", "A")], units, items, "judge")
    rows = {row["item_id"]: row for row in result["items"]}
    assert rows["a"]["rating"] == 0.33741581
    assert rows["b"]["rating"] == -0.33741581
    assert rows["a"]["standard_error"] == 0.91951661
    assert rows["b"]["standard_error"] == 0.91951661
    assert rows["a"]["rank_interval"] == [1, 2]
    assert rows["b"]["rank_interval"] == [1, 2]


def test_panel_rater_aggregates_stored_lens_labels_by_item_id(
    tmp_path: Path, capsys
) -> None:
    items, units = _pair_data()
    labels = [
        _label("u01", "a", "b", "A", lens, "2026-10-17T00:00:00Z")
        for lens in ("lens-one", "lens-three")
    ]
    labels.append(
        {
            **_label("u01", "b", "a", "B", "lens-two"),
            "lens": "lens-two",
            "rater_kind": "llm-lens",
            "label_source": "panel",
        }
    )
    labels = [
        {
            **label,
            "lens": label.get("lens", label["rater_id"]),
            "rater_kind": "llm-lens",
            "label_source": "panel",
        }
        for label in labels
    ]
    dataset = tmp_path / "stored-panel"
    _write_dataset(dataset, items, units, labels)
    assert rank_main([str(dataset), "--rater", "panel", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["matches"] == [["g", "a", "b", "x"]]


def _write_dataset(root: Path, items, units, labels):
    root.mkdir()
    (root / "manifest.toml").write_text(
        'dataset_id="ranking-test"\n[[label_batches]]\nid="batch"\n', encoding="utf-8"
    )
    for name, kind, records in (
        ("items.jsonl", "items", items),
        ("units.jsonl", "units", units),
    ):
        (root / name).write_text(
            "\n".join(
                json.dumps(row)
                for row in [
                    {"record_type": kind, "schema_version": 1},
                    *[{**row, "schema_version": 1} for row in records],
                ]
            )
            + "\n",
            encoding="utf-8",
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


def test_rank_reads_actual_panel_runner_run_files(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    dataset = init_dataset(tmp_path / "dataset")
    items, units = _pair_data()
    imported_items = [
        {
            **item,
            "language": "python",
            "task_id": "g",
            "text": item["id"],
            "license": "MIT",
            "split": "dev",
        }
        for item in items
    ]
    imported_units = [
        {**unit, "kind": "pair", "task_id": "g", "split": "dev"} for unit in units
    ]
    import_dataset(
        dataset,
        items=imported_items,
        units=imported_units,
        tasks=[{"id": "g", "description": "compare"}],
    )
    lens = tmp_path / "judge.md"
    notes = tmp_path / "idiom.md"
    lens.write_text("Judge which implementation is clearer", encoding="utf-8")
    notes.write_text("Use Python conventions", encoding="utf-8")
    executable = tmp_path / "fake-panel-client"
    count = tmp_path / "client-count"
    executable.write_text(
        f"""#!/bin/sh
if [ "$1" = "--version" ]; then echo fake-1; exit 0; fi
count=0
[ -f {str(count)!r} ] && read count < {str(count)!r}
count=$((count + 1))
echo "$count" > {str(count)!r}
output=''
while [ "$#" -gt 0 ]; do
  if [ "$1" = "-o" ]; then shift; output="$1"; fi
  shift
done
if [ "$count" -le 2 ]; then choice=A; else choice=B; fi
printf '{{"choice":"%s","confidence":"high"}}' "$choice" > "$output"
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    window = tmp_path / "window.toml"
    window.write_text(
        'start="2026-10-19T09:00:00Z"\nend="2026-10-19T10:00:00Z"\ncap_per_hour=20\nstop_rule="stop_on_first_limit_message"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("VARDE_CALIBRATE_ALLOW_LIVE", "1")
    args = [
        str(dataset),
        "--lens",
        str(lens),
        "--idiom-notes",
        str(notes),
        "--client-path",
        str(executable),
        "--run-id",
        "judge-run",
        "--window-file",
        str(window),
    ]
    assert panel_main(args, clock=lambda: NOW) == 0
    assert count.read_text().strip() == "4"
    assert rank_main([str(dataset), "--rater", "judge", "--json"]) == 0
    result = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert result["matches"] == [["g", "a", "b", "x"]]
    assert result["items"][0]["item_id"] == "a"


def test_adaptive_rule_stop_precedes_budget_and_returns_k_pairs(tmp_path: Path) -> None:
    items, units = _pair_data(4)
    preference = {"a": 4, "b": 3, "c": 2, "d": 1}
    calls = []

    def judge(pairs):
        calls.append(list(pairs))
        return [
            _label(unit, a, b, "A" if preference[a] > preference[b] else "B")
            for _, a, b in pairs
            for unit in [
                next(row["id"] for row in units if set(row["item_ids"]) == {a, b})
            ]
        ]

    stopped = run_adaptive_loop(
        [],
        units,
        items,
        "judge",
        judge,
        settings={"k": 2, "repeats": 1, "max_calls": 100},
    )
    assert stopped["stop_state"]["stop"] is True
    assert stopped["budget_exhausted"] is False
    assert all(len(batch) == 2 for batch in calls)

    three_items, three_units = _pair_data(3)

    def judge_all(pairs):
        return [
            _label(
                next(
                    row["id"]
                    for row in three_units
                    if set(row["item_ids"]) == {left, right}
                ),
                left,
                right,
                "A" if preference[left] > preference[right] else "B",
            )
            for _, left, right in pairs
        ]

    exactly_at_budget = run_adaptive_loop(
        [],
        three_units,
        three_items,
        "judge",
        judge_all,
        settings={"k": 3, "repeats": 1, "max_calls": 6},
    )
    assert exactly_at_budget["stop_state"]["stop"] is True
    assert exactly_at_budget["calls_used"] == 6
    assert exactly_at_budget["budget_exhausted"] is False

    budget = run_adaptive_loop(
        [],
        units,
        items,
        "judge",
        judge,
        settings={"k": 2, "repeats": 1, "max_calls": 4},
    )
    assert budget["stop_state"]["stop"] is False
    assert budget["budget_exhausted"] is True
