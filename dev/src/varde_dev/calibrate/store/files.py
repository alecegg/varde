"""Filesystem operations for the versioned calibration dataset."""

import hashlib
import json
import tomllib
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from varde_dev.calibrate.store.logic import (
    SCHEMA_VERSION,
    SPLITS,
    canonical_json,
    content_sha256,
    next_chain_hash,
    valid_batch_id,
    validate_records,
    verify_behaviour_test_hashes,
    verify_item_hashes,
    verify_label_chain,
    verify_unit_groups,
)

_ZERO_HASH = "0" * 64


def init_dataset(path: str | Path, dataset_id: str | None = None) -> Path:
    root = Path(path)
    root.mkdir(parents=True, exist_ok=False)
    for folder in (
        "items",
        "units",
        "tasks",
        "labels",
        "runs",
        "raters",
        "sessions",
        "validation",
    ):
        (root / folder).mkdir()
    for name, record_type in (
        ("items.jsonl", "items"),
        ("units.jsonl", "units"),
        ("tasks.jsonl", "tasks"),
    ):
        (root / name).write_text(_header(record_type), encoding="utf-8")
    manifest = {
        "dataset_id": dataset_id or root.name,
        "item_hashes": {},
        "splits": {},
        "label_batches": [],
        "chain_sha256": _ZERO_HASH,
    }
    _write_manifest(root, manifest)
    return root


def import_dataset(
    path: str | Path,
    *,
    items: Sequence[Mapping[str, Any]],
    units: Sequence[Mapping[str, Any]],
    tasks: Sequence[Mapping[str, Any]],
) -> None:
    root = Path(path)
    _assert_dataset(root)
    current_items = _read_records(root / "items.jsonl", "items")
    current_units = _read_records(root / "units.jsonl", "units")
    current_tasks = _read_records(root / "tasks.jsonl", "tasks")
    clean_items, clean_units, clean_tasks = validate_records(
        items,
        units,
        tasks,
        {"items": current_items, "units": current_units, "tasks": current_tasks},
    )
    _append_records(root / "items.jsonl", clean_items)
    _append_records(root / "units.jsonl", clean_units)
    if clean_tasks:
        tasks_by_id = {task["id"]: task for task in current_tasks}
        tasks_by_id.update({task["id"]: task for task in clean_tasks})
        _rewrite_records(root / "tasks.jsonl", "tasks", list(tasks_by_id.values()))

    manifest = _read_manifest(root)
    for item in clean_items:
        manifest["item_hashes"][item["id"]] = item["content_sha256"]
        manifest["splits"][item["id"]] = item["split"]
    _write_manifest(root, manifest)


def append_label_batch(
    path: str | Path,
    labels: Sequence[Mapping[str, Any]],
    *,
    batch_id: str | None = None,
) -> Path:
    root = Path(path)
    _assert_dataset(root)
    items = {
        record["id"]: record for record in _read_records(root / "items.jsonl", "items")
    }
    units = {
        record["id"]: record for record in _read_records(root / "units.jsonl", "units")
    }
    manifest = _read_manifest(root)
    next_number = len(manifest["label_batches"]) + 1
    label_batch_id = f"batch-{next_number:06d}" if batch_id is None else batch_id
    if not isinstance(label_batch_id, str) or not valid_batch_id(label_batch_id):
        raise ValueError(f"invalid label batch id: {label_batch_id}")
    batch_path = root / "labels" / f"{label_batch_id}.jsonl"
    if batch_path.exists():
        raise FileExistsError(f"closed label batch already exists: {label_batch_id}")

    records = [_label_with_digests(label, items, units) for label in labels]
    encoded_records = _encode_records("labels", records)
    batch_sha256 = hashlib.sha256(encoded_records.encode("utf-8")).hexdigest()
    previous_hash = manifest["chain_sha256"]
    chain_hash = next_chain_hash(previous_hash, batch_sha256)
    batch_path.write_text(encoded_records, encoding="utf-8")
    manifest["label_batches"].append(
        {
            "id": label_batch_id,
            "sha256": batch_sha256,
            "previous_chain_sha256": previous_hash,
            "chain_sha256": chain_hash,
        }
    )
    manifest["chain_sha256"] = chain_hash
    _write_manifest(root, manifest)
    return batch_path


def verify_dataset(path: str | Path) -> list[str]:
    root = Path(path)
    _assert_dataset(root)
    errors: list[str] = []
    manifest = _read_manifest(root)
    items = _read_records(root / "items.jsonl", "items")
    units = _read_records(root / "units.jsonl", "units")
    tasks = _read_records(root / "tasks.jsonl", "tasks")
    behaviour_hashes, behaviour_errors = _read_behaviour_test_hashes(root, tasks)
    errors.extend(behaviour_errors)
    errors.extend(verify_behaviour_test_hashes(tasks, behaviour_hashes))
    item_by_id = {item["id"]: item for item in items}
    unit_by_id = {unit["id"]: unit for unit in units}

    expected_sidecar = _manifest_sidecar_value(root / "manifest.toml")
    if expected_sidecar != _manifest_digest(root / "manifest.toml"):
        errors.append("manifest.toml hash mismatch")

    errors.extend(verify_item_hashes(items, manifest["item_hashes"]))
    errors.extend(verify_unit_groups(units, items))
    actual_batch_hashes: dict[str, str | None] = {}
    for batch in manifest["label_batches"]:
        batch_id = batch.get("id")
        if not isinstance(batch_id, str) or not valid_batch_id(batch_id):
            errors.append("invalid label batch id in manifest")
            continue
        batch_path = root / "labels" / f"{batch_id}.jsonl"
        if not batch_path.is_file():
            actual_batch_hashes[batch_id] = None
            continue
        actual_batch_hashes[batch_id] = hashlib.sha256(
            batch_path.read_bytes()
        ).hexdigest()
        _verify_batch_labels(batch_path, item_by_id, unit_by_id, batch_id, errors)
    errors.extend(
        verify_label_chain(
            manifest["label_batches"], actual_batch_hashes, manifest["chain_sha256"]
        )
    )
    return errors


def export_split(path: str | Path, split: str, output: str | Path) -> Path:
    root = Path(path)
    _assert_dataset(root)
    if split not in SPLITS:
        raise ValueError(f"unknown split: {split}")
    items = _read_records(root / "items.jsonl", "items")
    selected = [item for item in items if item.get("split") == split]
    destination = Path(output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(_encode_records("export", selected), encoding="utf-8")
    return destination


def _label_with_digests(
    source: Mapping[str, Any],
    items: Mapping[str, Mapping[str, Any]],
    units: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    label = dict(source)
    unit_id = label.get("unit_id")
    unit = units.get(unit_id)
    if unit is None or unit.get("kind") != "pair":
        raise ValueError(f"label requires a known pair unit: {unit_id}")
    a_id, b_id = label.get("a_item_id"), label.get("b_item_id")
    if a_id == b_id or a_id not in items or b_id not in items:
        raise ValueError(f"label {unit_id} refers to unknown or identical items")
    if {a_id, b_id} != set(unit["item_ids"]):
        raise ValueError(f"label items do not match unit {unit_id}")
    if label.get("order_shown") != [a_id, b_id]:
        raise ValueError(f"order_shown must match A and B item ids for unit {unit_id}")
    if label.get("choice") not in {"A", "B", "tie"}:
        raise ValueError(f"invalid label choice for unit {unit_id}")
    if label.get("confidence") not in {"high", "medium", "low"}:
        raise ValueError(f"invalid confidence for unit {unit_id}")
    rater_kind = label.get("rater_kind")
    if not isinstance(rater_kind, str) or rater_kind not in {
        "human",
        "llm-lens",
        "llm-personal",
    }:
        raise ValueError(f"invalid rater_kind for unit {unit_id}")
    for key in ("session_id", "rater_id", "rater_kind", "label_source", "timestamp"):
        if not isinstance(label.get(key), str) or not label[key]:
            raise ValueError(f"label {unit_id} requires {key}")
    if "tags" in label and (
        not isinstance(label["tags"], list)
        or any(not isinstance(tag, str) for tag in label["tags"])
    ):
        raise ValueError(f"label {unit_id} tags must be a list of strings")
    if not isinstance(label.get("duration_ms"), int) or label["duration_ms"] < 0:
        raise ValueError(f"label {unit_id} requires a non-negative duration_ms")
    label["a_sha256"] = items[a_id]["content_sha256"]
    label["b_sha256"] = items[b_id]["content_sha256"]
    label["schema_version"] = SCHEMA_VERSION
    return label


def _check_frozen_label_digests(
    labels: Sequence[Mapping[str, Any]],
    items: Mapping[str, Mapping[str, Any]],
    units: Mapping[str, Mapping[str, Any]],
    batch_id: str,
    errors: list[str],
) -> None:
    for label in labels:
        unit = units.get(label.get("unit_id"))
        order = label.get("order_shown", [])
        if unit is None or len(order) != 2:
            errors.append(f"invalid frozen label in {batch_id}")
            continue
        for key, item_id in zip(("a_sha256", "b_sha256"), order, strict=True):
            item = items.get(item_id)
            if item is None or content_sha256(item.get("text", "")) != label.get(key):
                errors.append(
                    f"item {item_id} changed under frozen label in {batch_id}"
                )


def _verify_batch_labels(
    batch_path: Path,
    items: Mapping[str, Mapping[str, Any]],
    units: Mapping[str, Mapping[str, Any]],
    batch_id: str,
    errors: list[str],
) -> None:
    try:
        labels = _read_records(batch_path, "labels")
    except (ValueError, OSError) as error:
        errors.append(f"invalid label batch {batch_id}: {error}")
        return
    _check_frozen_label_digests(labels, items, units, batch_id, errors)


def _read_manifest(root: Path) -> dict[str, Any]:
    with (root / "manifest.toml").open("rb") as stream:
        manifest = tomllib.load(stream)
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"unknown manifest schema version: {manifest.get('schema_version')}"
        )
    manifest.setdefault("item_hashes", {})
    manifest.setdefault("splits", {})
    manifest.setdefault("label_batches", [])
    return manifest


def _write_manifest(root: Path, manifest: Mapping[str, Any]) -> None:
    lines = [
        f"schema_version = {SCHEMA_VERSION}",
        f"dataset_id = {json.dumps(manifest['dataset_id'])}",
        f"chain_sha256 = {json.dumps(manifest['chain_sha256'])}",
        "",
        "[item_hashes]",
    ]
    for item_id, digest in sorted(manifest["item_hashes"].items()):
        lines.append(f"{json.dumps(item_id)} = {json.dumps(digest)}")
    lines.extend(("", "[splits]"))
    for item_id, split in sorted(manifest["splits"].items()):
        lines.append(f"{json.dumps(item_id)} = {json.dumps(split)}")
    for batch in manifest["label_batches"]:
        lines.extend(("", "[[label_batches]]"))
        lines.extend(
            f"{key} = {json.dumps(batch[key])}"
            for key in ("id", "sha256", "previous_chain_sha256", "chain_sha256")
        )
    manifest_path = root / "manifest.toml"
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    sidecar = (
        f"schema_version = {SCHEMA_VERSION}\n"
        f"sha256 = {json.dumps(_manifest_digest(manifest_path))}\n"
    )
    (root / "MANIFEST.sha256").write_text(sidecar, encoding="utf-8")


def _read_records(path: Path, record_type: str) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"missing schema header in {path.name}")
    header = json.loads(lines[0])
    if header.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"unknown {record_type} schema version: {header.get('schema_version')}"
        )
    if header.get("record_type") != record_type:
        raise ValueError(f"unexpected record type in {path.name}")
    records = [json.loads(line) for line in lines[1:] if line]
    for record in records:
        if record.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"unknown {record_type} record schema version")
    return records


def _append_records(path: Path, records: Sequence[Mapping[str, Any]]) -> None:
    if records:
        with path.open("a", encoding="utf-8") as stream:
            for record in records:
                stream.write(canonical_json(record) + "\n")


def _rewrite_records(
    path: Path, record_type: str, records: Sequence[Mapping[str, Any]]
) -> None:
    path.write_text(_encode_records(record_type, records), encoding="utf-8")


def _read_behaviour_test_hashes(
    root: Path, tasks: Sequence[Mapping[str, Any]]
) -> tuple[dict[str, str | None], list[str]]:
    actual_hashes: dict[str, str | None] = {}
    errors: list[str] = []
    root_path = root.resolve()
    for task in tasks:
        for reference in task.get("behaviour_tests", ()):
            relative_path = reference.get("path")
            if not isinstance(relative_path, str):
                errors.append(f"invalid behaviour-test path for task {task.get('id')}")
                continue
            file_path = (root / relative_path).resolve()
            if not file_path.is_relative_to(root_path):
                errors.append(f"behaviour-test path escapes dataset: {relative_path}")
                continue
            if not file_path.is_file():
                actual_hashes[relative_path] = None
                continue
            actual_hashes[relative_path] = hashlib.sha256(
                file_path.read_bytes()
            ).hexdigest()
    return actual_hashes, errors


def _encode_records(record_type: str, records: Sequence[Mapping[str, Any]]) -> str:
    header = {"record_type": record_type, "schema_version": SCHEMA_VERSION}
    return (
        "\n".join(
            [canonical_json(header), *(canonical_json(record) for record in records)]
        )
        + "\n"
    )


def _header(record_type: str) -> str:
    return _encode_records(record_type, [])


def _assert_dataset(root: Path) -> None:
    if not (root / "manifest.toml").is_file():
        raise FileNotFoundError(f"not a calibration dataset: {root}")


def _manifest_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_sidecar_value(path: Path) -> str:
    sidecar = tomllib.loads(
        (path.parent / "MANIFEST.sha256").read_text(encoding="utf-8")
    )
    if sidecar.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"unknown MANIFEST.sha256 schema version: {sidecar.get('schema_version')}"
        )
    return sidecar.get("sha256", "")
