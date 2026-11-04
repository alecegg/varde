"""Pure validation, canonicalization, and hash-chain operations."""

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

SCHEMA_VERSION = 1
SPLITS = ("dev", "regression", "test", "test-restricted")
_ZERO_HASH = "0" * 64
_BATCH_ID = re.compile(r"[A-Za-z0-9._-]+")
_LICENSE = re.compile(r"^[A-Za-z0-9.+() -]+$")
_LANGUAGE = re.compile(r"[A-Za-z][A-Za-z0-9_+-]*")


def content_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def validate_records(
    items: Sequence[Mapping[str, Any]],
    units: Sequence[Mapping[str, Any]],
    tasks: Sequence[Mapping[str, Any]],
    existing_records: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    existing = existing_records or {}
    existing_items = list(existing.get("items", ()))
    existing_tasks = {record["id"]: record for record in existing.get("tasks", ())}
    task_ids = set(existing_tasks)
    unit_ids = {record["id"] for record in existing.get("units", ())}
    item_ids = {record["id"] for record in existing_items}
    normalized_tasks = _normalize_tasks(tasks, existing_tasks)
    task_ids.update(record["id"] for record in normalized_tasks)
    normalized_items = _normalize_items(items, item_ids, task_ids)
    item_ids.update(record["id"] for record in normalized_items)
    groups = {record["id"]: record["pair_group_id"] for record in existing_items}
    groups.update(
        {record["id"]: record["pair_group_id"] for record in normalized_items}
    )
    normalized_units = _normalize_units(units, unit_ids, item_ids, groups, task_ids)
    return normalized_items, normalized_units, normalized_tasks


def next_chain_hash(previous_hash: str, batch_sha256: str) -> str:
    return hashlib.sha256(f"{previous_hash}:{batch_sha256}".encode("ascii")).hexdigest()


def valid_batch_id(batch_id: str) -> bool:
    return bool(_BATCH_ID.fullmatch(batch_id))


def _normalize_tasks(
    tasks: Sequence[Mapping[str, Any]], existing_tasks: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for source in tasks:
        record = dict(source)
        task_id = _required_text(record, "id", "task")
        description = _required_text(record, "description", f"task {task_id}")
        if task_id in seen_ids:
            raise ValueError(f"duplicate task id: {task_id}")
        seen_ids.add(task_id)
        existing = existing_tasks.get(task_id)
        if existing is not None:
            if existing.get("description") != description:
                raise ValueError(
                    f"task {task_id} already exists with a different description"
                )
            merged_tests = _merge_behaviour_tests(
                existing.get("behaviour_tests", ()), record.get("behaviour_tests", ())
            )
            if merged_tests != existing.get("behaviour_tests", []):
                records.append(
                    {
                        **existing,
                        "behaviour_tests": merged_tests,
                        "schema_version": SCHEMA_VERSION,
                    }
                )
            continue
        if "behaviour_tests" in record:
            record["behaviour_tests"] = _merge_behaviour_tests(
                (), record["behaviour_tests"]
            )
        record["schema_version"] = SCHEMA_VERSION
        records.append(record)
    return records


def verify_behaviour_test_hashes(
    tasks: Sequence[Mapping[str, Any]], actual_hashes: Mapping[str, str | None]
) -> list[str]:
    errors: list[str] = []
    for task in tasks:
        references = task.get("behaviour_tests", ())
        if not isinstance(references, (list, tuple)):
            errors.append(
                f"invalid behaviour-test references for task {task.get('id')}"
            )
            continue
        for reference in references:
            if not isinstance(reference, Mapping):
                errors.append(
                    f"invalid behaviour-test reference for task {task.get('id')}"
                )
                continue
            path = reference.get("path")
            expected_hash = reference.get("sha256")
            if not isinstance(path, str) or not isinstance(expected_hash, str):
                errors.append(
                    f"invalid behaviour-test reference for task {task.get('id')}"
                )
                continue
            if actual_hashes.get(path) != expected_hash:
                errors.append(f"behaviour test changed or missing: {path}")
    return errors


def verify_item_hashes(
    items: Sequence[Mapping[str, Any]], expected_hashes: Mapping[str, str]
) -> list[str]:
    actual_items = {item.get("id"): item for item in items}
    errors: list[str] = []
    for item_id, expected_hash in expected_hashes.items():
        item = actual_items.get(item_id)
        if item is None:
            errors.append(f"missing item {item_id} frozen in manifest")
            continue
        actual_hash = content_sha256(item.get("text", ""))
        if actual_hash != expected_hash:
            errors.append(f"item {item_id} changed under a frozen label or manifest")
        if item.get("content_sha256") != actual_hash:
            errors.append(f"item {item_id} content_sha256 field mismatch")
    return errors


def verify_unit_groups(
    units: Sequence[Mapping[str, Any]], items: Sequence[Mapping[str, Any]]
) -> list[str]:
    item_by_id = {item.get("id"): item for item in items}
    errors: list[str] = []
    for unit in units:
        errors.extend(_unit_group_errors(unit, item_by_id))
    return errors


def verify_label_chain(
    batches: Sequence[Mapping[str, Any]],
    actual_hashes: Mapping[str, str | None],
    final_hash: str,
) -> list[str]:
    errors: list[str] = []
    previous_hash = _ZERO_HASH
    for batch in batches:
        batch_id = batch.get("id")
        batch_hash = batch.get("sha256")
        chain_hash = batch.get("chain_sha256")
        if not isinstance(batch_id, str) or not isinstance(batch_hash, str):
            errors.append("invalid label batch entry in manifest")
            continue
        errors.extend(_batch_hash_errors(batch_id, batch_hash, actual_hashes))
        expected_chain = next_chain_hash(previous_hash, batch_hash)
        if (
            batch.get("previous_chain_sha256") != previous_hash
            or chain_hash != expected_chain
        ):
            errors.append(f"manifest hash chain changed at batch: {batch_id}")
        if isinstance(chain_hash, str):
            previous_hash = chain_hash
    if final_hash != previous_hash:
        errors.append("manifest final hash chain value changed")
    return errors


def _normalize_items(
    items: Sequence[Mapping[str, Any]], existing_ids: set[str], task_ids: set[str]
) -> list[dict[str, Any]]:
    records = _normalize_unique(items, existing_ids, "item")
    for record in records:
        item_id = record["id"]
        language = _required_text(record, "language", f"item {item_id}")
        if not _LANGUAGE.fullmatch(language):
            raise ValueError(f"invalid language for item {item_id}: {language}")
        _required_text(record, "pair_group_id", f"item {item_id}")
        text = _required_text(record, "text", f"item {item_id}")
        _validate_license(record, item_id)
        if _required_text(record, "task_id", f"item {item_id}") not in task_ids:
            raise ValueError(f"unknown task for item {item_id}: {record['task_id']}")
        _validate_split(record, item_id)
        _set_content_hash(record, item_id, text)
        record["schema_version"] = SCHEMA_VERSION
    return records


def _normalize_units(
    units: Sequence[Mapping[str, Any]],
    existing_ids: set[str],
    item_ids: set[str],
    item_groups: Mapping[str, str],
    task_ids: set[str],
) -> list[dict[str, Any]]:
    records = _normalize_unique(units, existing_ids, "unit")
    for unit in records:
        unit_id = unit["id"]
        item_refs = unit.get("item_ids")
        expected = {"pair": 2, "triple": 3, "single": 1}.get(unit.get("kind"))
        if (
            expected is None
            or not isinstance(item_refs, list)
            or len(item_refs) != expected
        ):
            raise ValueError(f"invalid item count or kind for unit {unit_id}")
        if any(ref not in item_ids for ref in item_refs):
            raise ValueError(f"unknown item in unit {unit_id}")
        group_id = _required_text(unit, "pair_group_id", f"unit {unit_id}")
        if any(item_groups[ref] != group_id for ref in item_refs):
            raise ValueError(
                f"unit {unit_id} items do not share pair_group_id {group_id}"
            )
        if _required_text(unit, "task_id", f"unit {unit_id}") not in task_ids:
            raise ValueError(f"unknown task for unit {unit_id}: {unit['task_id']}")
        _validate_split(unit, unit_id)
        unit["schema_version"] = SCHEMA_VERSION
    return records


def _normalize_unique(
    records: Sequence[Mapping[str, Any]], known_ids: set[str], kind: str
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for source in records:
        record = dict(source)
        record_id = _required_text(record, "id", kind)
        if record_id in known_ids:
            raise ValueError(f"duplicate {kind} id: {record_id}")
        known_ids.add(record_id)
        normalized.append(record)
    return normalized


def _merge_behaviour_tests(
    existing: Sequence[Mapping[str, Any]], incoming: Sequence[Mapping[str, Any]]
) -> list[dict[str, str]]:
    merged: dict[str, dict[str, str]] = {}
    for reference in (*existing, *incoming):
        path = _required_text(reference, "path", "behaviour test")
        digest = _required_text(reference, "sha256", f"behaviour test {path}")
        merged[path] = {"path": path, "sha256": digest}
    return list(merged.values())


def _required_text(record: Mapping[str, Any], key: str, owner: str) -> str:
    value = record.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{owner} requires {key}")
    return value


def _validate_license(record: Mapping[str, Any], item_id: str) -> None:
    license_id = _required_text(record, "license", f"item {item_id}")
    if not _LICENSE.fullmatch(license_id):
        raise ValueError(f"invalid license for item {item_id}: {license_id}")


def _validate_split(record: Mapping[str, Any], record_id: str) -> None:
    split = _required_text(record, "split", record_id)
    if split not in SPLITS:
        raise ValueError(f"invalid split for {record_id}: {split}")


def _set_content_hash(record: dict[str, Any], item_id: str, text: str) -> None:
    actual_hash = content_sha256(text)
    if record.get("content_sha256", actual_hash) != actual_hash:
        raise ValueError(f"content sha256 mismatch for item {item_id}")
    record["content_sha256"] = actual_hash


def _unit_group_errors(
    unit: Mapping[str, Any], item_by_id: Mapping[str, Mapping[str, Any] | None]
) -> list[str]:
    unit_id = unit.get("id", "unknown")
    item_ids = unit.get("item_ids", ())
    if not isinstance(item_ids, (list, tuple)):
        return [f"unit {unit_id} has invalid item_ids"]
    groups: set[str | None] = set()
    errors: list[str] = []
    for item_id in item_ids:
        item = item_by_id.get(item_id)
        if item is None:
            errors.append(f"unit {unit_id} references missing item {item_id}")
            continue
        groups.add(item.get("pair_group_id"))
    if errors:
        return errors
    if len(groups) != 1 or unit.get("pair_group_id") not in groups:
        errors.append(f"unit {unit_id} items do not share pair_group_id")
    return errors


def _batch_hash_errors(
    batch_id: str, expected_hash: str, actual_hashes: Mapping[str, str | None]
) -> list[str]:
    actual_hash = actual_hashes.get(batch_id)
    if actual_hash is None:
        return [f"missing label batch: {batch_id}"]
    if actual_hash != expected_hash:
        return [f"label batch changed: {batch_id}"]
    return []
