import hashlib
import json

import pytest
from varde_dev.calibrate.store import (
    append_label_batch,
    export_split,
    import_dataset,
    init_dataset,
    verify_dataset,
)


def sample_item(
    item_id: str, code: str, *, license_id: str = "MIT"
) -> dict[str, object]:
    return {
        "id": item_id,
        "language": "python",
        "task_id": "sort-values",
        "pair_group_id": "sorting-task",
        "text": code,
        "license": license_id,
        "split": "dev",
    }


def sample_unit() -> dict[str, object]:
    return {
        "id": "unit-1",
        "kind": "pair",
        "item_ids": ["item-a", "item-b"],
        "pair_group_id": "sorting-task",
        "task_id": "sort-values",
        "split": "dev",
    }


def test_init_import_label_verify_and_split_export(tmp_path):
    dataset = tmp_path / "dataset"
    init_dataset(dataset)
    assert (dataset / "items.jsonl").is_file()
    assert (dataset / "units.jsonl").is_file()
    assert (dataset / "manifest.toml").is_file()

    import_dataset(
        dataset,
        items=[
            sample_item("item-a", "def sort_a(xs): return sorted(xs)"),
            sample_item("item-b", "def sort_b(xs): return xs"),
        ],
        units=[sample_unit()],
        tasks=[{"id": "sort-values", "description": "Sort a list of values"}],
    )
    regression_item = sample_item("item-c", "def sort_c(xs): return xs")
    regression_item["split"] = "regression"
    import_dataset(dataset, items=[regression_item], units=[], tasks=[])
    labels = [
        {
            "unit_id": "unit-1",
            "a_item_id": "item-a",
            "b_item_id": "item-b",
            "order_shown": ["item-a", "item-b"],
            "choice": "A",
            "confidence": "high",
            "session_id": "session-1",
            "rater_id": "rater-1",
            "rater_kind": "human",
            "label_source": "duel",
            "timestamp": "2026-10-17T12:00:00Z",
            "duration_ms": 1000,
        }
    ]
    batch_path = append_label_batch(dataset, labels)
    stored_label = json.loads(batch_path.read_text().splitlines()[1])
    assert (
        stored_label["a_sha256"]
        == hashlib.sha256(b"def sort_a(xs): return sorted(xs)").hexdigest()
    )
    assert (
        stored_label["b_sha256"]
        == hashlib.sha256(b"def sort_b(xs): return xs").hexdigest()
    )
    assert verify_dataset(dataset) == []

    output = tmp_path / "export.jsonl"
    export_split(dataset, "dev", output)
    records = [json.loads(line) for line in output.read_text().splitlines()[1:]]
    assert [record["id"] for record in records] == ["item-a", "item-b"]
    assert all(record["schema_version"] == 1 for record in records)


def test_import_rejects_missing_group_invalid_license_and_duplicate(tmp_path):
    dataset = tmp_path / "dataset"
    init_dataset(dataset)
    invalid = sample_item("item-a", "pass")
    del invalid["pair_group_id"]
    with pytest.raises(ValueError, match="pair_group_id"):
        import_dataset(dataset, items=[invalid], units=[], tasks=[])

    with pytest.raises(ValueError, match="license"):
        import_dataset(
            dataset,
            items=[sample_item("item-a", "pass", license_id="")],
            units=[],
            tasks=[],
        )

    task = {"id": "sort-values", "description": "Sort"}
    invalid_language = sample_item("item-a", "pass")
    invalid_language["language"] = "not a language"
    with pytest.raises(ValueError, match="language"):
        import_dataset(dataset, items=[invalid_language], units=[], tasks=[task])

    with pytest.raises(ValueError, match="unknown task"):
        import_dataset(
            dataset, items=[sample_item("item-a", "pass")], units=[], tasks=[]
        )

    bad_hash = sample_item("item-a", "pass")
    bad_hash["content_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="content sha256"):
        import_dataset(dataset, items=[bad_hash], units=[], tasks=[task])

    with pytest.raises(ValueError, match="do not share pair_group_id"):
        import_dataset(
            dataset,
            items=[
                sample_item("item-a", "a"),
                {**sample_item("item-b", "b"), "pair_group_id": "another-task"},
            ],
            units=[sample_unit()],
            tasks=[task],
        )

    good = sample_item("item-a", "pass")
    import_dataset(dataset, items=[good], units=[], tasks=[task])
    with pytest.raises(ValueError, match="duplicate"):
        import_dataset(dataset, items=[good], units=[], tasks=[])


def test_batches_are_closed_and_verify_names_changed_batch(tmp_path):
    dataset = tmp_path / "dataset"
    init_dataset(dataset)
    import_dataset(
        dataset,
        items=[sample_item("item-a", "a"), sample_item("item-b", "b")],
        units=[sample_unit()],
        tasks=[{"id": "sort-values", "description": "Sort"}],
    )
    batch_path = append_label_batch(
        dataset,
        [
            {
                "unit_id": "unit-1",
                "a_item_id": "item-a",
                "b_item_id": "item-b",
                "order_shown": ["item-a", "item-b"],
                "choice": "tie",
                "confidence": "low",
                "session_id": "s",
                "rater_id": "r",
                "rater_kind": "human",
                "label_source": "duel",
                "timestamp": "now",
                "duration_ms": 1,
            }
        ],
    )
    with pytest.raises(FileExistsError):
        append_label_batch(dataset, [], batch_id=batch_path.stem)

    batch_path.write_text(batch_path.read_text() + "\n")
    assert "batch-000001" in " ".join(verify_dataset(dataset))


def test_verify_fails_when_item_changes_under_frozen_label(tmp_path):
    dataset = tmp_path / "dataset"
    init_dataset(dataset)
    import_dataset(
        dataset,
        items=[sample_item("item-a", "a"), sample_item("item-b", "b")],
        units=[sample_unit()],
        tasks=[{"id": "sort-values", "description": "Sort"}],
    )
    append_label_batch(
        dataset,
        [
            {
                "unit_id": "unit-1",
                "a_item_id": "item-a",
                "b_item_id": "item-b",
                "order_shown": ["item-a", "item-b"],
                "choice": "A",
                "confidence": "high",
                "session_id": "s",
                "rater_id": "r",
                "rater_kind": "human",
                "label_source": "duel",
                "timestamp": "now",
                "duration_ms": 1,
            }
        ],
    )
    item_lines = (dataset / "items.jsonl").read_text().splitlines()
    changed_item = json.loads(item_lines[1])
    changed_item["text"] = "changed"
    item_lines[1] = json.dumps(changed_item)
    (dataset / "items.jsonl").write_text("\n".join(item_lines) + "\n")
    errors = verify_dataset(dataset)
    assert any("item-a" in error and "frozen" in error for error in errors)


def test_verify_rejects_unknown_file_schema_version(tmp_path):
    dataset = tmp_path / "dataset"
    init_dataset(dataset)
    (dataset / "tasks.jsonl").write_text(
        '{"record_type":"tasks","schema_version":99}\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="unknown tasks schema version"):
        verify_dataset(dataset)


def test_verify_reports_unit_item_missing_from_items_file(tmp_path):
    dataset = tmp_path / "dataset"
    init_dataset(dataset)
    import_dataset(
        dataset,
        items=[sample_item("item-a", "a"), sample_item("item-b", "b")],
        units=[sample_unit()],
        tasks=[{"id": "sort-values", "description": "Sort"}],
    )
    unit_lines = (dataset / "units.jsonl").read_text().splitlines()
    unit = json.loads(unit_lines[1])
    unit["item_ids"][0] = "missing-item"
    unit_lines[1] = json.dumps(unit)
    (dataset / "units.jsonl").write_text("\n".join(unit_lines) + "\n")

    errors = verify_dataset(dataset)
    assert "unit unit-1 references missing item missing-item" in errors


def test_verify_walks_label_chain_in_manifest_order(tmp_path):
    dataset = tmp_path / "dataset"
    init_dataset(dataset)
    append_label_batch(dataset, [], batch_id="batch-z")
    append_label_batch(dataset, [], batch_id="batch-a")

    assert verify_dataset(dataset) == []


def test_label_batch_id_and_label_fields_are_validated(tmp_path):
    dataset = tmp_path / "dataset"
    init_dataset(dataset)
    import_dataset(
        dataset,
        items=[sample_item("item-a", "a"), sample_item("item-b", "b")],
        units=[sample_unit()],
        tasks=[{"id": "sort-values", "description": "Sort"}],
    )
    for invalid_id in ("../outside", "batch/child", "has space", "", "é"):
        with pytest.raises(ValueError, match="invalid label batch id"):
            append_label_batch(dataset, [], batch_id=invalid_id)

    label = {
        "unit_id": "unit-1",
        "a_item_id": "item-a",
        "b_item_id": "item-b",
        "order_shown": ["item-a", "item-b"],
        "choice": "A",
        "confidence": "high",
        "session_id": "session-1",
        "rater_id": "rater-1",
        "rater_kind": "human",
        "label_source": "duel",
        "timestamp": "now",
        "duration_ms": 1,
    }
    for field, invalid_value, message in (
        ("rater_kind", "automation", "rater_kind"),
        ("label_source", 3, "label_source"),
        ("tags", "naming", "tags"),
        ("tags", ["naming", 1], "tags"),
    ):
        invalid_label = {**label, field: invalid_value}
        with pytest.raises(ValueError, match=message):
            append_label_batch(dataset, [invalid_label])
