import subprocess
from pathlib import Path

from varde_dev.calibrate.ranking.adaptive import run_adaptive_loop
from varde_dev.calibrate.ranking.commands import main
from varde_dev.calibrate.ranking.plan import plan_next


def test_plan_and_fake_client_loop_respect_stop_rule_and_budget(tmp_path: Path) -> None:
    items = [{"id": "a", "pair_group_id": "g"}, {"id": "b", "pair_group_id": "g"}]
    units = [{"id": "ab", "item_ids": ["a", "b"], "pair_group_id": "g"}]
    labels: list[dict[str, object]] = []
    plan = plan_next(labels, units, items, "judge", settings={"k": 1, "repeats": 2})
    assert plan["pairs"] == [("g", "a", "b")]
    assert plan["projected_remaining_calls"] == 4

    client = tmp_path / "fake-client"
    count = tmp_path / "count"
    client.write_text(f"#!/bin/sh\necho call >> {count}\n", encoding="utf-8")
    client.chmod(0o755)

    def run_round(pairs):
        for pair in pairs:
            for _ in range(4):
                subprocess.run([str(client)], check=True)  # noqa: S603 - Test executes its compiled fixture client.
            _group, left, right = pair
            return [
                {
                    "unit_id": "ab",
                    "rater_id": "judge",
                    "choice": "A",
                    "a_item_id": left,
                    "b_item_id": right,
                    "order_shown": [left, right],
                }
            ]
        return []

    result = run_adaptive_loop(
        labels,
        units,
        items,
        "judge",
        run_round,
        settings={"k": 1, "repeats": 2, "max_calls": 4},
    )
    assert result["stop_state"]["stop"] is True
    assert result["calls_used"] == 4
    assert len(count.read_text().splitlines()) == 4


def test_plan_command_has_no_client_execution(tmp_path: Path, capsys) -> None:
    data = tmp_path / "dataset"
    data.mkdir()
    (data / "manifest.toml").write_text(
        'dataset_id="test"\n[[label_batches]]\nid="b"\n', encoding="utf-8"
    )
    (data / "items.jsonl").write_text(
        '{"record_type":"items","schema_version":1}\n{"id":"a","pair_group_id":"g","schema_version":1}\n{"id":"b","pair_group_id":"g","schema_version":1}\n{"id":"c","pair_group_id":"g","schema_version":1}\n',
        encoding="utf-8",
    )
    (data / "units.jsonl").write_text(
        '{"record_type":"units","schema_version":1}\n{"id":"ab","item_ids":["a","b"],"pair_group_id":"g","schema_version":1}\n{"id":"ac","item_ids":["a","c"],"pair_group_id":"g","schema_version":1}\n{"id":"bc","item_ids":["b","c"],"pair_group_id":"g","schema_version":1}\n',
        encoding="utf-8",
    )
    (data / "labels").mkdir()
    (data / "labels" / "b.jsonl").write_text(
        '{"record_type":"labels","schema_version":1}\n{"unit_id":"ab","rater_id":"judge","choice":"A","a_item_id":"a","b_item_id":"b","order_shown":["a","b"],"timestamp":"1","schema_version":1}\n',
        encoding="utf-8",
    )
    client = tmp_path / "fake-client"
    count = tmp_path / "dry-run-count"
    client.write_text(f"#!/bin/sh\necho call >> {count}\n", encoding="utf-8")
    client.chmod(0o755)
    assert (
        main([str(data), "--rater", "judge", "--plan-next", "--lens-count", "3"]) == 0
    )
    output = capsys.readouterr().out
    assert "g/a/c" in output
    assert "Projected remaining calls: 24" in output
    assert not count.exists()
