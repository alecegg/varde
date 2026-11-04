"""Read the calibration store's public JSONL and TOML file formats."""

import json
import tomllib
from pathlib import Path
from typing import Any


def read_dataset_files(root: Path) -> dict[str, Any]:
    if not (root / "manifest.toml").is_file():
        raise FileNotFoundError(f"not a calibration dataset: {root}")
    manifest = tomllib.loads((root / "manifest.toml").read_text(encoding="utf-8"))
    labels = []
    for batch in manifest.get("label_batches", []):
        labels.extend(_read_jsonl(root / "labels" / f"{batch['id']}.jsonl", "labels"))
    return {
        "manifest": manifest,
        "items": _read_jsonl(root / "items.jsonl", "items"),
        "units": _read_jsonl(root / "units.jsonl", "units"),
        "labels": labels,
    }


def _read_jsonl(path: Path, record_type: str) -> list[dict[str, Any]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise ValueError(f"missing {record_type} schema header: {path.name}")
    header = json.loads(lines[0])
    if header.get("record_type") != record_type or header.get("schema_version") != 1:
        raise ValueError(f"unexpected {record_type} schema header: {path.name}")
    records = [json.loads(line) for line in lines[1:] if line.strip()]
    if any(record.get("schema_version") != 1 for record in records):
        raise ValueError(f"unknown {record_type} schema version: {path.name}")
    return records
